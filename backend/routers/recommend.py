# backend/routers/recommend.py

import os, json
import requests
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from database import SessionLocal
from .auth import get_current_user_token  # JWT 인증 (user_id)
import models
import openai
import datetime as dt
from zoneinfo import ZoneInfo
from .search import google_search_cse

openai.api_key = os.getenv("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY_HERE")

router = APIRouter(prefix="/recommend", tags=["recommend"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def extract_movie_keyword(user_query: str) -> str:
    """
    사용자 문장을 TMDB 검색에 유효한 간단 키워드로 치환.
    여긴 아주 단순 예시로, '개봉' '볼만한' 등 빼고 '영화'만 남기거나,
    혹은 '최근 개봉' 정도만 유지.
    """
    # 예: "최근에 개봉한 영화 중에 볼만한 영화를 추천해줘."
    # -> "최근 개봉 영화"
    # 실제론 더 정교하게 처리 가능
    if not user_query.strip():
        return "영화"
    # 간단히:
    if "개봉" in user_query:
        return "최근 개봉 영화"
    return user_query  # fallback

def search_tmdb_and_create_cards(
    db: Session,
    user_query: str,
    rec_type: str = "movie"
):
    """
    1) TMDB 검색
    2) 결과를 rec_cards 테이블에 저장
    """
    tmdb_api_key = os.getenv("TMDB_API_KEY", "")  # 환경변수
    if not tmdb_api_key:
        print("TMDB_API_KEY not set!")
        return

    # TMDB /search/movie 예시
    # 문서: https://developers.themoviedb.org/3/search/search-movies
    keyword = extract_movie_keyword(user_query)

    if keyword == "최근 개봉 영화":
        now = dt.date.today()
        start_date = (now - dt.timedelta(days=30)).isoformat()  # 30일 전
        end_date   = now.isoformat()

        # GET /discover/movie?primary_release_date.gte=YYYY-MM-DD&primary_release_date.lte=YYYY-MM-DD
        params = {
            "api_key": tmdb_api_key,
            "language": "ko-KR",
            "region": "KR",                    # 한국 기준
            "with_release_type": "2|3",        # theatrical
            "sort_by": "release_date.desc",    # 로컬 릴리즈 날짜 기준 정렬
            "release_date.gte": start_date,    # 이 지역(kr)의 개봉일이 start_date ~ end_date
            "release_date.lte": end_date,
            "page": 1,
            "include_adult": "false"
        }
        url = "https://api.themoviedb.org/3/discover/movie"
    else:
        params = {
            "api_key": tmdb_api_key,
            "query": keyword,
            "language": "ko-KR",
            "page": 1,
            "include_adult": "false",
            "watch_region": "KR"
        }
        print(params)
        url = "https://api.themoviedb.org/3/search/movie"
    print("[TMDB] Request params:", params)
    resp = requests.get(url, params=params)
    if resp.status_code != 200:
        print(f"TMDB search error: {resp.text}")
        return

    data = resp.json()
    results = data.get("results", [])
    print("[TMDB] results:", results)
    print(results)
    if not results:
        return

    for i, r in enumerate(results):
        # ID, title, overview, release_date ...
        movie_title = r.get("title") or "(no title)"
        overview = r.get("overview") or ""
        movie_id = r.get("id")

        # TMDB 사이트 링크
        link = f"https://www.themoviedb.org/movie/{movie_id}"

        # RecCard 생성
        card_id = f"{rec_type}_{i}_{int(dt.datetime.utcnow().timestamp())}"
        new_card = models.RecCard(
            id       = card_id,
            type     = rec_type,
            title    = movie_title,
            subtitle = overview,
            url      = link,
            reason   = f"TMDB 검색: '{user_query}'",
            tags     = [rec_type, "tmdb_search"]
        )
        db.add(new_card)
    db.commit()

def filter_recent_movies_with_llm(items: list[dict], user_query: str = "") -> list[dict]:
    """
    GPT에게 items[]를 주고,
    "최근 (한 달 이내) 개봉/개봉 예정인 영화"만 남기고 나머지는 제외하게 한다.

    여기서 user_query를 시스템 프롬프트에 삽입해,
    "사용자가 실제로 원한 내용"을 LLM이 파악할 수 있게 함.
    """

    system_prompt = f"""
        The user asked: '{user_query}'.

        We have these search results about movies. 
        If none mention an explicit release date, do your best guess. 
        Never return an empty array. 
        At least pick something that might be relevant to recently released or recommended movies. 
        Output in valid JSON array.
        """
    user_msg = { "results": items }
    print(system_prompt)

    try:
        completion = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            temperature=0.0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": json.dumps(user_msg)}
            ]
        )
        filtered_json = completion.choices[0].message["content"]
        # 예: '[{"title":"...","snippet":"...","link":"..."}, ...]'
        final_list = json.loads(filtered_json)
        return final_list
    except:
        return []

