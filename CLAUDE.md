# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目简介

miniDeerFlow：基于字节 DeerFlow 经典深度研究架构（LangGraph 多智能体）的网络流量分析 Agent。用户输入自然语言需求，工作流自动查询防火墙日志并产出安全分析报告。提示词、注释、报告均为中文。

## 常用命令

```bash
uv sync                                  # 安装依赖（Python >= 3.12，uv 管理）
uv run python scripts/gen_sample_logs.py # 重新生成样例日志 data/firewall.log（含四类注入攻击）
uv run python main.py                    # CLI 交互式分析
uv run python main.py --auto-accept --topic "..."   # 一次性任务，跳过计划确认
uv run uvicorn server:app --port 8000    # FastAPI + SSE 服务
uv run ruff check src main.py server.py  # lint
```

端到端验证 SSE：`curl -N -X POST localhost:8000/api/chat/stream -H 'Content-Type: application/json' -d '{"messages":[{"role":"user","content":"分析防火墙日志"}]}'`

配置：`conf.yaml`（`${ENV_VAR}` 占位符，支持 `${VAR:-default}`）+ `.env`（参考 `.env.example`；`LLM_PROVIDER` 可选 openai / anthropic）。日志路径由 `LOG_FILE_PATH` 控制，默认 `data/firewall.log`。

## 架构（改动前必读）

LangGraph 状态图：`coordinator → background_investigator → planner → human_feedback → research_team ⇄ {researcher|coder|analyst} → reporter → END`

- **显式路由**：coordinator/planner/human_feedback/research_team 各节点用 `Command(goto=...)` 决定下一跳，`src/graph/builder.py` 里没有这些节点的静态出边；analyst/researcher/coder 执行完回 research_team。
- **步骤调度**（`src/graph/nodes.py: research_team_node`）：找 `current_plan.steps` 中第一个 `execution_res` 为空的步骤，按 `step_type`（research/processing/analysis）路由；全部完成回 planner 重新评估是否收敛。`_finish_step` 回填 `execution_res` 并把结论追加进 `observations`。
- **防死循环**：`MAX_PLAN_ITERATIONS=3`，超限强制 `has_enough_context=True` 进入报告生成。
- **State**（`src/graph/types.py`）：继承 `MessagesState`；`observations` 用 `_merge_list` 追加语义；`user_prompt` 字段是当前步骤任务，由 research_team 写入、执行节点读取。
- **提示词**：`src/prompts/<node>.md`（Jinja2），由 `apply_prompt_template(node, state)` 渲染；每个节点可用的状态变量在 `_NODE_STATE_VARS` 白名单里（改提示词引用新变量时需同步白名单）。
- **Plan 结构化输出**：`src/prompts/planner_model.py` 的 Pydantic `Plan`/`Step`，planner 用 `with_structured_output(Plan)` 生成。
- **工具**（`src/tools/`）：researcher 用 `log_query.py` 的 `describe_log_source/query_logs/get_log_stats`（对应 DeerFlow 的 web search/crawl）；coder 用 `python_repl.py`（exec + 持久命名空间，预置 pandas，`LOG_FILE` 变量指向日志路径）。工具输出有截断（防上下文溢出），改动时保持。
- **LLM 档位**：`src/llms/llm.py` 的 `get_llm_by_type("basic"|"reasoning")`（basic=researcher/coder/coordinator/reporter，reasoning=planner/analyst）。
- **日志格式**：`<ISO8601> <ALLOW|DENY> <proto> <src ip:port> <dst ip:port> bytes=<n> packets=<n> rule=<name>`，正则解析在 `src/tools/log_query.py: LINE_RE`。改格式需同步 `gen_sample_logs.py` 与 coder 提示词中的读取代码。

## 样例数据中的注入攻击（验证基准）

生成器注入四类攻击，端到端测试时报告应能发现：端口扫描（203.0.113.77 扫 10.0.0.10 约 1000 端口）、SSH 爆破（198.51.100.42 → :22 共 300 次）、DDoS（海量外部 IP → 10.0.0.10:443 约 2000 条 DENY）、数据外传（10.0.1.42 → 203.0.113.200:443，总量约 4GB）。
