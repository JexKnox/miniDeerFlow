"""配置加载：conf.yaml + .env。

conf.yaml 中的 `${ENV_VAR}` 占位符在加载时展开（支持 `${VAR:-default}` 语法），
敏感信息（API key、模型名）统一放 .env，不进版本库。
"""

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_ENV_PATTERN = re.compile(r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]*))?\}")


def _expand_env(value: Any) -> Any:
    """递归展开配置值中的 ${ENV_VAR} / ${VAR:-default} 占位符。"""
    if isinstance(value, str):
        def repl(m: re.Match) -> str:
            env_val = os.environ.get(m.group("name"))
            if env_val is not None and env_val != "":
                return env_val
            if m.group("default") is not None:
                return m.group("default")
            # 未设置且无默认值 → 保留原样，便于报错定位
            return m.group(0)

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


@lru_cache
def load_config() -> dict[str, Any]:
    """加载 conf.yaml（.env 先于其读取，保证占位符可展开）。"""
    load_dotenv(PROJECT_ROOT / ".env")
    conf_path = PROJECT_ROOT / "conf.yaml"
    if not conf_path.exists():
        raise FileNotFoundError(
            f"缺少配置文件 {conf_path}，请参考 conf.yaml 与 .env.example 完成配置"
        )
    with open(conf_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return _expand_env(raw)


def get_llm_config(model_type: str) -> dict[str, Any]:
    """获取指定档位（BASIC_MODEL / REASONING_MODEL）的 LLM 配置。"""
    cfg = load_config().get("LLM", {})
    if model_type not in cfg:
        raise KeyError(f"conf.yaml 中未配置 LLM.{model_type}")
    return cfg[model_type]


def get_log_path() -> Path:
    """防火墙日志文件路径（环境变量 LOG_FILE_PATH 优先级高于 conf.yaml）。"""
    env_path = os.environ.get("LOG_FILE_PATH")
    if env_path:
        p = Path(env_path)
    else:
        p = Path(load_config().get("LOG", {}).get("file_path", "data/firewall.log"))
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p
