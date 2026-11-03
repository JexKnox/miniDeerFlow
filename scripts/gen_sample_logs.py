"""生成合成防火墙日志（含注入的四类攻击模式），用于 miniDeerFlow 开发与测试。

日志格式（一行一条，空格分隔）：
    <ISO8601时间戳> <action> <protocol> <src_ip>:<src_port> <dst_ip>:<dst_port> bytes=<n> packets=<n> rule=<规则名>

注入的攻击模式：
    1. 端口扫描：单源 IP 在短时间内探测大量目标端口
    2. SSH 暴力破解：单源 IP 大量 DENY 到多个内网主机的 22 端口
    3. DDoS：大量外部 IP 向单一内网 Web 主机发送海量请求
    4. 数据外传：单内网 IP 向外部地址传输异常大的出站流量

用法：uv run python scripts/gen_sample_logs.py [--out data/firewall.log] [--days 1]
"""

import argparse
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 内网资产：Web 服务器、数据库、办公终端等
INTERNAL_SERVERS = ["10.0.0.10", "10.0.0.11", "10.0.0.12", "10.0.0.20", "10.0.0.21"]
INTERNAL_CLIENTS = [f"10.0.1.{i}" for i in range(2, 60)]
EXTERNAL_IPS = [f"203.0.113.{i}" for i in range(1, 200)] + [
    f"198.51.100.{i}" for i in range(1, 100)
]

COMMON_PORTS = [80, 443, 22, 3389, 3306, 5432, 6379, 8080, 8443, 25, 53]

ALLOW_RULES = {
    80: "ALLOW_WEB",
    443: "ALLOW_WEB",
    53: "ALLOW_DNS",
    25: "ALLOW_SMTP",
}
DENY_RULES = {
    22: "BLOCK_SSH_BRUTE",
    3389: "BLOCK_RDP",
    3306: "BLOCK_DB_EXT",
    5432: "BLOCK_DB_EXT",
    6379: "BLOCK_REDIS_EXT",
    8080: "BLOCK_ADMIN",
    8443: "BLOCK_ADMIN",
}

random.seed(2026)


def fmt_line(
    ts: datetime,
    action: str,
    protocol: str,
    src_ip: str,
    src_port: int,
    dst_ip: str,
    dst_port: int,
    nbytes: int,
    packets: int,
    rule: str,
) -> str:
    return (
        f"{ts.strftime('%Y-%m-%dT%H:%M:%SZ')} {action} {protocol} "
        f"{src_ip}:{src_port} {dst_ip}:{dst_port} "
        f"bytes={nbytes} packets={packets} rule={rule}"
    )


def normal_traffic(start: datetime, duration_hours: float, lines: int) -> list[str]:
    """正常业务流量：内网客户端访问内网服务器，偶发外部访问被拒。"""
    out = []
    for _ in range(lines):
        ts = start + timedelta(seconds=random.uniform(0, duration_hours * 3600))
        if random.random() < 0.85:
            src = random.choice(INTERNAL_CLIENTS)
            dst = random.choice(INTERNAL_SERVERS[:3])
            port = random.choice([80, 443])
            action, rule = "ALLOW", ALLOW_RULES[port]
            nbytes = random.randint(500, 500_000)
            packets = max(2, nbytes // random.randint(500, 1500))
        else:
            src = random.choice(EXTERNAL_IPS)
            dst = random.choice(INTERNAL_SERVERS)
            port = random.choice(COMMON_PORTS)
            if port in ALLOW_RULES and random.random() < 0.5:
                action, rule = "ALLOW", ALLOW_RULES[port]
                nbytes = random.randint(500, 200_000)
            else:
                action, rule = "DENY", DENY_RULES.get(port, "BLOCK_DEFAULT")
                nbytes = 0
                packets = random.randint(1, 5)
        out.append(
            fmt_line(ts, action, "tcp", src, random.randint(32768, 61000),
                     dst, port, nbytes, packets, rule)
        )
    return out


def port_scan(start: datetime) -> list[str]:
    """攻击模式 1：203.0.113.77 对 10.0.0.10 全端口扫描。"""
    out = []
    base = start + timedelta(hours=1)
    for i, port in enumerate(range(20, 1024)):
        ts = base + timedelta(seconds=i * 0.5)
        out.append(fmt_line(ts, "DENY", "tcp", "203.0.113.77", 52000 + (i % 1000),
                            "10.0.0.10", port, 0, 1, "BLOCK_PORTSCAN"))
    return out


def ssh_brute_force(start: datetime) -> list[str]:
    """攻击模式 2：198.51.100.42 对多台内网主机 22 端口暴力破解。"""
    out = []
    base = start + timedelta(hours=3)
    for i in range(300):
        ts = base + timedelta(seconds=i * 4)
        dst = random.choice(["10.0.0.11", "10.0.0.12", "10.0.0.20"])
        out.append(fmt_line(ts, "DENY", "tcp", "198.51.100.42", random.randint(40000, 60000),
                            dst, 22, 0, random.randint(3, 6), "BLOCK_SSH_BRUTE"))
    return out


def ddos(start: datetime) -> list[str]:
    """攻击模式 3：僵尸网络对 10.0.0.10:443 的 DDoS。"""
    out = []
    base = start + timedelta(hours=10)
    for i in range(2000):
        ts = base + timedelta(seconds=i * 0.3)
        src = f"45.{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}"
        out.append(fmt_line(ts, "DENY", "udp", src, random.randint(32768, 61000),
                            "10.0.0.10", 443, random.randint(1000, 8000),
                            random.randint(1, 10), "BLOCK_DDOS"))
    return out


def data_exfiltration(start: datetime) -> list[str]:
    """攻击模式 4：失陷内网主机 10.0.1.42 向外部 203.0.113.200:443 外传大量数据。"""
    out = []
    base = start + timedelta(hours=14)
    for i in range(80):
        ts = base + timedelta(minutes=i * 2)
        out.append(fmt_line(ts, "ALLOW", "tcp", "10.0.1.42", 41000 + i,
                            "203.0.113.200", 443, random.randint(20_000_000, 90_000_000),
                            random.randint(15000, 60000), "ALLOW_WEB"))
    return out


def main():
    parser = argparse.ArgumentParser(description="生成合成防火墙日志")
    parser.add_argument("--out", default="data/firewall.log", help="输出文件路径")
    parser.add_argument("--days", type=float, default=1.0, help="日志覆盖的时间跨度（小时）")
    parser.add_argument("--normal-lines", type=int, default=5000, help="正常流量行数")
    args = parser.parse_args()

    start = datetime(2026, 11, 2, 0, 0, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    lines = []
    lines += normal_traffic(start, args.days * 24, args.normal_lines)
    lines += port_scan(start)
    lines += ssh_brute_force(start)
    lines += ddos(start)
    lines += data_exfiltration(start)
    lines.sort()  # 按时间戳全局排序

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    attacks = len(port_scan(start)) + len(ssh_brute_force(start)) + \
        len(ddos(start)) + len(data_exfiltration(start))
    print(f"已生成 {len(lines)} 行日志 → {out_path}")
    print(f"  正常流量: {len(lines) - attacks} 行")
    print(f"  攻击行为: {attacks} 行（端口扫描 / SSH爆破 / DDoS / 数据外传）")


if __name__ == "__main__":
    main()
