"""工作流节点实现（对应 DeerFlow 的 src/graph/nodes.py）。

图结构：coordinator → background_investigator → planner → human_feedback
        → research_team → {researcher | coder | analyst} →（全部完成后回 planner）→ reporter → END
"""

import logging
from datetime import datetime, timezone
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.types import Command, interrupt
from pydantic import BaseModel

from src.agents import create_coder_agent, create_researcher_agent, run_agent
from src.llms.llm import get_llm_by_type
from src.prompts.planner_model import Plan
from src.prompts.template import apply_prompt_template
from src.tools.log_query import describe_log_source, get_log_stats
from src.graph.types import State

logger = logging.getLogger(__name__)

# 允许的最大规划轮数（超过则强制收敛，防止 planner/research_team 死循环）
MAX_PLAN_ITERATIONS = 3


# ---------------------------------------------------------------------------
# 工具：coordinator 用来显式移交控制权
# ---------------------------------------------------------------------------

@tool
def handoff_to_planner(
    research_topic: str,
    locale: str,
):
    """用户请求是流量分析任务时，调用此工具移交规划员。research_topic 为完整的需求描述。"""
    return


# ---------------------------------------------------------------------------
# 节点实现
# ---------------------------------------------------------------------------

async def coordinator_node(state: State) -> Command[Literal["planner", "__end__"]]:
    """判断用户输入是流量分析任务还是闲聊。"""
    logger.info("coordinator 运行中")
    goto = "end"
    locale = state.get("locale", "zh-CN")

    system_prompt, user_prompt = apply_prompt_template("coordinator", state)
    llm = get_llm_by_type("basic").bind_tools([handoff_to_planner])
    response = await llm.ainvoke(
        [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
    )

    content = response.content or ""
    tool_calls = getattr(response, "tool_calls", None)
    if tool_calls:
        # LLM 决定移交规划员
        call = tool_calls[0]
        if call.get("name") == "handoff_to_planner":
            args = call.get("args", {})
            research_topic = args.get("research_topic") or state.get("research_topic")
            locale = args.get("locale") or locale
            return Command(
                update={
                    "research_topic": research_topic,
                    "locale": locale,
                    "messages": [AIMessage(content=content)],
                },
                goto="background_investigator",
            )

    # 闲聊：直接回复并结束本轮
    return Command(
        update={
            "messages": [AIMessage(content=content)],
        },
        goto=END_NODE,
    )


END_NODE = "__end__"


async def background_investigation_node(state: State) -> Command["planner"]:
    """背景摸底：直接调用统计工具获取数据源概览，供 planner 参考。"""
    logger.info("background investigation 运行中")
    if not state.get("enable_background_investigation", True):
        return Command(goto="planner")

    overview = describe_log_source.invoke({})
    top_src = get_log_stats.invoke({"group_by": "src_ip", "top": 5})
    top_port = get_log_stats.invoke({"group_by": "dst_port", "action": "DENY", "top": 5})
    results = f"{overview}\n\nTop 源 IP 统计：\n{top_src}\n\nDENY Top 目标端口统计：\n{top_port}"
    logger.info("背景摸底完成")
    return Command(
        update={"background_investigation_results": results},
        goto="planner",
    )


class PlannerOutput(BaseModel):
    """planner 结构化输出包装。"""

    plan: Plan


async def planner_node(state: State) -> Command[Literal["human_feedback", "reporter"]]:
    """生成/更新分析计划；信息足够时移交给报告员。"""
    logger.info("planner 运行中（第 %d 轮）", state.get("plan_iterations", 0) + 1)
    plan_iterations = state.get("plan_iterations", 0)

    system_prompt, user_prompt = apply_prompt_template("planner", state)
    if plan_iterations > 0:
        # 重规划：附带已完成步骤的执行结果，帮助 planner 判断信息是否充分
        executed = "\n".join(
            f"- {s.title}: {s.execution_res}" for s in (state.get("current_plan").steps if state.get("current_plan") else [])
        )
        system_prompt += (
            f"\n\n## 已有计划及执行结果（第 {plan_iterations} 轮规划，可在此基础上收敛）\n{executed}"
        )

    llm = get_llm_by_type("reasoning")
    structured_llm = llm.with_structured_output(Plan)
    messages = [SystemMessage(content=system_prompt)]
    if user_prompt:
        messages.append(HumanMessage(content=user_prompt))

    plan: Plan = await structured_llm.ainvoke(messages)

    # 防死循环：达到上限轮数仍未收敛则强制结束
    if plan_iterations >= MAX_PLAN_ITERATIONS - 1 and not plan.has_enough_context:
        logger.warning("达到最大规划轮数，强制进入报告生成")
        plan.has_enough_context = True
        plan.steps = []

    if plan.has_enough_context and not plan.steps:
        return Command(
            update={"current_plan": plan, "plan_iterations": plan_iterations + 1},
            goto="reporter",
        )

    return Command(
        update={"current_plan": plan, "plan_iterations": plan_iterations + 1},
        goto="human_feedback",
    )


async def human_feedback_node(state: State) -> Command["research_team"]:
    """计划确认（human-in-the-loop）。auto_accepted_plan=true 时跳过。"""
    logger.info("human_feedback 运行中")
    if state.get("auto_accepted_plan", False):
        return Command(goto="research_team")

    current_plan = state.get("current_plan")
    plan_text = "\n".join(
        f"{i + 1}. [{s.step_type.value}] {s.title}：{s.description}"
        for i, s in enumerate(current_plan.steps)
    )
    feedback = interrupt(
        {
            "question": "请确认分析计划，或提出修改意见：",
            "plan": plan_text,
        }
    )

    # interrupt 恢复时，feedback 为用户回复（dict: {"approved": bool, "feedback": str} 或 str）
    if isinstance(feedback, dict):
        approved = feedback.get("approved", True)
        feedback_text = feedback.get("feedback", "")
    else:
        approved = True
        feedback_text = str(feedback)

    if not approved or any(k in feedback_text for k in ("修改", "不要", "调整", "改一下")):
        # 带反馈重新规划
        research_topic = state.get("research_topic", "")
        if feedback_text:
            research_topic += f"\n\n（用户对计划的修改意见：{feedback_text}）"
        return Command(
            update={"research_topic": research_topic, "plan_iterations": state.get("plan_iterations", 0)},
            goto="planner",
        )

    return Command(goto="research_team")


def _first_incomplete_step(state: State):
    current_plan = state.get("current_plan")
    if not current_plan or not current_plan.steps:
        return None
    for step in current_plan.steps:
        if not step.execution_res:
            return step
    return None


async def research_team_node(state: State) -> Command[Literal["planner", "researcher", "coder", "analyst"]]:
    """调度器：把当前步骤路由到对应执行节点。"""
    step = _first_incomplete_step(state)
    if step is None:
        return Command(goto="planner")  # 全部完成 → 回 planner 评估是否收敛

    # 把步骤任务写入 user_prompt，供执行节点作为任务输入
    task = f"{step.title}\n任务描述：{step.description}\n\n用户原始需求（供参考）：{state.get('research_topic', '')}"
    if step.step_type.value == "research":
        return Command(update={"user_prompt": task}, goto="researcher")
    if step.step_type.value == "processing":
        return Command(update={"user_prompt": task}, goto="coder")
    if step.step_type.value == "analysis":
        return Command(update={"user_prompt": task}, goto="analyst")
    return Command(goto="planner")


async def researcher_node(state: State) -> Command["research_team"]:
    """日志取证：ReAct agent 多轮调用日志查询工具。"""
    logger.info("researcher 运行中")
    agent = create_researcher_agent(get_llm_by_type("basic"))
    conclusion = await run_agent(agent, "researcher", state)
    return _finish_step(state, conclusion)


async def coder_node(state: State) -> Command["research_team"]:
    """代码分析：ReAct agent 编写并执行 pandas 代码。"""
    logger.info("coder 运行中")
    agent = create_coder_agent(get_llm_by_type("basic"))
    conclusion = await run_agent(agent, "coder", state)
    return _finish_step(state, conclusion)


async def analyst_node(state: State) -> Command["research_team"]:
    """推理研判：结合已有观察结果做安全事件分析。"""
    logger.info("analyst 运行中")
    system_prompt, user_prompt = apply_prompt_template("analyst", state)
    messages = [SystemMessage(content=system_prompt)]
    if user_prompt:
        messages.append(HumanMessage(content=user_prompt))
    llm = get_llm_by_type("reasoning")
    response = await llm.ainvoke(messages)
    return _finish_step(state, str(response.content))


def _finish_step(state: State, conclusion: str) -> Command["research_team"]:
    """回填当前步骤的执行结果，并追加到 observations。"""
    current_plan: Plan = state.get("current_plan")
    step = _first_incomplete_step(state)
    step.execution_res = conclusion
    return Command(
        update={
            "current_plan": current_plan,
            "observations": [f"[{step.step_type.value}] {step.title}\n{conclusion}"],
        },
        goto="research_team",
    )


async def reporter_node(state: State) -> Command["__end__"]:
    """汇总观察结果生成最终报告。"""
    logger.info("reporter 运行中")
    system_prompt, user_prompt = apply_prompt_template("reporter", state)
    messages = [SystemMessage(content=system_prompt)]
    if user_prompt:
        messages.append(HumanMessage(content=user_prompt))
    llm = get_llm_by_type("basic")
    response = await llm.ainvoke(messages)
    final_report = str(response.content)
    return Command(
        update={
            "final_report": final_report,
            "messages": [AIMessage(content=final_report)],
        },
        goto=END_NODE,
    )
