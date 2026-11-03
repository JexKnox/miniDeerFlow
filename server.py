"""miniDeerFlow FastAPI 服务（对应 DeerFlow 的 server.py）。

POST /api/chat/stream — SSE 流式接口
    请求体：
        {
          "messages": [{"role": "user", "content": "分析最近一天防火墙日志"}],
          "auto_accepted_plan": true,        // 可选，默认 true（跳过计划确认中断）
          "thread_id": "xxx"                 // 可选，多轮会话 ID
        }
    SSE 事件（data: {"type": ..., "node": ..., "content": ...}）：
        type=node_start   节点开始（node 为 planner/researcher/coder/analyst/reporter 等）
        type=plan         分析计划（content 为步骤列表文本）
        type=observation  单步执行结果
        type=interrupt    计划确认中断（携带 thread_id，客户端批准后重新请求）
        type=report       最终报告（Markdown）
        type=done         本轮结束
        type=error        出错

POST /api/chat/feedback — 计划确认反馈（恢复被 interrupt 的会话）
    请求体：{"thread_id": "xxx", "approved": true, "feedback": "..."}

GET  /api/health — 健康检查
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from pydantic import BaseModel

from src.graph.builder import build_graph_with_memory

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("miniDeerflow.server")

app = FastAPI(title="miniDeerFlow - Network Traffic Analysis Agent", version="0.1.0")

# 每个会话一个带 MemorySaver 的图实例（简化实现：全局单图 + thread_id 区分会话）
_graph = build_graph_with_memory()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    auto_accepted_plan: bool = True
    thread_id: Optional[str] = None
    # 恢复中断时携带的反馈
    feedback: Optional[dict] = None


class FeedbackRequest(BaseModel):
    thread_id: str
    approved: bool = True
    feedback: str = ""


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _plan_to_text(plan) -> str:
    lines = [plan.title]
    for i, s in enumerate(plan.steps, 1):
        lines.append(f"{i}. [{s.step_type.value}] {s.title}：{s.description}")
    return "\n".join(lines)


@app.get("/api/health")
async def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    thread_id = req.thread_id or f"thread-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    config = {"configurable": {"thread_id": thread_id}}

    async def event_generator():
        yield _sse({"type": "meta", "thread_id": thread_id})
        try:
            # 中断恢复：携带反馈 resume；否则以新输入启动
            if req.feedback is not None:
                graph_input = Command(resume=req.feedback)
            else:
                graph_input = {
                    "messages": [HumanMessage(content=m.content) for m in req.messages if m.role == "user"],
                    "research_topic": next((m.content for m in reversed(req.messages) if m.role == "user"), ""),
                    "locale": "zh-CN",
                    "current_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "auto_accepted_plan": req.auto_accepted_plan,
                }

            async for chunk in _graph.astream(graph_input, config=config, stream_mode="updates"):
                for node_name, updates in chunk.items():
                    if node_name == "__interrupt__":
                        intr = updates[0] if isinstance(updates, list) else updates
                        payload = intr.value if hasattr(intr, "value") else intr
                        yield _sse({
                            "type": "interrupt",
                            "node": "human_feedback",
                            "thread_id": thread_id,
                            "content": payload,
                        })
                        yield _sse({"type": "done", "thread_id": thread_id})
                        return
                    if not updates:
                        continue
                    if node_name == "planner":
                        plan = updates.get("current_plan")
                        if plan is not None:
                            yield _sse({"type": "plan", "node": "planner",
                                        "content": _plan_to_text(plan)})
                    if node_name == "coordinator":
                        # 闲聊直接回复
                        msgs = updates.get("messages") or []
                        if msgs:
                            yield _sse({"type": "message", "node": "coordinator",
                                        "content": str(msgs[-1].content)})
                        continue
                    for obs in updates.get("observations", []) or []:
                        yield _sse({"type": "observation", "node": node_name, "content": obs})
                    report = updates.get("final_report")
                    if report:
                        yield _sse({"type": "report", "node": "reporter", "content": report})
            yield _sse({"type": "done", "thread_id": thread_id})
        except Exception as ex:
            logger.exception("流式处理出错")
            yield _sse({"type": "error", "content": f"{type(ex).__name__}: {ex}"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/chat/feedback")
async def chat_feedback(req: FeedbackRequest):
    """对 interrupt 的计划确认提交反馈，返回新的 SSE 流（接口同 /api/chat/stream）。"""
    return await chat_stream(ChatRequest(
        messages=[ChatMessage(role="user", content="")],
        thread_id=req.thread_id,
        feedback={"approved": req.approved, "feedback": req.feedback},
    ))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
