# backend/agent/executor.py

import re
from .tools import make_toolset

class StepExecutor:
    """
    플래너가 생성한 계획의 단일 스텝(step)을 실행하는 역할.
    이전 단계의 결과를 플레이스홀더에 채워넣고 도구를 실행합니다.
    """
    def __init__(self, db, user, tz, llm, openai_client):
        self.tools_by_name = {
            tool.name: tool for tool in make_toolset(db, user, tz, openai_client, llm)
        }
        self.llm = llm

    def _replace_placeholders(self, arg_value: str, previous_step_outputs: dict) -> str:
        """문자열 내의 모든 {{step_N_output}} 플레이스홀더를 실제 값으로 치환합니다."""
        placeholders = re.findall(r"\{\{([\w_]+)\}\}", arg_value)
        
        for placeholder in placeholders:
            if placeholder in previous_step_outputs:
                replacement_value = str(previous_step_outputs[placeholder])
                print(f"      - Replacing placeholder '{{{{{placeholder}}}}}' with -> '{replacement_value[:100]}...'")
                arg_value = arg_value.replace(f"{{{{{placeholder}}}}}", replacement_value)
        return arg_value

    def execute_step(self, step: dict, previous_step_outputs: dict) -> dict:
        tool_name = step.get("tool")
        tool_args = step.get("args", {})

        # ‼️ [디버깅 로그 추가] 단계 실행 정보
        print("\n" + "-" * 28 + " EXECUTING STEP " + "-" * 28)
        print(f"  - 🛠️ Tool: {tool_name}")
        print(f"  - 📥 Original Args: {tool_args}")

        if tool_name not in self.tools_by_name:
            error_msg = f"Error: Tool '{tool_name}' not found."
            print(f"  - ❌ RESULT: {error_msg}")
            print("-" * 70)
            return {"output": error_msg}

        processed_args = {}
        for key, value in tool_args.items():
            if isinstance(value, str):
                processed_args[key] = self._replace_placeholders(value, previous_step_outputs)
            else:
                processed_args[key] = value

        if processed_args != tool_args:
             print(f"  - ⚙️ Processed Args: {processed_args}")

        tool_to_run = self.tools_by_name[tool_name]
        
        try:
            result = tool_to_run.invoke(processed_args)
            print(f"  - ✅ Result: {str(result)[:200]}...") # 결과가 너무 길 수 있으므로 일부만 출력
            print("-" * 70)
            return {"output": result}
        except Exception as e:
            error_msg = f"Error executing tool '{tool_name}': {e}"
            print(f"  - ❌ RESULT: {error_msg}")
            print("-" * 70)
            return {"output": error_msg}