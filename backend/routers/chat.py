# backend/routers/chat.py

import os
import openai
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from database import SessionLocal
import models
from .auth import get_current_user_token  # JWT 인증 함수

openai.api_key = os.getenv("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY_HERE")

router = APIRouter(prefix="/chat", tags=["chat"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class ChatRequest(BaseModel):
    conversation_id: int | None = None
    question: str

@router.post("/")
def chat(
    req: ChatRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user_token)
):
    """
    - 반드시 JWT 필요 (현재 user가 누구인지)
    - conversation_id 있으면 해당 대화 불러서 맥락 추가
    - 없으면 새 conversation 생성
    - GPT 호출 후 Message 테이블에 user/assistant 메시지 기록
    """

    # 1) 기존 대화 로드(맥락)
    messages_context = [
        {"role": "system", "content": "You are a helpful assistant."}
    ]
    conversation_obj = None

    if req.conversation_id:
        conversation_obj = db.query(models.Conversation).filter_by(
            id=req.conversation_id,
            user_id=current_user.id
        ).first()
        if not conversation_obj:
            raise HTTPException(status_code=404, detail="Conversation not found or not yours")

        for msg in conversation_obj.messages:
            messages_context.append({"role": msg.role, "content": msg.content})

    # 2) user 메시지 추가
    messages_context.append({"role": "user", "content": req.question})

    # 3) GPT 호출
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=messages_context
        )
        answer = resp.choices[0].message["content"]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # 4) DB에 저장
    if conversation_obj is None:
        # 새 conversation 생성
        conversation_obj = models.Conversation(
            user_id=current_user.id,
            title="Untitled Chat"
        )
        db.add(conversation_obj)
        db.commit()
        db.refresh(conversation_obj)

    # user 메시지
    user_msg = models.Message(
        conversation_id=conversation_obj.id,
        role="user",
        content=req.question
    )
    # assistant 메시지
    assistant_msg = models.Message(
        conversation_id=conversation_obj.id,
        role="assistant",
        content=answer
    )
    db.add(user_msg)
    db.add(assistant_msg)
    db.commit()

    return {
        "answer": answer,
        "conversation_id": conversation_obj.id
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
