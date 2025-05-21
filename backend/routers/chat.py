# backend/routers/chat.py

import os, json
import datetime as dt
from zoneinfo import ZoneInfo 
from openai import OpenAI
import httpx
from typing import Literal
from pydantic import BaseModel, constr
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from database import SessionLocal
import models
from models import Message, MessageRecommendationMap, RecCard
from .auth import get_current_user_token  # JWT 인증 함수
from .gcal  import build_gcal_service                  # Google service 헬퍼
from utils.personalization import recent_feedback_summaries, make_persona_prompt
from fastapi.responses import Response
import base64

HISTORY_CUTOFF = 12

# 1) 로컬 타임존 결정
try:
    local_tz: ZoneInfo | dt.tzinfo = dt.datetime.now().astimezone().tzinfo  # ZoneInfo or timezone
except Exception:
    local_tz = dt.timezone.utc   # 극단적인 fallback

# 2) 사람이 읽을 이름 얻기 (ZoneInfo.key 가 있으면 그걸, 없으면 tzname)
def tz_label(tz: dt.tzinfo) -> str:
    return getattr(tz, "key", None) or tz.tzname(None) or "UTC"

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    http_client=httpx.Client(),          # proxies 파라미터 없음
)

router = APIRouter(prefix="/chat", tags=["chat"])

# ────────────────────────────── Pydantic ───────────────────────────────
class ChatRequest(BaseModel):
    conversation_id: int | None = None
    question:        str
    timezone:        str | None = None    # ex. "Europe/Berlin"

class ToolResponse(BaseModel):
    """GPT function‑call 이 내려올 경우 파라미터 스키마"""
    action : Literal["create_event","delete_event"]
    title  : str | None = None
    start  : str | None = None     # ISO datetime
    end    : str | None = None
    event_id: str | None = None

class TitleUpdate(BaseModel):
    title: constr(strip_whitespace=True, min_length=1, max_length=60)

