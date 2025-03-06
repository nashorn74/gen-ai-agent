# backend/routers/search.py

import os
import requests
import openai
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import SessionLocal
from .auth import get_current_user_token  # JWT 인증 함수
import models

router = APIRouter(prefix="/search", tags=["search"])

openai.api_key = os.getenv("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY_HERE")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "YOUR_GOOGLE_API_KEY_HERE")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID", "YOUR_GOOGLE_CSE_ID_HERE")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class SearchRequest(BaseModel):
    query: str
    conversation_id: int | None = None   # 새로 추가

@router.post("/")
def search_and_summarize(
    req: SearchRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user_token)
):
    """
    1) Google Custom Search로 검색
    2) 검색 결과(타이틀, 요약 등)를 OpenAI API에 넘겨 "정리"된 응답 생성
    3) conversation_id가 있으면 해당 대화, 없으면 새 대화 생성
    4) user(검색 질의), assistant(정리 결과) 메시지 기록
    5) 최종 결과 반환
    """

    # 1) [DB] conversation_id 핸들링
    conversation_obj = None
    if req.conversation_id:
        # 기존 대화 로드
        conversation_obj = db.query(models.Conversation).filter_by(
            id=req.conversation_id,
            user_id=current_user.id
        ).first()
        if not conversation_obj:
            raise HTTPException(status_code=404, detail="Conversation not found or not yours")

    else:
        # 새 대화 생성
        conversation_obj = models.Conversation(
            user_id=current_user.id,
            title="(Search) " + req.query[:20]  # 간단 제목
        )
        db.add(conversation_obj)
        db.commit()
        db.refresh(conversation_obj)

    # 2) Google Search
    try:
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": GOOGLE_API_KEY,
            "cx": GOOGLE_CSE_ID,
            "q": req.query,
            "lr": "lang_ko",
            "num": 3
        }
        resp = requests.get(url, params=params)
        if resp.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Google Search Error: {resp.text}")
        data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    items = data.get("items", [])
    if not items:
        # 검색 결과 없음 -> DB에 user 메시지만 남기고 짧은 응답
        user_msg = models.Message(
            conversation_id=conversation_obj.id,
            role="user",
            content=f"[검색요청] {req.query}"
        )
        db.add(user_msg)
        db.commit()
        return {
            "conversation_id": conversation_obj.id,
            "result": "No search results found.",
            "detail": []
        }

    # 3) OpenAI 정리
    content_for_gpt = "다음은 사용자 검색 결과입니다.\n"
    for i, item in enumerate(items):
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        link = item.get("link", "")
        content_for_gpt += f"\n[{i+1}] 제목: {title}\n요약: {snippet}\n링크: {link}\n"

    messages = [
        {"role": "system", "content": "You are a helpful assistant. Please read the search results and provide an organized explanation (in Korean)."},
        {"role": "user", "content": content_for_gpt}
    ]

    try:
        openai_resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=messages
        )
        final_text = openai_resp.choices[0].message["content"]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OpenAI error: {str(e)}")

    # 4) 대화 히스토리에 user/assistant 메시지 저장
    # 4.1 user 메시지 (검색 요청)
    user_msg = models.Message(
        conversation_id=conversation_obj.id,
        role="user",
        content=f"[검색요청] {req.query}"
    )
    db.add(user_msg)

    # 4.2 assistant 메시지 (정리 결과)
    assistant_msg = models.Message(
        conversation_id=conversation_obj.id,
        role="assistant",
        content=final_text
    )
    db.add(assistant_msg)
    db.commit()

    # 5) 반환
    return {
        "conversation_id": conversation_obj.id,
        "query": req.query,
        "search_results": items,
        "final_answer": final_text
    }
