"""提示词模板渲染（对应 DeerFlow 的 src/prompts/template.py）。

每个节点的提示词是 src/prompts/<node>.md，支持 Jinja2 变量
（{{ research_topic }}、{{ locale }}、{{ background_investigation_results }} 等）。
"""

from pathlib import Path
from typing import Any

from jinja2 import StrictUndefined, Template

from src.config.configuration import get_log_path
from src.graph.types import State

PROMPTS_DIR = Path(__file__).parent

# 模板渲染时可用的公共变量
_COMMON_VARS: dict[str, Any] = {
    "log_file_path": str(get_log_path()),
}

# 各节点允许使用的额外状态变量（防止误注入超大字段）
_NODE_STATE_VARS: dict[str, list[str]] = {
    "coordinator": ["research_topic"],
    "planner": [
        "research_topic",
        "background_investigation_results",
        "locale",
    ],
    "researcher": ["research_topic", "locale", "current_plan"],
    "coder": ["research_topic", "locale", "current_plan"],
    "analyst": ["research_topic", "locale", "observations"],
    "reporter": ["research_topic", "locale", "observations"],
}


def apply_prompt_template(node: str, state: State) -> tuple[str, str]:
    """加载并渲染节点提示词模板。

    返回 (system_prompt, user_prompt)。user_prompt 取自状态中最后一条
    HumanMessage（researcher/coder 等执行节点用它承载当前步骤任务）。
    """
    template_path = PROMPTS_DIR / f"{node}.md"
    if not template_path.exists():
        raise FileNotFoundError(f"缺少提示词模板 {template_path}")

    variables: dict[str, Any] = dict(_COMMON_VARS)
    variables["current_time"] = state.get("current_time", "")
    for key in _NODE_STATE_VARS.get(node, []):
        variables[key] = state.get(key, "")

    template = Template(template_path.read_text(encoding="utf-8"), undefined=StrictUndefined)
    system_prompt = template.render(**variables)

    # user prompt：显式传入则用之，否则回退到最后一条用户消息
    user_prompt = state.get("user_prompt", "")
    if not user_prompt:
        for msg in reversed(state.get("messages", [])):
            msg_type = getattr(msg, "type", msg.get("role", "") if isinstance(msg, dict) else "")
            content = getattr(msg, "content", msg.get("content", "")) if isinstance(msg, dict) else msg.content
            if msg_type in ("human", "user"):
                user_prompt = str(content)
                break

    return system_prompt, user_prompt
