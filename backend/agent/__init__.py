# backend/agent/__init__.py  ▶ 수정본 전부

from __future__ import annotations
import os, json, datetime as dt
from typing import List, Dict, Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session
from openai import OpenAI, AsyncOpenAI
import httpx

from langchain_openai import ChatOpenAI
from langchain.memory import ConversationBufferMemory
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.schema import SystemMessage
from langchain_core.tools import BaseTool
from langchain_core.tools import tool  # ⬅️ 데코레이터
from pydantic import BaseModel, Field

import models
from routers.gcal import build_gcal_service
from routers.search import google_search_cse
from utils.image import fetch_and_resize

# ─────────────────────────── OpenAI 클라이언트
_sync_root = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    http_client=httpx.Client(
        timeout=30.0,
        limits=httpx.Limits(max_keepalive_connections=20),
    ),
)
_async_root = AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    http_client=httpx.AsyncClient(
        timeout=30.0,
        limits=httpx.Limits(max_keepalive_connections=20),
    ),
)


class _SyncChat:
    def create(self, **kwargs):
        return _sync_root.chat.completions.create(**kwargs)


class _AsyncChat:
    async def create(self, **kwargs):
        return await _async_root.chat.completions.create(**kwargs)


_llm = ChatOpenAI(
    model="gpt-3.5-turbo",
    temperature=0.2,
    client=_SyncChat(),
    async_client=_AsyncChat(),
)

# ── pydantic 스키마 ───────────────────────────
class CreateEventArgs(BaseModel):
    title: str  = Field(..., description="일정 제목")
    start: str  = Field(..., description="ISO-8601 시작")
    end:   str  = Field(..., description="ISO-8601 종료")

class DeleteEventArgs(BaseModel):
    event_id: str

class WebSearchArgs(BaseModel):
    query: str
    k: int = 5

class GenImgArgs(BaseModel):
    prompt: str = Field(..., description="DALL-E 프롬프트")

class RecArgs(BaseModel):
    types: str
    limit: int = 5
# ─────────────────────────────────────────────


# ─────────────────────────── tool 세트
def _make_toolset(db: Session, user: models.User, tz: ZoneInfo):

    @tool(args_schema=CreateEventArgs, return_direct=True)
    def create_event(title: str, start: str, end: str) -> str:
        """Google Calendar 일정 생성. 사용자가 일정, 미팅, 약속 등을 잡아달라고 할 때 항상 사용하세요.
        
        title: 일정 제목 (예: "팀 회의", "점심 약속")
        start: ISO-8601 시작 시간 (예: "2025-05-26T13:00:00+02:00")
        end: ISO-8601 종료 시간 (예: "2025-05-26T14:00:00+02:00")
        
        일정 생성은 항상 미래 시간에만 가능합니다.
        """
        print("---------------------------------------")
        print("create_event 호출됨!")
        print(f"매개변수: title={title}, start={start}, end={end}")
        print("---------------------------------------")
        try:
            # 1) ISO → datetime
            try:
                dt_start = dt.datetime.fromisoformat(start)
                dt_end = dt.datetime.fromisoformat(end)
            except ValueError as e:
                print(f"ISO 파싱 실패: {start}, {end}, 오류: {e}")
                return f"❗ 날짜 형식이 올바르지 않습니다: {e}"

            # 2) 타임존 처리
            if dt_start.tzinfo is None:
                dt_start = dt_start.replace(tzinfo=tz)
            if dt_end.tzinfo is None:
                dt_end = dt_end.replace(tzinfo=tz)
            
            # 3) 현재 시간
            now = dt.datetime.now(tz)
            print(f"시간 비교: 시작={dt_start}, 현재={now}")
            
            # 4) 미래 일정 확인 (10분 이내는 허용)
            if dt_start < now - dt.timedelta(minutes=10):
                return f"❗ 과거 시간({dt_start.strftime('%Y-%m-%d %H:%M')})에는 일정을 추가할 수 없습니다. 현재 시간은 {now.strftime('%Y-%m-%d %H:%M')}입니다."
            
            # 5) Google Calendar API 호출
            svc = build_gcal_service(db, user.id)
            print(f"일정 생성 시도: {title}, {dt_start} ~ {dt_end}")
            ev = svc.events().insert(
                calendarId="primary",
                body={
                    "summary": title,
                    "start": {"dateTime": dt_start.isoformat(), "timeZone": str(tz)},
                    "end": {"dateTime": dt_end.isoformat(), "timeZone": str(tz)},
                },
            ).execute()

            result = f"✅ 일정 생성 완료 → {dt_start.strftime('%Y-%m-%d %H:%M')} ~ {dt_end.strftime('%H:%M')} {ev.get('htmlLink')}"
            print(result)
            return result
        except Exception as e:
            print(f"일정 생성 오류: {e}")
            return f"❗ 일정 생성 중 오류가 발생했습니다: {str(e)}"

    @tool(args_schema=DeleteEventArgs, return_direct=True)
    def delete_event(event_id: str) -> str:
        """event_id 로 Google Calendar 이벤트를 삭제한다."""
        svc = build_gcal_service(db, user.id)
        svc.events().delete(calendarId="primary", eventId=event_id).execute()
        return "🗑️ 일정이 삭제되었습니다."

    @tool(args_schema=WebSearchArgs)
    def web_search(query: str, k: int = 5) -> str:
        """Google CSE 로 웹을 검색하고 상위 k개 링크를 돌려준다."""
        items = google_search_cse(query=query, num=k, date_restrict="m6", sort="date")
        return "\n".join(f"{it['title']} – {it['link']}" for it in items) or "No results"

    @tool(args_schema=GenImgArgs, return_direct=True)
    def generate_image(prompt: str) -> str:
        """DALL-E 3 로 이미지를 생성해 base64 JSON 을 돌려준다."""
        try:
            resp = _sync_root.images.generate(
                model="dall-e-3", prompt=prompt, n=1, size="1024x1024"
            )
            url = resp.data[0].url
            orig, thumb = fetch_and_resize(url)
            payload = {
                "prompt": prompt,
                "original_b64": orig,
                "thumb_b64": thumb,
            }
            return json.dumps(payload, ensure_ascii=False)   # ★ 반드시 str!
        except Exception as e:
            return json.dumps({"error": f"이미지 생성 실패: {e}"}, ensure_ascii=False)

    @tool(args_schema=RecArgs, return_direct=True)
    def fetch_recommendations(types: str, limit: int = 5) -> str:
        """
        ONLY USE THIS TOOL when the user EXPLICITLY asks for content recommendations or suggestions.
        
        APPROPRIATE USES:
        - User asks "뭐 볼까?" (What should I watch?)
        - User says "영화 추천해줘" (Recommend me a movie)
        - User asks for options or suggestions for content to consume
        
        DO NOT USE FOR:
        - Technical questions like "React란 무엇인가?"
        - Factual information queries like "TypeScript의 장점은?"
        - General knowledge or explanations
        
        This tool returns personalized content recommendation cards as JSON.
        """
        from routers.recommend import get_recommendations
        recs = get_recommendations(
            types=types, limit=limit, db=db, current_user=user, tz=tz, user_query=""
        )
        return json.dumps({"cards": recs}, ensure_ascii=False)

    return [
        create_event,
        delete_event,
        web_search,
        generate_image,
        fetch_recommendations,
    ]