# ────────────────────────────── helpers ────────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def append_and_commit(db, convo, role, content):
    msg = Message(
        conversation_id=convo.id,
        role=role,
        content=content
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg

@router.post("/", status_code=201)
def chat(
    req: ChatRequest,
    db : Session       = Depends(get_db),
    me : models.User   = Depends(get_current_user_token)
):
    """
    하나의 엔드포인트에서
    ① 일반질문   ② 일정 생성/삭제 명령(자연어) 모두 처리
    """

    # ── 0) 대화 객체 준비 ────────────────────────────
    if req.conversation_id:
        convo = db.query(models.Conversation).filter_by(
            id=req.conversation_id, user_id=me.id
        ).first()
        if not convo:
            raise HTTPException(404,"Conversation not found")
    else:
        convo = models.Conversation(user_id=me.id, title="Untitled chat")
        db.add(convo); db.commit(); db.refresh(convo)

    # ── 1) 직전 메시지들 → GPT 컨텍스트 ───────────────
    client_tz = ZoneInfo(req.timezone) if req.timezone else local_tz
    now_local = dt.datetime.now(client_tz)
    now_client = now_local.isoformat()      # 예: '2025-05-04T10:23:45.123456+09:00'

    # 오늘/내일 날짜(‘YYYY-MM-DD’ 형태)
    today_str = now_local.date().isoformat()  
    tomorrow_str = (now_local.date() + dt.timedelta(days=1)).isoformat()
    
    # 2) 시스템 메시지
    system_content = (
        "You are an AI assistant that can also manage the user's Google Calendar.\n"
        "If the user asks to add, update or delete an event, respond with a function‑call.\n"
        f"⏱️ **Current client time ({tz_label(client_tz)}):** {now_client}\n"
        "Always interpret relative Korean expressions such as 오늘/내일/모레/오후 3시에 "
        f"the client‑side timezone (**{tz_label(client_tz)}**) and make sure the "
        "event is in the future.\n"
        "If the user wants some recommendation (e.g. 어떤 콘텐츠 볼까요?), call `fetch_recommendations`.\n"
        "Otherwise, answer normally.\n\n"

        # ------ 여기서 날짜 강조 ------
        f"IMPORTANT:\n"
        f"오늘(‘today’)은 {today_str} 입니다. "
        f"‘내일’(tomorrow)은 {tomorrow_str} 이므로 일정 계산 시 이 사실을 준수하세요.\n"
    )

    # ▒ Personalization Block ▒
    profile = db.query(models.UserProfile).filter_by(user_id=me.id).first()
    persona = {
        "locale": profile.locale if profile else "ko",
        "genres": {g.genre: g.score for g in me.pref_genres},
        "tags":   [{"type": t.tag_type, "tag": t.tag, "weight": t.weight}
                   for t in me.pref_tags],
        "recent_feedback": recent_feedback_summaries(db, me, limit=50)
    }
    persona_prompt = make_persona_prompt(persona)
    messages_ctx = [
        {"role": "system", "content": persona_prompt},
        {"role": "system", "content": system_content}
    ]
    # 이전 대화(Conversation.messages) 쌓기
    history = convo.messages[-HISTORY_CUTOFF:]
    for m in history:
        messages_ctx.append({"role": m.role, "content": m.content})

    # 현재 user 질문 추가
    messages_ctx.append({"role":"user","content":req.question})
    append_and_commit(db, convo, "user", req.question)

    # ── 2) GPT 호출 (function‑calling) ────────────────
    functions = [
        {
            "name":"create_event",
            "description":"Create a new calendar event",
            "parameters":{
              "type":"object",
              "properties":{
                "title" :{"type":"string"},
                "start" :{"type":"string","description":"ISO datetime"},
                "end"   :{"type":"string","description":"ISO datetime"},
              },
              "required":["title","start","end"]
            }
        },
        {
            "name":"delete_event",
            "description":"Delete an existing event",
            "parameters":{
              "type":"object",
              "properties":{
                "event_id":{"type":"string"}
              },
              "required":["event_id"]
            }
        },
        {
            "name": "generate_image",
            "description": "When the user explicitly asks to draw/create/illustrate something, call this.",
            "parameters": {
                "type": "object",
                "properties": {
                "prompt": {"type": "string", "description": "Korean or English prompt for DALL-E 3"}
                },
                "required": ["prompt"]
            }
        },
        {
            "name":"fetch_recommendations",
            "description":"사용자에게 구체적 영화/콘텐츠 목록을 '추천'할 때 호출하세요. "
                 "특히 질문이 '추천'·'볼만한'·'최고의 영화'·'best movie' 등을 포함하면 호출합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "types": {
                        "type": "string",
                        "description": "콤마로 구분된 추천 타입. 예: 'content,learn'"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "가져올 카드 최대 개수"
                    }
                },
                "required": ["types"]
            }
        }
    ]

    gpt = client.chat.completions.create(
        model       = "gpt-3.5-turbo-1106",
        messages    = messages_ctx,
        functions   = functions,
        temperature = 0.7
    )

    choice  = gpt.choices[0]
    finish   = choice.finish_reason
    msg     = choice.message
    content = msg.content

    # ── 3‑A) 일반 답변이면 그대로 반환 ────────────────
    if finish != "function_call":
        append_and_commit(db, convo, "assistant", content)

        # ★ 추가: 만약 title이 "Untitled chat" 이면 요약해서 제목으로 만들기
        if convo.title == "Untitled chat":
            summarize_conversation_title(db, convo)

        return {
            "answer"         : content,
            "conversation_id": convo.id,
            "cards"          : []  # 일반 답변 시엔 카드 없음
        }

    # ── 3‑B) function‑call 인 경우 ──────────────────
    call   = msg.function_call
    name   = call.name                    # "create_event" | "delete_event"
    args   = json.loads(call.arguments or "{}")   # str → dict

    # 구글 캘린더 연결 체크
    if name == "create_event" or name == "delete_event":
        token_row = db.query(models.GToken).filter_by(user_id=me.id).first()
        if not token_row:
            answer = "❗ Google 캘린더가 연결돼 있지 않아 일정을 처리할 수 없습니다."
            append_and_commit(db, convo, "assistant", answer)

            # ★ 추가: 제목 요약
            if convo.title == "Untitled chat":
                summarize_conversation_title(db, convo)

            return {"answer": answer, "conversation_id": convo.id, "cards": []}
        service = build_gcal_service(db, me.id)
    
    recs = []

    try:
        if name == "create_event":
            # 필수 파라미터 검증
            for k in ("title", "start", "end"):
                if k not in args:
                    raise ValueError(f"missing {k}")

            start_local = dt.datetime.fromisoformat(args["start"]).replace(tzinfo=client_tz)
            end_local   = dt.datetime.fromisoformat(args["end"]).replace(tzinfo=client_tz)

            ev = service.events().insert(
                calendarId="primary",
                body={
                    "summary": args["title"],
                    "start": {
                        "dateTime": start_local.isoformat(timespec="seconds"),
                        "timeZone": req.timezone or tz_label(client_tz)
                    },
                    "end": {
                        "dateTime": end_local.isoformat(timespec="seconds"),
                        "timeZone": req.timezone or tz_label(client_tz)
                    },
                },
            ).execute()
            answer = (f"✅ ‘{args['title']}’ 일정을 "
                      f"{start_local.strftime('%Y‑%m‑%d %H:%M')}에 만들었어요!")

        elif name == "delete_event":
            if "event_id" not in args:
                raise ValueError("missing event_id")

            service.events().delete(
                calendarId="primary", eventId=args["event_id"]
            ).execute()
            answer = "🗑️ 일정을 삭제했어요."

        elif name == "generate_image":
            from utils.image import fetch_and_resize

            full_prompt = args["prompt"]
            # 비용 ↓: 512×512 (DALL-E 3 가능) 1장
            img_resp = client.images.generate(
                model="dall-e-3",
                prompt=full_prompt,
                n=1,
                size="1024x1024"
            )
            img_url = img_resp.data[0].url

            orig_b64, thumb_b64 = fetch_and_resize(img_url)

            # (1) Message row
            assistant_msg = append_and_commit(
                db, convo, "assistant",
                f"📷 요청하신 이미지를 생성했습니다.\n\nprompt: {full_prompt}"
            )

            # (2) MessageImage row
            db.add(models.MessageImage(
                message_id = assistant_msg.id,
                prompt     = full_prompt,
                original_b64 = orig_b64,
                thumb_b64    = thumb_b64
            ))
            db.commit()

            # ★ 제목 없는 대화라면 요약
            if convo.title == "Untitled chat":
                summarize_conversation_title(db, convo)

            return {
                "answer": "(image_created)",
                "conversation_id": convo.id,
                "cards": [],
            }

        elif name == "fetch_recommendations":
            # 1) 인수 파싱
            from routers.recommend import get_recommendations
            types = args.get("types", "")
            limit = args.get("limit", 5)

            # 백엔드 내부 함수 직접 호출
            try:
                recs = get_recommendations(
                    types = types,
                    limit = limit,
                    db    = db,
                    current_user = me,
                    tz    = client_tz,
                    user_query = req.question,
                )
                # recs 는 [{"card_id","type","title","subtitle","link","reason",...}, ...]

                # 예시: 채팅 답변용 텍스트
                if not recs:
                    answer = "추천할 카드가 없네요!"
                else:
                    lines = []
                    for r in recs:
                        lines.append(f"• {r['title']} ({r['type']}) : {r['link']}")
                    answer = "아래와 같은 추천 결과를 찾았습니다:\n\n" + "\n".join(lines)

            except Exception as e:
                answer = f"추천 조회 중 오류: {str(e)}"
                recs = []
            
            # 메시지 먼저 생성
            assistant_msg = append_and_commit(db, convo, "assistant", answer)

            # recs = [{ "card_id":"c_12903","title":"...","type":"..."}, ...]
            for i, r in enumerate(recs):
                # rec_cards 테이블에서 해당 card_id 가 존재하는지 확인 (없으면 생성할 수도 있음)
                card = db.query(RecCard).filter_by(id=r["card_id"]).first()

                # 만약 card 자체가 DB에 없으면, 임시로 생성 예시 (원래는 미리 DB에 있음이 일반적)
                if not card:
                    card = RecCard(
                        id       = r["card_id"],
                        type     = r.get("type","content"),
                        title    = r.get("title","Untitled"),
                        subtitle = r.get("subtitle",""),
                        url      = r.get("link",""),
                        reason   = r.get("reason",""),
                        tags     = r.get("tags", [])
                    )
                    db.add(card)
                    db.commit()

                mapping = MessageRecommendationMap(
                    message_id = assistant_msg.id,
                    rec_card_id = card.id,
                    sort_order  = i
                )
                db.add(mapping)

            db.commit()

            # ★ 타이틀 요약
            if convo.title == "Untitled chat":
                summarize_conversation_title(db, convo)

            return {
                "answer": answer,
                "conversation_id": convo.id,
                "cards": recs
            }

        else:                                  # 정의되지 않은 함수명
            answer = "⚠️ 알 수 없는 function call"

    except Exception as e:
        answer = f"function call 처리 중 오류: {e}"

    # DB에 assistant 메시지로 저장
    append_and_commit(db, convo, "assistant", answer)

    # ★ 타이틀 요약
    if convo.title == "Untitled chat":
        summarize_conversation_title(db, convo)

    return {
        "answer"         : answer,
        "conversation_id": convo.id,
        "cards"          : recs
    }

