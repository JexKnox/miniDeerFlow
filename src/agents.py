"""ReAct agent 封装（对应 DeerFlow 的 src/agents.py）。

researcher / coder 是工具调用型 agent：以节点提示词为 system message，
当前步骤任务为 user message，让 LLM 自主多轮调用工具后给出结论。
"""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from src.prompts.template import apply_prompt_template
from src.tools import CODER_TOOLS, RESEARCHER_TOOLS


def create_researcher_agent(llm: BaseChatModel) -> object:
    """日志取证 agent：多轮调用 query_logs / get_log_stats 等工具后总结事实。"""
    return create_react_agent(llm, tools=RESEARCHER_TOOLS)


def create_coder_agent(llm: BaseChatModel) -> object:
    """代码分析 agent：编写并执行 pandas 代码做流量统计。"""
    return create_react_agent(llm, tools=CODER_TOOLS)


async def run_agent(agent, node_name: str, state) -> str:
    """执行一个 ReAct agent 并返回其最终结论文本。"""
    system_prompt, user_prompt = apply_prompt_template(node_name, state)
    result = await agent.ainvoke(
        {"messages": [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]}
    )
    # 最后一条 AI 消息即结论
    return str(result["messages"][-1].content)
