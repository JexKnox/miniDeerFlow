"""防火墙日志解析与查询工具（researcher 的"眼睛"，对应 DeerFlow 的 web search/crawl）。

日志格式（由 scripts/gen_sample_logs.py 生成，也兼容同格式的真实日志）：
    <ISO8601时间戳> <action> <protocol> <src_ip>:<src_port> <dst_ip>:<dst_port> bytes=<n> packets=<n> rule=<规则名>
"""

import re
from dataclasses import dataclass
from pathlib import Path

from langchain_core.tools import tool

from src.config.configuration import get_log_path

LINE_RE = re.compile(
    r"^(?P<ts>\S+)\s+(?P<action>ALLOW|DENY)\s+(?P<proto>\w+)\s+"
    r"(?P<src_ip>[\d.]+):(?P<src_port>\d+)\s+(?P<dst_ip>[\d.]+):(?P<dst_port>\d+)\s+"
    r"bytes=(?P<bytes>\d+)\s+packets=(?P<packets>\d+)\s+rule=(?P<rule>\S+)$"
)

LOG_FORMAT_DOC = (
    "每行格式：<ISO8601时间戳(UTC)> <action(ALLOW|DENY)> <protocol> "
    "<src_ip>:<src_port> <dst_ip>:<dst_port> bytes=<字节数> packets=<包数> rule=<防火墙规则名>"
)


@dataclass
class LogEntry:
    ts: str
    action: str
    protocol: str
    src_ip: str
    src_port: int
    dst_ip: str
    dst_port: int
    nbytes: int
    packets: int
    rule: str

    @property
    def raw(self) -> str:
        return (
            f"{self.ts} {self.action} {self.protocol} "
            f"{self.src_ip}:{self.src_port} {self.dst_ip}:{self.dst_port} "
            f"bytes={self.nbytes} packets={self.packets} rule={self.rule}"
        )


def parse_line(line: str) -> LogEntry | None:
    m = LINE_RE.match(line.strip())
    if not m:
        return None
    d = m.groupdict()
    return LogEntry(
        ts=d["ts"],
        action=d["action"],
        protocol=d["proto"],
        src_ip=d["src_ip"],
        src_port=int(d["src_port"]),
        dst_ip=d["dst_ip"],
        dst_port=int(d["dst_port"]),
        nbytes=int(d["bytes"]),
        packets=int(d["packets"]),
        rule=d["rule"],
    )


def load_entries(path: Path | None = None) -> tuple[list[LogEntry], Path]:
    """加载并解析全部日志行（跳过无法解析的行）。"""
    p = path or get_log_path()
    if not p.exists():
        raise FileNotFoundError(f"日志文件不存在：{p}（可运行 scripts/gen_sample_logs.py 生成样例数据）")
    entries = []
    with open(p, encoding="utf-8", errors="replace") as f:
        for line in f:
            e = parse_line(line)
            if e:
                entries.append(e)
    return entries, p


def _match(
    e: LogEntry,
    time_start: str | None,
    time_end: str | None,
    src_ip: str | None,
    dst_ip: str | None,
    dst_port: int | None,
    action: str | None,
    protocol: str | None,
    keyword: str | None,
) -> bool:
    if time_start and e.ts < time_start:
        return False
    if time_end and e.ts > time_end:
        return False
    if src_ip and e.src_ip != src_ip:
        return False
    if dst_ip and e.dst_ip != dst_ip:
        return False
    if dst_port is not None and e.dst_port != dst_port:
        return False
    if action and e.action != action.upper():
        return False
    if protocol and e.protocol != protocol.lower():
        return False
    if keyword and keyword.lower() not in e.raw.lower():
        return False
    return True


@tool
def describe_log_source() -> str:
    """概览当前防火墙日志数据源：文件路径、时间范围、总行数、字段格式说明。在制定分析计划前调用。"""
    entries, path = load_entries()
    if not entries:
        return f"日志文件 {path} 为空或无法解析。"
    total_bytes = sum(e.nbytes for e in entries)
    return (
        f"日志文件: {path}\n"
        f"总记录数: {len(entries)}\n"
        f"时间范围: {entries[0].ts} ~ {entries[-1].ts}\n"
        f"动作分布: ALLOW={sum(1 for e in entries if e.action == 'ALLOW')}, "
        f"DENY={sum(1 for e in entries if e.action == 'DENY')}\n"
        f"总流量: {total_bytes / 1_000_000:.1f} MB\n"
        f"格式说明: {LOG_FORMAT_DOC}"
    )


