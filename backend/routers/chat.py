# backend/routers/chat.py
import os
import openai
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/chat", tags=["chat"])

# 환경 변수 등에 OpenAI API 키를 저장했다고 가정 (예: .env)
# 또는 직접 하드코딩 가능 (보안상 비추천)
openai.api_key = os.getenv("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY_HERE")

class ChatRequest(BaseModel):
    question: str

@router.post("/")
def chat(req: ChatRequest):
    """
    간단한 챗봇 라우터.
    JSON Body로 {"question": "..."} 형태를 받음
    OpenAI GPT-3.5/4 등을 호출하고, 응답 반환.
    """
    try:
        user_question = req.question
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",  # 또는 "gpt-4"
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": user_question}
            ]
        )
        # ChatCompletion은 여러 개의 answer(choices)를 반환할 수 있음
        answer = response.choices[0].message["content"]
        return {"answer": answer}

    except Exception as e:
        # API 호출 실패, 키 불량, 모델 에러 등
        raise HTTPException(status_code=500, detail=str(e))
