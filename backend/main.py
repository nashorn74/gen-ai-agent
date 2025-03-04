# backend/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import user, chat
from database import engine
import models

# 데이터베이스 테이블 생성(동기 모드라면)
models.Base.metadata.create_all(bind=engine)

app = FastAPI()

# CORS 설정
origins = [
    "http://localhost:5173",      # 프론트엔드 개발 서버
    "http://127.0.0.1:5173",
    # 필요한 도메인이 있다면 계속 추가
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,          # 허용할 오리진 리스트
    allow_credentials=True,
    allow_methods=["*"],            # 허용할 http 메서드
    allow_headers=["*"],            # 허용할 http 헤더
)

# 라우터 등록
app.include_router(user.router)
app.include_router(chat.router)

@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI!"}
