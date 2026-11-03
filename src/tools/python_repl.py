"""受限 Python REPL 工具（coder 的"手"，对应 DeerFlow 的 python_repl_tool）。

在独立命名空间中 exec 代码，捕获 stdout 返回给 LLM。预置 pandas 并告知日志
文件路径，coder 用它做工具难以表达的深度分析（时序分布、多条件透视等）。
"""

import io
import sys
from contextlib import redirect_stdout

from langchain_core.tools import tool

from src.config.configuration import get_log_path

# 保留每次调用的全局命名空间，使 coder 能跨多次调用累积变量（类似 Jupyter）
_GLOBAL_NS: dict = {}


@tool
def python_repl(code: str) -> str:
    """执行 Python 代码进行流量数据分析，返回代码的 stdout 输出。

    可用环境：
    - 已导入 pandas（as pd）；日志文件路径在变量 LOG_FILE 中，可用 pd.read_csv 读取：
      df = pd.read_csv(LOG_FILE, sep=r'\\s+', names=['ts','action','protocol','src','dst','bytes_','packets_','rule'])
      其中 src/dst 形如 "1.2.3.4:5678"，bytes_/packets_ 形如 "bytes=123"/"packets=4"，需自行清洗。
    - 变量在多次调用间保留（类似 Jupyter notebook）。
    - 适合做时序统计、分组透视、异常阈值计算等 query_logs/get_log_stats 表达不了的分析。
    """
    local_ns = {"LOG_FILE": str(get_log_path())}
    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            exec(  # noqa: S102 - 受控环境，代码由 coder agent 生成
                "import pandas as pd\n" + code,
                _GLOBAL_NS,
                local_ns,
            )
    except Exception as ex:  # 把异常信息回传给 LLM 便于其修正代码
        return f"执行出错：{type(ex).__name__}: {ex}\nstdout 输出：\n{buffer.getvalue()}"
    finally:
        sys.stdout.flush()
    output = buffer.getvalue()
    if not output:
        return "代码执行成功（无 stdout 输出）。请用 print() 输出分析结果。"
    # 截断超长输出，防止上下文溢出
    if len(output) > 20000:
        output = output[:20000] + "\n...（输出过长已截断）"
    return output
