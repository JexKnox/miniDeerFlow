# miniDeerFlow

基于字节跳动 [DeerFlow](https://github.com/bytedance/deer-flow) 经典深度研究架构（LangGraph 多智能体工作流）二次开发的**网络流量分析 Agent**：输入自然语言分析需求，自动查询防火墙/安全日志，产出结构化的安全分析报告。

## 架构

```
START → coordinator → background_investigator → planner
     → human_feedback(可中断确认) → research_team ⇄ ┬─ researcher（日志取证：query_logs / get_log_stats）
                                                     ├─ coder（代码分析：pandas REPL）
                                                     └─ analyst（推理研判）
     →（步骤全部完成后回 planner 收敛）→ reporter → END
```

| 节点 | 职责 | LLM 档位 |
|---|---|---|
| coordinator | 识别输入是流量分析任务还是闲聊（tool-call 移交） | basic |
| background_investigator | 调用统计工具摸底数据源（时间范围/Top IP/Top 端口） | 无 LLM |
| planner | 结构化输出分析计划（Pydantic `Plan`，步骤分 research/processing/analysis） | reasoning |
| human_feedback | 人工确认计划（LangGraph `interrupt`，可跳过） | 无 LLM |
| research_team | 调度器：路由第一个未完成步骤到对应执行节点 | 无 LLM |
| researcher | ReAct agent，多轮调用日志查询工具核实事实 | basic |
| coder | ReAct agent，编写并执行 pandas 代码做深度统计 | basic |
| analyst | 结合全部观察结果做安全事件研判 | reasoning |
| reporter | 汇总生成中文 Markdown 报告 | basic |

## 快速开始

要求：Python ≥ 3.12（推荐用 [uv](https://docs.astral.sh/uv/) 管理）

```bash
# 1. 安装依赖
uv sync

# 2. 配置 LLM（OpenAI 兼容接口或 Anthropic，二选一）
cp .env.example .env
# 编辑 .env 填入 LLM_PROVIDER / LLM_BASE_URL / LLM_API_KEY / *_MODEL_NAME

# 3. 生成样例防火墙日志（含端口扫描/SSH爆破/DDoS/数据外传四类注入攻击）
uv run python scripts/gen_sample_logs.py

# 4. CLI 交互式分析
uv run python main.py
# 或一次性任务 + 自动确认计划
uv run python main.py --auto-accept --topic "分析防火墙日志，找出可疑行为"

# 5. 启动 API 服务（SSE 流式）
uv run uvicorn server:app --port 8000
```

报告输出至终端并保存到 `reports/report_*.md`。

## API

### `POST /api/chat/stream`（SSE）

```bash
curl -N -X POST localhost:8000/api/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"分析最近一天防火墙日志中的可疑行为"}]}'
```

事件流：`meta`（会话 ID）→ `plan`（分析计划）→ `observation`（各步骤执行结果）→ `report`（最终报告）→ `done`。闲聊请求返回 `message` 事件。设置 `auto_accepted_plan: false` 时会发出 `interrupt` 事件，客户端通过 `POST /api/chat/feedback`（`{"thread_id", "approved", "feedback"}`）提交确认后继续。

### `GET /api/health`

健康检查。

## 日志格式

一行一条（`scripts/gen_sample_logs.py` 生成样例，也兼容同格式真实日志）：

```
2026-11-02T10:23:45Z DENY tcp 203.0.113.5:52341 10.0.0.12:22 bytes=0 packets=4 rule=BLOCK_SSH_BRUTE
```

字段：`时间戳(UTC ISO8601) action(ALLOW|DENY) protocol src_ip:port dst_ip:port bytes packets rule`

## 目录结构

```
main.py                 CLI 入口
server.py               FastAPI + SSE 服务
conf.yaml               LLM 与日志路径配置（${ENV_VAR} 占位符）
src/
├── config/configuration.py   配置加载
├── llms/llm.py               LLM 工厂（openai / anthropic provider）
├── agents.py                 ReAct agent 封装
├── prompts/                  各节点中文提示词（Markdown + Jinja2）
│   └── planner_model.py      Plan/Step 结构化输出模型
├── graph/
│   ├── types.py              工作流 State
│   ├── nodes.py              全部节点实现
│   └── builder.py            StateGraph 组装
└── tools/
    ├── log_query.py          日志查询/聚合工具（researcher）
    └── python_repl.py        受限 Python REPL（coder）
scripts/gen_sample_logs.py    合成日志生成器
```

## 致谢

架构参考 [bytedance/deer-flow](https://github.com/bytedance/deer-flow)（MIT License）经典深度研究工作流。
