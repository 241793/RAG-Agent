"""登录防爆破：IP 限流 + 账号失败锁定。

- IP 维度：令牌桶限流，防单机高频撞库（内存实现，多副本部署需换 Redis）。
- 账号维度：连续失败达阈值锁定一段时间，防针对单账号的慢速爆破。
- 失败计数存进程内（重启清零）；锁定判定同时看内存计数与数据库中的 last_login_at 无关，
  仅内存即可满足单机；多副本下建议配合网关限流。
"""
from __future__ import annotations

import time

from app.core.config import settings
from app.core.errors import RateLimitError
from app.core.rate_limit import rate_limiter

# username(小写) -> [失败次数, 锁定到期 monotonic 时间]
_FAILS: dict[str, list[float]] = {}
_LOCK_UNTIL: dict[str, float] = {}
_MAX_TRACKED = 10000  # 防内存膨胀


def _now() -> float:
    return time.monotonic()


def _prune() -> None:
    if len(_FAILS) > _MAX_TRACKED:
        # 清理已过期的锁定与非锁定且失败次数为 0 的项
        now = _now()
        for k in list(_LOCK_UNTIL.keys()):
            if _LOCK_UNTIL[k] <= now:
                _LOCK_UNTIL.pop(k, None)
        for k in list(_FAILS.keys()):
            if k not in _LOCK_UNTIL and _FAILS[k][0] <= 0:
                _FAILS.pop(k, None)


async def guard_ip(ip: str) -> None:
    """按 IP 限流：超过每分钟上限则拒绝。"""
    rate = settings.login_rate_per_min
    if rate <= 0:
        return
    ok = await rate_limiter.allow(f"login:{ip or 'unknown'}", rate_per_min=max(rate, 1), burst=max(rate, 1))
    if not ok:
        raise RateLimitError("登录尝试过于频繁，请稍后再试")


def ensure_not_locked(username: str) -> None:
    """账号是否处于锁定期。"""
    key = (username or "").strip().lower()
    until = _LOCK_UNTIL.get(key)
    if until and until > _now():
        left = int(until - _now())
        mins = max(1, (left + 59) // 60)
        raise RateLimitError(f"账号因多次登录失败已被临时锁定，请约 {mins} 分钟后重试")


def record_failure(username: str) -> None:
    """记录一次失败；达到阈值则锁定。"""
    key = (username or "").strip().lower()
    if not key:
        return
    _prune()
    rec = _FAILS.setdefault(key, [0, _now()])
    rec[0] += 1
    rec[1] = _now()
    if settings.login_max_failures > 0 and rec[0] >= settings.login_max_failures:
        _LOCK_UNTIL[key] = _now() + settings.login_lock_minutes * 60
        rec[0] = 0  # 锁定后清零，解锁后重新计数


def record_success(username: str) -> None:
    """登录成功：清除失败计数与锁定。"""
    key = (username or "").strip().lower()
    _FAILS.pop(key, None)
    _LOCK_UNTIL.pop(key, None)


def reset_all() -> None:
    """测试用：清空所有状态。"""
    _FAILS.clear()
    _LOCK_UNTIL.clear()
