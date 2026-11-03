from .log_query import describe_log_source, get_log_stats, query_logs
from .python_repl import python_repl

# researcher 可用的工具集（日志取证）
RESEARCHER_TOOLS = [describe_log_source, query_logs, get_log_stats]

# coder 可用的工具集（代码分析）
CODER_TOOLS = [python_repl]

__all__ = [
    "describe_log_source",
    "query_logs",
    "get_log_stats",
    "python_repl",
    "RESEARCHER_TOOLS",
    "CODER_TOOLS",
]
