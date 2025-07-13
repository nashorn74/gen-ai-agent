# backend/agent/__init__.py  ▶ 수정본 전부

from __future__ import annotations
import os, json, datetime as dt
from typing import List, Dict, Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session
from openai import OpenAI, AsyncOpenAI
import httpx

from langchain_openai import ChatOpenAI
from langchain.memory import ConversationTokenBufferMemory
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.schema import SystemMessage
from langchain_core.tools import BaseTool
from langchain_core.tools import tool  # ⬅️ 데코레이터
from pydantic import BaseModel, Field

from .tools import make_toolset
from .planner import create_planner_prompt, plan_output_parser
from .executor import StepExecutor

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

# 일반 에이전트용 LLM
_llm = ChatOpenAI(
    model="gpt-3.5-turbo",
    temperature=0.2,
    client=_SyncChat(),
    async_client=_AsyncChat(),
)

# ✅ [수정] 플래너 전용 LLM을 여기서 중앙 관리합니다.
_planner_llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.2,
    client=_SyncChat(),      # 올바르게 설정된 클라이언트 재사용
    async_client=_AsyncChat(), # 올바르게 설정된 클라이언트 재사용
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
    # 1) Memory – 토큰 기반 윈도우 (≈ 1 200 tokens)
    memory = ConversationTokenBufferMemory(
        llm=_llm,
        memory_key="chat_history",
        input_key="input",
        max_token_limit=1200,
        return_messages=True,
    )
    for role, text in _clean_history(history or []):
        (memory.chat_memory.add_user_message if role == "user"
         else memory.chat_memory.add_ai_message)(text)

    # 2) tools & prompt
    tools  = make_toolset(db, user, tz, _sync_root, _llm)
    prompt = build_prompt(tools, tz)

    # 3) agent → executor
    agent = create_openai_tools_agent(_llm, tools, prompt)
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

# examples 부분에 추가
#User: "다음 달 주말에 볼 만한 전시회 추천하고 일정 잡아줘"
#Assistant (plan):
#{
# "steps":[
#   {"tool":"web_search","args":{"query":"서울 전시회 2025-08", "k":10}},
#   {"tool":"fetch_recommendations","args":{"types":"content","limit":5}},
#   {"tool":"create_event","args":{
#      "title":"데이비드 호크니 전",
#      "start":"2025-08-16T14:00:00+09:00",
#      "end":"2025-08-16T16:00:00+09:00"}}
# ]
#}

# ───────── LCEL 기반 Plan-and-Execute 1-회 실행 ──────────
def run_lcel_once(
    db: Session,
    user: models.User,
    tz: ZoneInfo,
    history: list[models.Message] | None = None,
    user_input: str | None = None,
) -> dict:
    """
    LLM이 계획을 세우고(Plan), 각 단계를 순차적으로 실행(Execute)합니다.
    """
    # ── 0) 입력 확정 ──────────────────────────────────────
    if user_input is None:
        if not history:
            raise ValueError("run_lcel_once: history or user_input is required.")
        
        last_user_message_content = None
        for message in reversed(history):
            if message.role == 'user':
                last_user_message_content = message.content
                break
        
        if last_user_message_content is None:
            return {"output": "이전 대화에서 사용자님의 메시지를 찾을 수 없습니다."}
        user_input = last_user_message_content

    # ── 1) 플래너 호출 (계획 수립) ─────────────────────────
    # ‼️ [수정] 현재 시간을 기준으로 동적으로 프롬프트를 생성
    now_in_client_tz = dt.datetime.now(tz)
    plan_prompt = create_planner_prompt(current_time_str=now_in_client_tz.isoformat())
    
    plan_chain = plan_prompt | _planner_llm | plan_output_parser

    print("\n" + "=" * 70)
    print(f"🕵️ 1. PLANNER INPUT: '{user_input}'")
    
    prompt_value = plan_prompt.invoke({"input": user_input})
    print("\n" + "-" * 25 + " 💌 FINAL PROMPT TO LLM " + "-" * 25)
    for message in prompt_value.to_messages():
        print(f"[{message.type.upper()}]")
        print(message.content)
        print("---")
    print("-" * 75)

    # 파싱 전 LLM 원본 답변 확인
    raw_plan = (plan_prompt | _planner_llm).invoke({"input": user_input})
    print("\n" + "-" * 25 + " 🤖 RAW LLM OUTPUT " + "-" * 26)
    print(raw_plan.content)
    print("-" * 75)

    try:
        plan = plan_output_parser.parse(raw_plan.content)
        print("\n📝 2. PARSED PLAN:\n", json.dumps(plan, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"\n❌ ERROR: Failed to parse LLM output into JSON. Error: {e}")
        return {"output": "에이전트가 응답을 생성하는 데 실패했습니다. (JSON 파싱 오류)"}

    # ── 2) 단계별 실행 (Executor 사용) ───────────────────
    step_executor = StepExecutor(db, user, tz, _planner_llm, _sync_root)

    step_outputs: dict[str, str] = {}
    logs: list[dict] = []

    if not plan.get("steps"):
        print("\n🤷 NO STEPS TO EXECUTE. Returning default response.")
    else:
        for idx, step in enumerate(plan.get("steps", [])):
            result = step_executor.execute_step(step, step_outputs)
            step_key = f"step_{idx + 1}_output"
            step_outputs[step_key] = result.get("output", "")
            logs.append(result)

    print("=" * 70 + "\n")

    # ── 3) 최종 출력 ────────────────────────────────────
    if logs:
        return {"output": logs[-1].get("output", "실행은 완료되었지만 결과가 없습니다.")}
    
    return {"output": "알겠습니다. 어떻게 도와드릴까요?"}
