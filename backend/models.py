# backend/models.py

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, ARRAY
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)  # 해시된 비밀번호를 저장

    # 새 테이블과의 연결 (선택)
    conversations = relationship("Conversation", back_populates="owner")


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    # User와의 관계
    owner = relationship("User", back_populates="conversations")
    # Message와의 관계
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"))
    role = Column(String)  # 'system', 'user', 'assistant'
    content = Column(Text)
    created_at = Column(DateTime, server_default=func.now())

    conversation = relationship("Conversation", back_populates="messages")
    recommendations = relationship(
        "MessageRecommendationMap",
        back_populates="message",
        cascade="all, delete-orphan"
    )

class Event(Base):
    __tablename__ = "events"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False)

    title       = Column(String,  nullable=False)
    description = Column(Text,    default="")
    start_utc   = Column(DateTime, nullable=False)
    end_utc     = Column(DateTime, nullable=False)
    timezone    = Column(String,  default="UTC")

    created_at  = Column(DateTime, server_default=func.now())

    owner = relationship("User", back_populates="events")


class GToken(Base):
    """
    Google OAuth 토큰 저장 테이블
    access_token 이 만료되면 refresh_token 으로 자동 갱신
    """
    __tablename__ = "google_tokens"

    user_id       = Column(Integer, ForeignKey("users.id"), primary_key=True)
    access_token  = Column(Text,  nullable=False)
    refresh_token = Column(Text,  nullable=False)
    expires_at    = Column(DateTime, nullable=False)


# ── User 와의 관계 설정 ──────────────────────────
User.events = relationship("Event",
                            back_populates="owner",
                            cascade="all, delete-orphan")


class RecCard(Base):
    __tablename__ = "rec_cards"
    id = Column(String, primary_key=True)   # 예: "c_123"
    type = Column(String)                   # "content", "learn", etc.
    title = Column(String)
    subtitle = Column(String)
    url = Column(String)
    reason = Column(Text, nullable=True)    # LLM이나 규칙 기반으로 생성된 추천 사유
    tags = Column(ARRAY(String), default=[])# 검색 및 필터용 태그
    created_at = Column(DateTime, server_default=func.now())

class RecImpression(Base):
    __tablename__ = "rec_impressions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    card_id = Column(String, ForeignKey("rec_cards.id"), nullable=False)
    action = Column(String)                  # "viewed"/"clicked"/"accepted"/"dismissed" ...
    shown_at = Column(DateTime, server_default=func.now())

    # 예: 필요하다면 관계도 설정
    # card = relationship("RecCard")
    # user = relationship("User")

class MessageRecommendationMap(Base):
    __tablename__ = "message_recommendation_map"
    id = Column(Integer, primary_key=True, index=True)

    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False)
    rec_card_id = Column(String, ForeignKey("rec_cards.id"), nullable=False)
    sort_order = Column(Integer, default=0)

    # 필요 시 관계 설정
    message = relationship("Message", back_populates="recommendations")
    rec_card = relationship("RecCard")