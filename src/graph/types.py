"""工作流状态定义（对应 DeerFlow 的 src/graph/types.py）。"""

from typing import Annotated, Any, Optional

from langgraph.graph import MessagesState

from src.prompts.planner_model import Plan


def _merge_list(current: list, update: list | None) -> list:
    """列表字段采用追加语义（observations 逐条累积）。"""
    if update is None:
        return current
    return current + update


class State(MessagesState):
    """Agent 系统状态：在消息历史之上附加工作流控制字段。"""

    # 运行时变量
    locale: str = "zh-CN"
    research_topic: str = ""
    user_prompt: str = ""  # 当前要执行的步骤任务（注入 researcher/coder 的 user message）
    current_time: str = ""

    # 分析过程
    observations: Annotated[list[str], _merge_list] = []
    background_investigation_results: str = ""
    plan_iterations: int = 0
    current_plan: Optional[Plan] = None
    final_report: str = ""

    # 工作流控制
    auto_accepted_plan: bool = False
    enable_background_investigation: bool = True

    # 中断恢复时携带的人类反馈
    human_feedback: dict[str, Any] = {}