@router.get("/conversations")
def get_conversations(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user_token)
):
    """
    - 현재 로그인 사용자(user_id) 소유의 conversation 목록 반환
    """
    convo_list = db.query(models.Conversation)\
                   .filter_by(user_id=current_user.id)\
                   .all()
    results = []
    for c in convo_list:
        results.append({
            "conversation_id": c.id,
            "title": c.title,
            "created_at": c.created_at
        })
    return results

@router.get("/conversations/{conversation_id}")
def get_conversation_detail(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user_token)
):
    """
    - 특정 대화 상세(메시지 목록)를 불러온다
    """
    convo = db.query(models.Conversation).filter_by(
        id=conversation_id,
        user_id=current_user.id
    ).first()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found or not yours")

    messages = []
    for m in convo.messages:
        # ↘ 추천 카드가 있으면, 관계를 통해 가져옴
        card_list = []
        for mr in m.recommendations:
            c = mr.rec_card
            # DB의 RecCard 정보를 JSON 형태로 변환
            card_fb = db.query(models.FeedbackLog).filter_by(
                user_id = current_user.id,
                category="recommend",
                reference_id=f"card_id={c.id}"   # or just c.id
            ).first()

            card_feedback_info = None
            if card_fb:
                card_feedback_info = {
                    "feedback_id": card_fb.id,
                    "feedback_score": card_fb.feedback_score,
                    "feedback_label": card_fb.feedback_label,
                    "details": card_fb.details
                }

            card_list.append({
                "card_id"  : c.id,
                "type"     : c.type,
                "title"    : c.title,
                "subtitle" : c.subtitle,
                "link"     : c.url,
                "reason"   : c.reason,
                "feedback" : card_feedback_info,
                "tags"     : c.tags,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "sort_order": mr.sort_order  # 혹은 필요 없다면 생략
            })

        # ----- (2) 메시지에 대한 피드백 로딩
        # category="chat", reference_id=f"message_{m.id}", user_id=current_user.id
        fb = db.query(models.FeedbackLog).filter_by(
            user_id=current_user.id,
            category="chat",
            reference_id=f"message_{m.id}"
        ).first()
        if fb:
            feedback_info = {
                "feedback_id": fb.id,
                "feedback_score": fb.feedback_score,
                "feedback_label": fb.feedback_label,
                "details": fb.details
            }
        else:
            feedback_info = None

        thumbs = [ {"image_id": im.id, "thumb": im.thumb_b64} for im in m.images ]

        messages.append({
            "message_id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at,
            "cards": card_list,
            "images": thumbs,
            "feedback": feedback_info   # ← ★ 메시지별 피드백 정보
        })

    return {
        "conversation_id": convo.id,
        "title": convo.title,
        "messages": messages
    }

