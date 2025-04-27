# backend/routers/chat.py

import os, json
import datetime as dt
from zoneinfo import ZoneInfo 
import openai
from typing import Literal
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from database import SessionLocal
import models
from .auth import get_current_user_token  # JWT 인증 함수
from .gcal  import build_gcal_service                  # Google service 헬퍼

# 1) 로컬 타임존 결정
try:
    local_tz: ZoneInfo | dt.tzinfo = dt.datetime.now().astimezone().tzinfo  # ZoneInfo or timezone
except Exception:
    local_tz = dt.timezone.utc   # 극단적인 fallback

# 2) 사람이 읽을 이름 얻기 (ZoneInfo.key 가 있으면 그걸, 없으면 tzname)
def tz_label(tz: dt.tzinfo) -> str:
    return getattr(tz, "key", None) or tz.tzname(None) or "UTC"

openai.api_key = os.getenv("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY_HERE")

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

# ────────────────────────────── helpers ────────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def append_and_commit(db: Session, convo, role, content):
    msg = models.Message(conversation_id = convo.id,
                         role = role, content = content)
    db.add(msg); db.commit()

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
    now_client = dt.datetime.now(client_tz).isoformat()
    
    messages_ctx = [
        {
            "role": "system",
            "content": (
                "You are an AI assistant that can also manage the user's Google Calendar.\n"
                "If the user asks to add, update or delete an event, respond with a function‑call.\n"
                f"⏱️ **Current client time ({tz_label(client_tz)}):** {now_client}\n"
                "Always interpret relative Korean expressions such as 오늘/내일/모레/오후 3시에 "
                f"the client‑side timezone (**{tz_label(client_tz)}**) and make sure the "
                "event is in the future."
            )
        }
    ]
    print(messages_ctx)
    for m in convo.messages:
        messages_ctx.append({"role":m.role,"content":m.content})

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
        }
    ]

    gpt = openai.ChatCompletion.create(
        model       = "gpt-3.5-turbo-1106",
        messages    = messages_ctx,
        functions   = functions,
        temperature = 0.3
    )

    choice   = gpt.choices[0]
    finish   = choice.finish_reason
    content  = choice.message.get("content")

    # ── 3‑A) 일반 답변이면 그대로 반환 ────────────────
    if finish != "function_call":
        append_and_commit(db, convo, "assistant", content)
        return {
            "answer"         : content,
            "conversation_id": convo.id
        }

    # ── 3‑B) function‑call 인 경우 ──────────────────
    call   = choice.message.function_call
    name   = call.name                    # "create_event" | "delete_event"
    args   = json.loads(call.arguments or "{}")   # str → dict

    # 구글 캘린더 연결 체크
    token_row = db.query(models.GToken).filter_by(user_id=me.id).first()
    if not token_row:
        answer = "❗ Google 캘린더가 연결돼 있지 않아 일정을 처리할 수 없습니다."
        append_and_commit(db, convo, "assistant", answer)
        return {"answer": answer, "conversation_id": convo.id}

    service = build_gcal_service(db, me.id)

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

        else:                                  # 정의되지 않은 함수명
            answer = "⚠️ 알 수 없는 요청입니다."

    except Exception as e:
        answer = f"⚠️ 일정 처리 중 오류: {e}"

    append_and_commit(db, convo, "assistant", answer)
    return {"answer": answer, "conversation_id": convo.id}

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
        messages.append({
            "message_id": m.id,
            "role": m.role,
            "content": m.content,
            "created_at": m.created_at
        })

    return {
        "conversation_id": convo.id,
        "title": convo.title,
        "messages": messages
    }
