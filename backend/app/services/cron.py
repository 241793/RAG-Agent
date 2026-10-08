"""极简 cron 解析（零依赖）：支持 分 时 日 月 周 五字段子集。

支持：通配 `*`、具体值 `5`、列表 `1,3,5`、步长 `*/15`、范围 `1-5`。
用于「可视化选时间」生成的表达式，非完整 cron。
"""
from __future__ import annotations

from datetime import datetime, timedelta

_FIELDS = [("minute", 0, 59), ("hour", 0, 23), ("dom", 1, 31), ("month", 1, 12), ("dow", 0, 6)]


def parse_cron(expr: str) -> list[set[int]]:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError("cron 表达式必须为 5 段：分 时 日 月 周")
    out: list[set[int]] = []
    for (name, lo, hi), token in zip(_FIELDS, parts):
        out.append(_parse_field(token, lo, hi))
    return out


def _parse_field(token: str, lo: int, hi: int) -> set[int]:
    vals: set[int] = set()
    for part in token.split(","):
        part = part.strip()
        if part == "*":
            vals.update(range(lo, hi + 1))
        elif "/" in part:
            base, step = part.split("/", 1)
            step = int(step)
            start = lo if base == "*" else int(base)
            vals.update(range(start, hi + 1, step))
        elif "-" in part:
            a, b = part.split("-", 1)
            vals.update(range(int(a), int(b) + 1))
        else:
            vals.add(int(part))
    return {v for v in vals if lo <= v <= hi}


def _zone(tz_name: str | None):
    """解析时区名（如 Asia/Shanghai）为 tzinfo；无则用本地时区。"""
    if not tz_name:
        return None
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001
        return None


def next_run(expr: str, after: datetime | None = None, tz_name: str | None = None) -> datetime:
    """返回 after 之后第一个匹配的时间（逐分钟推进，上限 366 天）。

    tz_name 指定任务时区（如 "Asia/Shanghai"）；不传则用服务器本地时区。
    返回值携带对应 tzinfo（naive 输入在本地时区解释）。
    """
    minute, hour, dom, month, dow = parse_cron(expr)
    tz = _zone(tz_name)
    if after is None:
        after = datetime.now(tz) if tz else datetime.now()
    elif tz is not None and after.tzinfo is None:
        local = _zone(None)
        after = after.replace(tzinfo=local).astimezone(tz) if local else after.replace(tzinfo=tz)
    elif tz is not None:
        after = after.astimezone(tz)
    cur = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = cur + timedelta(days=366)
    while cur < limit:
        if (cur.minute in minute and cur.hour in hour and cur.month in month
                and cur.day in dom and (cur.weekday() + 1) % 7 in dow):
            return cur
        cur += timedelta(minutes=1)
    raise ValueError("cron 表达式在一年内无匹配时间")