# ★ 추가: 요약해서 convo.title 로 설정하는 함수
def summarize_conversation_title(db: Session, convo: models.Conversation):
    """
    대화 내용(Message)을 간략히 요약하여 conversation.title 로 설정
    """
    # 1) 대화 내용을 하나의 문자열로 합침
    text_parts = []
    print(convo.messages)
    for m in convo.messages:
        # role: system, user, assistant
        # 일단 user/assistant 메시지만 포함
        if m.role in ("user", "assistant"):
            text_parts.append(f"{m.role}: {m.content}")
    joined_text = "\n".join(text_parts)
    print(text_parts)
    if not joined_text.strip():
        return  # 대화가 비어있으면 그냥 둠

    # 2) OpenAI 요청: "이 대화를 한 줄짜리 짧은 제목으로 요약"
    system_prompt = (
        "You are a helpful assistant. The user and assistant messages are shown. "
        "Please create a concise conversation title in Korean, under 30 characters. "
        "If there's no meaningful content, just return something like '메시지 없음'."
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": joined_text}
    ]
    try:
        resp = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=30,
            temperature=0.6
        )
        new_title = resp.choices[0].message.content.strip()
    except:
        new_title = "(Untitled)"

    # 제목 길이가 너무 길면 잘라냄 (30자)
    if len(new_title) > 30:
        new_title = new_title[:30].rstrip()

    # DB 반영
    convo.title = new_title
    db.commit()


