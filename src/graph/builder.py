"""LangGraph 工作流组装（对应 DeerFlow 的 src/graph/builder.py）。

图结构：
    START → coordinator → background_investigator → planner
          → human_feedback → research_team ⇄ {researcher | coder | analyst}
          →（步骤全部完成回 planner 收敛）→ reporter → END
"""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .nodes import (
    analyst_node,
    background_investigation_node,
    coder_node,
    coordinator_node,
    human_feedback_node,
    planner_node,
    reporter_node,
    research_team_node,
    researcher_node,
)
from .types import State


def _build_base_graph() -> StateGraph:
    builder = StateGraph(State)
    builder.add_edge(START, "coordinator")
    builder.add_node("coordinator", coordinator_node)
    builder.add_node("background_investigator", background_investigation_node)
    builder.add_node("planner", planner_node)
    builder.add_node("human_feedback", human_feedback_node)
    builder.add_node("research_team", research_team_node)
    builder.add_node("researcher", researcher_node)
    builder.add_node("coder", coder_node)
    builder.add_node("analyst", analyst_node)
    builder.add_node("reporter", reporter_node)
    builder.add_edge("background_investigator", "planner")
    builder.add_edge("human_feedback", "research_team")
    builder.add_edge("researcher", "research_team")
    builder.add_edge("coder", "research_team")
    builder.add_edge("analyst", "research_team")
    builder.add_edge("reporter", END)
    # coordinator / research_team / planner 通过 Command(goto=...) 显式路由，无需静态边
    return builder


def build_graph_with_memory():
    """构建带内存检查点的工作流（server 多轮会话用）。"""
    return _build_base_graph().compile(checkpointer=MemorySaver())


def build_graph():
    """构建无检查点的工作流（CLI 单轮分析用）。"""
    return _build_base_graph().compile()


graph = build_graph()
