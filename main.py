"""miniDeerFlow CLI 入口。

交互式终端：输入流量分析需求，流式展示工作流各阶段进展，
human_feedback 阶段在终端确认计划，最终报告打印并存盘到 reports/。

用法：uv run python main.py [--auto-accept] [--topic "一次性分析需求"]
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.messages import HumanMessage
from langgraph.types import Command
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from src.graph.builder import build_graph_with_memory

console = Console()

REPORTS_DIR = Path(__file__).parent / "reports"

# 节点 → 展示名
NODE_TITLES = {
    "coordinator": "任务识别",
    "background_investigator": "背景摸底",
    "planner": "制定计划",
    "human_feedback": "计划确认",
    "research_team": "任务调度",
    "researcher": "日志取证",
    "coder": "代码分析",
    "analyst": "推理研判",
    "reporter": "生成报告",
}


def _print_step_plan(state_updates: dict) -> None:
    """planner 输出后展示计划步骤。"""
    plan = state_updates.get("current_plan")
    if plan is None:
        return
    lines = [f"[bold]{plan.title}[/bold]"]
    for i, s in enumerate(plan.steps, 1):
        lines.append(f"  {i}. [cyan][{s.step_type.value}][/cyan] {s.title} — {s.description}")
    console.print(Panel("\n".join(lines), title="分析计划", border_style="blue"))


async def run_analysis(graph, topic: str, thread_id: str, auto_accept: bool) -> None:
    """执行一次完整分析（含中断-恢复的计划确认循环）。"""
    config = {"configurable": {"thread_id": thread_id}}
    state = {
        "messages": [HumanMessage(content=topic)],
        "research_topic": topic,
        "locale": "zh-CN",
        "current_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "auto_accepted_plan": auto_accept,
    }

    pending_feedback = None  # 等待用户反馈的 Command
    while True:
        try:
            stream = graph.astream(
                pending_feedback if pending_feedback is not None else state,
                config=config,
                stream_mode="updates",
            )
            pending_feedback = None
            async for chunk in stream:
                for node_name, updates in chunk.items():
                    if node_name == "__interrupt__":
                        # human_feedback 中断：在终端征求确认
                        intr = updates[0] if isinstance(updates, list) else updates
                        payload = intr.value if hasattr(intr, "value") else intr
                        console.print(Panel(payload.get("plan", ""), title=payload.get("question", "确认计划"), border_style="yellow"))
                        if auto_accept:
                            answer = "同意"
                        else:
                            answer = Prompt.ask("[yellow]回车确认执行，或输入修改意见[/yellow]", default="同意")
                        approved = answer.strip() in ("同意", "y", "yes", "确认", "")
                        pending_feedback = Command(resume={"approved": approved, "feedback": "" if approved else answer})
                        break
                    if node_name == "human_feedback" and updates is None:
                        continue
                    title = NODE_TITLES.get(node_name, node_name)
                    if updates:
                        console.print(f"[green]▶ {title}[/green]")
                        _print_step_plan(updates)
                        for obs in updates.get("observations", []) or []:
                            console.print(Panel(obs[:2000], title="观察结果", border_style="dim"))
                        report = updates.get("final_report")
                        if report:
                            console.print(Markdown(report))
                            REPORTS_DIR.mkdir(exist_ok=True)
                            out = REPORTS_DIR / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
                            out.write_text(report, encoding="utf-8")
                            console.print(f"[dim]报告已保存至 {out}[/dim]")
                    if node_name == "reporter":
                        return
            if pending_feedback is None:
                return
        except KeyboardInterrupt:
            console.print("\n[dim]已中断[/dim]")
            return


async def chat_loop(auto_accept: bool) -> None:
    # interrupt() 需要 checkpointer 支持，必须用带内存检查点的图
    graph = build_graph_with_memory()
    console.print(Panel(
        "[bold]miniDeerFlow 网络流量分析 Agent[/bold]\n"
        "基于 DeerFlow 架构（coordinator → planner → researcher/coder/analyst → reporter）\n"
        "输入分析需求开始，输入 exit 退出。",
        border_style="green",
    ))
    turn = 0
    while True:
        try:
            topic = console.input("\n[bold blue]需求 >[/bold blue] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not topic:
            continue
        if topic.lower() in ("exit", "quit", "退出"):
            break
        turn += 1
        await run_analysis(graph, topic, thread_id=f"cli-{turn}", auto_accept=auto_accept)
    console.print("[dim]再见[/dim]")


def main():
    parser = argparse.ArgumentParser(description="miniDeerFlow 网络流量分析 Agent（CLI）")
    parser.add_argument("--auto-accept", action="store_true", help="自动确认分析计划（跳过人工反馈）")
    parser.add_argument("--topic", help="一次性分析需求（执行完退出，不进入交互循环）")
    args = parser.parse_args()

    try:
        if args.topic:
            asyncio.run(run_analysis(build_graph_with_memory(), args.topic, "cli-once", args.auto_accept))
        else:
            asyncio.run(chat_loop(args.auto_accept))
    except FileNotFoundError as ex:
        console.print(f"[red]配置错误：{ex}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
