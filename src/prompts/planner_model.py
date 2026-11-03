"""Planner 的结构化输出模型（对应 DeerFlow 的 src/prompts/planner_model.py）。

领域化语义：
    RESEARCH   = 日志取证（调用日志查询工具核实事实）
    PROCESSING = 代码分析（写 Python/pandas 做统计）
    ANALYSIS   = 推理研判（结合观察结果推断攻击行为与影响）
"""

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class StepType(str, Enum):
    RESEARCH = "research"
    ANALYSIS = "analysis"
    PROCESSING = "processing"


class Step(BaseModel):
    need_search: bool = Field(
        ..., description="该步骤是否需要查询日志获取数据（research 类型必须为 true）"
    )
    title: str = Field(..., description="步骤标题（简短）")
    description: str = Field(..., description="步骤要做什么、要查询哪些字段或统计什么指标")
    step_type: StepType = Field(..., description="research=日志取证 / processing=代码统计 / analysis=推理研判")
    execution_res: Optional[str] = Field(default=None, description="步骤执行结果（由系统回填，规划时留空）")


class Plan(BaseModel):
    locale: str = Field(..., description="用户语言，如 'zh-CN' 或 'en-US'")
    has_enough_context: bool = Field(
        ..., description="已收集的信息是否足以产出最终分析报告"
    )
    thought: str = Field(default="", description="规划的思考过程")
    title: str = Field(..., description="分析计划标题")
    steps: List[Step] = Field(default_factory=list, description="分析步骤列表")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "has_enough_context": False,
                    "thought": "需要先摸底整体流量分布，再定位可疑行为。",
                    "title": "防火墙日志异常行为分析",
                    "steps": [
                        {
                            "need_search": True,
                            "title": "统计高频源 IP",
                            "description": "按 src_ip 聚合统计记录数与流量，找出请求量异常高的源 IP。",
                            "step_type": "research",
                        },
                        {
                            "need_search": False,
                            "title": "计算流量时序分布",
                            "description": "用 pandas 按小时统计 DENY 记录数与字节数，定位攻击时间窗口。",
                            "step_type": "processing",
                        },
                    ],
                }
            ]
        }
    }
