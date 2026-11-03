"""LLM 工厂：按档位（basic / reasoning）返回 LLM 客户端。

支持 provider：openai（OpenAI 兼容接口，默认）/ anthropic（Anthropic 原生协议）。
"""

from functools import lru_cache

from langchain_core.language_models.chat_models import BaseChatModel

from src.config.configuration import get_llm_config

# 节点 → LLM 档位映射（对应 DeerFlow 的 AGENT_LLM_MAP）
AGENT_LLM_MAP = {
    "coordinator": "basic",
    "planner": "reasoning",
    "researcher": "basic",
    "coder": "basic",
    "analyst": "reasoning",
    "reporter": "basic",
}


@lru_cache
def get_llm_by_type(llm_type: str) -> BaseChatModel:
    """获取指定档位的 LLM 客户端（缓存实例）。

    llm_type: "basic"（常规任务）或 "reasoning"（规划/推理任务）
    """
    cfg = get_llm_config("BASIC_MODEL" if llm_type == "basic" else "REASONING_MODEL")
    provider = cfg.get("provider", "openai")
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=cfg["model"],
            base_url=cfg.get("base_url"),
            api_key=cfg.get("api_key"),
            temperature=cfg.get("temperature", 0.2),
            max_tokens=cfg.get("max_tokens", 8192),
        )
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=cfg["model"],
        base_url=cfg.get("base_url"),
        api_key=cfg.get("api_key"),
        temperature=cfg.get("temperature", 0.2),
        max_tokens=cfg.get("max_tokens", 8192),
    )