@tool
def query_logs(
    time_start: str | None = None,
    time_end: str | None = None,
    src_ip: str | None = None,
    dst_ip: str | None = None,
    dst_port: int | None = None,
    action: str | None = None,
    protocol: str | None = None,
    keyword: str | None = None,
    limit: int = 100,
) -> str:
    """按条件过滤防火墙日志，返回匹配的原始日志行。

    参数（均可选，组合使用时为 AND 关系）：
        time_start / time_end: ISO8601 时间范围，如 "2026-11-02T10:00:00Z"
        src_ip / dst_ip: 精确匹配源/目标 IP
        dst_port: 精确匹配目标端口
        action: "ALLOW" 或 "DENY"
        protocol: "tcp" / "udp" / "icmp"
        keyword: 关键字（如规则名 rule=BLOCK_SSH_BRUTE 或 IP 片段）
        limit: 最多返回的行数（默认 100，避免上下文溢出）

    返回：命中总数 + 前 limit 行日志；命中数很大时应改用 get_log_stats 做聚合。
    """
    try:
        entries, path = load_entries()
    except FileNotFoundError as ex:
        return str(ex)

    matched = [
        e for e in entries
        if _match(e, time_start, time_end, src_ip, dst_ip, dst_port,
                  action, protocol, keyword)
    ]
    if not matched:
        return "没有匹配的日志记录。"
    lines = [e.raw for e in matched[:limit]]
    head = (
        f"查询条件: time=[{time_start or '开始'}, {time_end or '结束'}]"
        f" src={src_ip or '-'} dst={dst_ip or '-'} dst_port={dst_port if dst_port is not None else '-'}"
        f" action={action or '-'} protocol={protocol or '-'} keyword={keyword or '-'}\n"
        f"命中 {len(matched)} 条（来自 {path}），显示前 {min(len(lines), limit)} 条：\n"
    )
    return head + "\n".join(lines)


@tool
def get_log_stats(
    group_by: str = "src_ip",
    time_start: str | None = None,
    time_end: str | None = None,
    action: str | None = None,
    top: int = 20,
) -> str:
    """聚合统计防火墙日志，用于发现异常模式（如单 IP 高频请求、异常大流量）。

    参数：
        group_by: 聚合维度，可选 "src_ip" / "dst_ip" / "dst_port" / "rule" / "action"
        time_start / time_end: ISO8601 时间范围过滤
        action: 仅统计 "ALLOW" 或 "DENY"
        top: 返回前 N 个分组（默认 20）

    返回：按记录数降序的分组统计（记录数 / 总字节 / 涉及目标端口数）。
    """
    try:
        entries, _ = load_entries()
    except FileNotFoundError as ex:
        return str(ex)

    valid_dims = {"src_ip", "dst_ip", "dst_port", "rule", "action"}
    if group_by not in valid_dims:
        return f"无效的 group_by '{group_by}'，可选值：{sorted(valid_dims)}"

    matched = [e for e in entries if _match(e, time_start, time_end, None, None,
                                            None, action, None, None)]
    if not matched:
        return "时间范围内没有日志记录。"

    groups: dict[str, dict] = {}
    for e in matched:
        key = getattr(e, group_by)
        key = str(key)
        g = groups.setdefault(key, {"count": 0, "bytes": 0, "dst_ports": set()})
        g["count"] += 1
        g["bytes"] += e.nbytes
        g["dst_ports"].add(e.dst_port)

    rows = sorted(groups.items(), key=lambda kv: kv[1]["count"], reverse=True)[:top]
    out = [
        f"按 {group_by} 聚合（时间范围 [{time_start or '开始'}, {time_end or '结束'}]，"
        f"action={action or '全部'}），共 {len(matched)} 条记录、{len(groups)} 个分组，Top {len(rows)}："
    ]
    out.append(f"{'分组':<18}{'记录数':>8}{'总流量(MB)':>12}{'目标端口数':>10}")
    for key, g in rows:
        out.append(
            f"{key:<18}{g['count']:>8}{g['bytes'] / 1_000_000:>12.2f}{len(g['dst_ports']):>10}"
        )
    return "\n".join(out)