def tz_label(tz: dt.tzinfo) -> str:
    return getattr(tz, "key", None) or tz.tzname(None) or "UTC"

def _make_time_system_prompt(client_tz: ZoneInfo) -> str:
    now_local     = dt.datetime.now(client_tz)
    now_client    = now_local.isoformat(timespec="seconds")
    today_str     = now_local.date().isoformat()
    tomorrow_str  = (now_local.date() + dt.timedelta(days=1)).isoformat()

    # 예제 시간 (미리 계산)
    afternoon_example = (now_local.replace(hour=13, minute=0, second=0) + 
                     dt.timedelta(days=(0 if now_local.hour < 13 else 1))).isoformat()

    system_prompt = (
        "You are an AI assistant that can also manage the user's Google Calendar.\n"
        f"⏱️ **Current client time ({tz_label(client_tz)}):** {now_client}\n\n"
        
        "## CALENDAR INSTRUCTIONS\n"
        f"- Today's date is {today_str} in timezone {tz_label(client_tz)}\n"
        f"- Tomorrow's date is {tomorrow_str}\n"
        f"- Current hour is {now_local.hour}\n"
        "- When user mentions '오늘' (today), use today's date\n"
        "- When user mentions '내일' (tomorrow), use tomorrow's date\n"
        "- '오전' means AM, '오후' means PM\n"
        f"- Example: '오늘 오후 1시' should be interpreted as {afternoon_example}\n"
        "- ALWAYS create events in the FUTURE (after current time)\n"
        "- ALWAYS use the create_event tool for calendar requests\n\n"
        
        "## TOOL USAGE GUIDELINES\n"
        "- Use calendar tools (create_event, delete_event) when the user wants to manage their schedule\n"
        "- Use web_search when the user asks for current information or news\n"
        "- Use generate_image when the user asks to create or visualize an image\n\n"
        
        "## ABOUT THE RECOMMENDATION TOOL\n"
        "The fetch_recommendations tool should ONLY be used when:\n"
        "1. The user is EXPLICITLY asking for content suggestions, recommendations, or options\n"
        "2. The user is asking what to watch, read, or consume\n"
        "3. The user uses phrases like '추천해줘', '뭐 볼까?', '어떤 게 좋을까?'\n\n"
        
        "NEVER use fetch_recommendations for:\n"
        "1. Technical explanations (e.g., 'React란 무엇인가?', 'TypeScript의 장점')\n"
        "2. Factual questions (e.g., '파이썬 함수 정의 방법', '한국의 수도는?')\n"
        "3. General conversation or advice\n\n"
        
        "If no tool is appropriate, just respond with a direct text answer. Most queries should be answered with text, not tools.\n"
    )
    print(system_prompt)
    return system_prompt

