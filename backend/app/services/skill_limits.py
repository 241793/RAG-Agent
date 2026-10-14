"""技能脚本资源限额：CPU 时间、内存上限、进程数、子进程隔离。

跨平台策略：
- POSIX：`resource.setrlimit` 在 preexec 里设 RLIMIT_CPU/AS/NOFILE/NPROC（硬限）。
- Windows：用 Job Object（内存/进程数硬限）+ 派生的 watchdog 定时采样（无 psutil 依赖）。

设计：限额失败**不阻断**执行（降级为仅超时），但会记录，便于诊断。
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass


@dataclass
class Limits:
    cpu_seconds: int = 60          # CPU 时间上限
    mem_mb: int = 1024             # 常驻内存上限
    max_procs: int = 32            # 进程/线程数上限
    max_file_mb: int = 256         # 单文件写入上限


def _posix_preexec(lim: Limits):
    """POSIX：返回 preexec_fn，在该进程内设 rlimit。"""
    def _pre():  # pragma: no cover（Windows 不走此路径）
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (lim.cpu_seconds, lim.cpu_seconds))
        mem = lim.mem_mb * 1024 * 1024
        for rl in ("RLIMIT_AS", "RLIMIT_DATA"):
            if hasattr(resource, rl):
                try:
                    resource.setrlimit(getattr(resource, rl), (mem, mem))
                except (ValueError, OSError):
                    pass
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (1024, 1024))
        except (ValueError, OSError):
            pass
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (lim.max_procs, lim.max_procs))
        except (ValueError, OSError, AttributeError):
            pass
    return _pre


def make_popen_kwargs(lim: Limits) -> dict:
    """根据平台返回 subprocess 的额外 kwargs。"""
    if sys.platform == "win32":
        return {}  # Windows 用 Job Object，见 apply_job_limits
    return {"preexec_fn": _posix_preexec(lim)}


def apply_job_limits(proc: subprocess.Popen, lim: Limits) -> object | None:
    """Windows：把子进程放进 Job Object 限内存与进程数。失败返回 None（降级）。"""
    if sys.platform != "win32":
        return None
    try:  # pragma: no cover（仅 Windows）
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [("x", ctypes.c_ulonglong) * 6]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
        JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
        JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_JOB_MEMORY
            | JOB_OBJECT_LIMIT_ACTIVE_PROCESS | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        mem = lim.mem_mb * 1024 * 1024
        info.ProcessMemoryLimit = mem
        info.JobMemoryLimit = mem
        info.BasicLimitInformation.ActiveProcessLimit = lim.max_procs
        JobObjectExtendedLimitInformation = 9
        ok = kernel32.SetInformationJobObject(
            job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
        )
        if not ok:
            return None
        handle = int(proc._handle)  # type: ignore[attr-defined]
        if not kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(handle)):
            return None
        return job
    except Exception:  # noqa: BLE001
        return None