def search_cse_and_create_cards(
    db: Session,
    query: str,               # 실제 구글 검색에 쓸 문장 (사용자 입력)
    rec_type: str,
    client_tz: dt.tzinfo = None,
    user_query: str = ""      # LLM 필터에 '원본 질문'으로 넘길 문장
):
    """
    1) Google Custom Search (페이징 + 최대 50개, 최근 3개월)
    2) LLM 필터 -> '최근 개봉 영화'에 진짜 부합하는 항목만
    3) RecCard DB 생성
    """

    print(query)
    print(user_query)
    date_restrict = "m3"  # 최근 3개월
    sort_method   = "date"
    items = google_search_cse(
        query=user_query,    # ← 사용자가 입력한 문장 전체로 검색
        num=50,
        date_restrict=date_restrict,
        sort=sort_method
    )
    print(items)
    if not items:
        return

    # 2) LLM 필터
    chunks = [items[i:i+10] for i in range(0, len(items), 10)]
    final_items = []
    for chunk in chunks:
        partial_filtered = filter_recent_movies_with_llm(chunk, user_query=user_query)
        final_items.extend(partial_filtered)
    print(final_items)
    if not final_items:
        return

    # 3) RecCard DB 저장
    for i, it in enumerate(final_items):
        # 만약 it가 dict가 아니면 스킵
        if not isinstance(it, dict):
            continue
        
        title = it.get("title","(no title)")
        snippet = it.get("snippet","")
        link = it.get("link","")

        card_id = f"{rec_type}_{i}_{int(dt.datetime.utcnow().timestamp())}"
        new_card = models.RecCard(
            id       = card_id,
            type     = rec_type,
            title    = title,
            subtitle = snippet,
            url      = link,
            reason   = f"'{query}' -> LLM 필터 통과",
            tags     = [rec_type, "google_cse", "recent"]
        )
        db.add(new_card)
    db.commit()

@router.get("/")
def get_recommendations(
    types: Optional[str] = Query(None, description="예: content,learn,movie"),
    limit: int = Query(5, description="결과 최대 개수"),
    tz: Optional[str] = Query(None),
    user_query: Optional[str] = Query(None, description="사용자 질문(예: 최근에 개봉한 영화 중에 볼만한거.. )"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user_token),
):
    """
    GET /recommend?types=content,learn,movie&user_query=...
      - movie일 땐 TMDB 검색 / 그 외는 기존 구글CSE+ChatGPT
      - 결과 중복제거 후 limit개 반환
    """

    # 1) tzinfo
    if tz:
        try:
            client_tz = ZoneInfo(tz)
        except Exception:
            client_tz = dt.timezone.utc
    else:
        client_tz = dt.timezone.utc

    # 2) 파라미터 처리
    type_list = []
    if types:
        type_list = [t.strip() for t in types.split(",") if t.strip()]
    print(type_list)

    # 3) 만약 "movie"가 포함되어 있으면 -> TMDB 검색
    #    (만약 "movie" 외 다른 것도 있으면? -> 여기서는 우선 movie 우선)
    if "movie" in type_list:
        search_txt = user_query if user_query else "최근 개봉한 영화"
        # TMDB 검색으로 rec_cards 추가
        search_tmdb_and_create_cards(
            db=db,
            user_query=search_txt,
            rec_type="movie"
        )

    # 4) 남아있는 type_list (content, learn 등) -> 구글+ChatGPT
    #    예) "content, movie"면 위에서 "movie" 처리 -> 남은건 "content"
    elif type_list:
        # 하나 이상 남았다면 -> ex) "content"
        # 만약 여러개(learn, wellness...)라면 -> 구글+ChatGPT 처리
        for t in type_list:
            # ex) user_query="백엔드 학습자료"
            #    search_cse_and_create_cards(..., rec_type=t)
            search_txt = user_query if user_query else t
            search_cse_and_create_cards(
                db=db,
                query=search_txt,
                rec_type=t,
                client_tz=client_tz,
                user_query=search_txt
            )
            break

    # 5) DB에서 최종 후보 쿼리 (movie, content, etc)
    q = db.query(models.RecCard)
    # 만약 types==None, or types=="movie" only -> we've inserted "movie" cards
    # 만약 types=="content,movie", etc
    # -> we call "in_" for the original types
    all_types = [t.strip() for t in (types or "").split(",") if t.strip()]
    if all_types:
        q = q.filter(models.RecCard.type.in_(all_types))

    # 최신순 20개
    candidates = q.order_by(models.RecCard.created_at.desc()).limit(20).all()
    if not candidates:
        return []

    # 중복 title 제거
    result = []
    seen_titles = set()
    count = 0
    for c in candidates:
        if c.title not in seen_titles:
            # feedback_logs 찾아본다
            fb = db.query(models.FeedbackLog).filter_by(
                user_id = current_user.id,
                category="recommend",
                reference_id=f"card_id={c.id}"   # or just c.id
            ).first()

            feedback_info = None
            if fb:
                feedback_info = {
                    "feedback_id": fb.id,
                    "feedback_score": fb.feedback_score,
                    "feedback_label": fb.feedback_label,
                    "details": fb.details
                }

            result.append({
                "card_id": c.id,
                "type": c.type,
                "title": c.title,
                "subtitle": c.subtitle,
                "link": c.url,
                "reason": c.reason,
                "feedback": feedback_info
            })
            seen_titles.add(c.title)
            count += 1
            if count >= limit:
                break

    return result


@router.post("/feedback")
def post_feedback(
    card_id: str,
    action: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user_token)
):
    """
    POST /recommend/feedback
    - { card_id, action }을 받아 rec_impressions 테이블에 기록
    - action: "clicked"/"accepted"/"dismissed" 등
    """
    # 카드 존재하는지 체크 (생략 가능)
    card = db.query(models.RecCard).filter_by(id=card_id).first()
    if not card:
        raise HTTPException(404, detail="Card not found")

    imp = models.RecImpression(
        user_id=current_user.id,
        card_id=card_id,
        action=action
    )
    db.add(imp)
    db.commit()
    return {"message": f"Feedback logged: {card_id} -> {action}"}


@router.get("/models")
def get_models():
    """
    GET /recommend/models
    - 현재 사용 중인 추천 모델들(또는 버전 정보) 간단히 반환
    """
    # 실제로는 DB 또는 config 에서 읽어올 수 있음
    return {
        "candidate_model": "basic_sql_filter_v1",
        "rerank_model": "openai_chat_gpt_3.5_turbo",
        "version": "2025-04-01"
    }