def format_tool_to_str(tool) -> str:
    """
    LangChain <0.3 계열에 render util 이 없을 때 쓰는 폴리-필.
    LLM 이 쉽게 따라 할 수 있도록 **JSON 예시** 까지 넣어 준다.
    """
    fields = getattr(tool, "args_schema", None)
    fields   = getattr(tool, "args_schema", None)
    sample_args: dict[str, str] = {}
    if fields:
        for name, field in fields.__fields__.items():
            # pydantic v1 → ModelField  /  v2 → FieldInfo
            tp = (
                getattr(field, "annotation", None)   # v2
                or getattr(field, "outer_type_", None)  # v1
                or str
            )
            type_name = getattr(tp, "__name__", str(tp))
            sample_args[name] = f"<{type_name}>"
    return f"{tool.name} – {tool.description or ''}"

def build_prompt(tools: list[BaseTool], tz: ZoneInfo) -> ChatPromptTemplate:
    tool_block  = "\n".join(format_tool_to_str(t) for t in tools)
    system_str  = _make_time_system_prompt(tz)

    # 완전히 하드코딩된 예제 (문자열 템플릿 변수 없음)
    examples = """
    EXAMPLES:
    
    User: "TypeScript란 무엇인가요?"
    Assistant: TypeScript는 Microsoft에서 개발한 JavaScript의 상위집합(superset) 프로그래밍 언어입니다...
    
    User: "오늘 오후 1시에 팀 회의 잡아줘"
    Assistant: {{"name": "create_event", "arguments": {{"title": "팀 회의", "start": "2025-05-26T13:00:00+02:00", "end": "2025-05-26T14:00:00+02:00"}}}}
    
    User: "내일 점심 약속 일정 추가해줘"
    Assistant: {{"name": "create_event", "arguments": {{"title": "점심 약속", "start": "2025-05-27T12:00:00+02:00", "end": "2025-05-27T13:00:00+02:00"}}}}
    
    User: "영화 추천해줘"
    Assistant: {{"name": "fetch_recommendations", "arguments": {{"types": "movie", "limit": 5}}}}
    
    User: "React의 장점이 뭐야?"
    Assistant: React의 주요 장점은 다음과 같습니다: 1) 가상 DOM을 통한 효율적인 렌더링...
    """

    system_message = ("system",
             f"{system_str}\n\n"
             "You have access to the following tools:\n"
             f"{tool_block}\n"
             #f"{examples}\n\n"
             "When handling calendar requests:\n"
             "1. ALWAYS convert relative times to absolute ISO datetime\n"
             "2. ALWAYS check that the time is in the future\n"
             "3. ALWAYS include timezone information\n"
             "4. NEVER respond with natural language for calendar requests - use the tool\n\n"
             "When you need a tool, reply **only** with the JSON shown in the example -- "
             "no markdown, no extra keys, no natural-language."
            )
    print(system_message)

    return ChatPromptTemplate.from_messages(
        [
            system_message,
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
            ("assistant", "{agent_scratchpad}"),
        ]
    )

def _clean_history(messages: list[models.Message]) -> list[tuple[str,str]]:
    """기능-응답(✅/🗑️/❗/JSON) 제거 후 (role,text) 튜플 반환"""
    cleaned = []
    for m in messages[-15:]:
        if m.role == "assistant":
            t = m.content.strip()
            if t.startswith(("✅", "🗑️", "❗", "📷", '{"card_id', '{"prompt')):
                continue
        cleaned.append((m.role, m.content))
    return cleaned

# ─────────────────────────── 에이전트
def build_agent(
    db: Session,
    user: models.User,
    tz: ZoneInfo = ZoneInfo("UTC"),
    history: list[models.Message] | None = None,
) -> AgentExecutor:
    # 1) memory (최근 15개, 이미지/카드/확인메시지 제거)
    memory = ConversationBufferMemory(
        memory_key="chat_history",
        input_key="input",
        return_messages=True,
    )
    for role, text in _clean_history(history or []):
        (memory.chat_memory.add_user_message if role == "user"
         else memory.chat_memory.add_ai_message)(text)

    # 2) tools & prompt
    tools  = _make_toolset(db, user, tz)
    prompt = build_prompt(tools, tz)

    # 3) agent → executor
    agent   = create_openai_tools_agent(_llm, tools, prompt)   # ✅ system_message 안 넘김
    exec_   = AgentExecutor(
        agent   = agent,
        tools   = tools,
        memory  = memory,
        verbose = True,  # 디버깅을 위해 verbose 모드 활성화
        max_iterations      = 4,
        handle_parsing_errors = True,   # LLM 이 JSON 깨뜨려도 한 번 더 시도
        early_stopping_method = "force",  # 더 확실한 제어
    )
    return exec_