@router.patch("/conversations/{conversation_id}", status_code=200)
def rename_conversation(
    conversation_id: int,
    payload: TitleUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user_token),
):
    """
    PATCH /chat/conversations/{id}
    바디: { "title": "새 제목" }
    """
    convo = (
        db.query(models.Conversation)
        .filter_by(id=conversation_id, user_id=current_user.id)
        .first()
    )
    if not convo:
        raise HTTPException(404, "Conversation not found or not yours")

    convo.title = payload.title
    db.commit()
    return {"conversation_id": convo.id, "title": convo.title}


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user_token),
):
    """
    DELETE /chat/conversations/{id}
    대화 · 메시지 · 추천맵 전부 삭제 (SQLAlchemy cascade)
    """
    convo = (
        db.query(models.Conversation)
        .filter_by(id=conversation_id, user_id=current_user.id)
        .first()
    )
    if not convo:
        raise HTTPException(404, "Conversation not found or not yours")

    db.delete(convo)
    db.commit()
    # 204 No Content


@router.get("/images/{image_id}", status_code=200)
def get_original_image(
    image_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user_token),
):
    """
    원본 WebP 바이너리를 그대로 돌려준다.
    (Auth 적용 → 내 대화의 이미지만 볼 수 있게)
    """
    img_row = (
        db.query(models.MessageImage)
        .join(models.Message, models.Message.id == models.MessageImage.message_id)
        .join(models.Conversation, models.Conversation.id == models.Message.conversation_id)
        .filter(
            models.MessageImage.id == image_id,
            models.Conversation.user_id == current_user.id,
        )
        .first()
    )
    if not img_row:
        raise HTTPException(404, "Image not found or not yours")

    return Response(
        content=base64.b64decode(img_row.original_b64),
        media_type="image/webp",          # ↔ PIL 의 .save(format="WEBP")
        headers={"Cache-Control": "public,max-age=31536000"},
    )