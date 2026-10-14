"""技能运行时适配层：把「怎么跑一个技能脚本」从散落的 if-else 收敛为可扩展的运行时注册表。

设计要点（勿凭直觉改，均有实测依据）：

1. **Python 沙箱**：旧实现用 `-I -S`，`-S` 会跳过 site-packages 初始化，导致技能脚本
   **无法导入任何第三方库**（实测 `import requests` → ModuleNotFoundError）。改为 `-I`
   （保留 `-I`：隔离 cwd/PYTHONPATH/用户站点），用 `PYTHONNOUSERSITE=1` 挡用户站点，
   保留系统 site-packages 供技能使用。依赖走「共享环境」（与后端同一解释器）。

2. **多运行时**：Python / Node / Shell 各实现 `build_cmd` / `check_deps` / `install_deps`，
   新增运行时只需注册一个实现，不动调用方。

3. **清单可选**：技能包内可选 `skill.yaml`（或 `skill.json`）声明 runtime/entrypoints/
   outputs/permissions。无清单时按扩展名与目录约定推断，行为与历史完全一致。

4. **能力桥接**：脚本经环境变量 `PLATFORM_BASE_URL` / `PLATFORM_SKILL_TOKEN` 回调平台工具，
   避免技能内重复实现 HTTP 且绕过 SSRF 守卫。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

# 可作入口脚本的扩展名 → 运行时
SCRIPT_RUNTIMES: dict[str, str] = {
    ".py": "python", ".pyw": "python",
    ".mjs": "node", ".js": "node", ".cjs": "node",
    ".sh": "sh", ".bash": "sh",
}
# 约定俗成的入口脚本目录（Claud 技能用 scripts/，部分 Node 技能用 tools/）
SCRIPT_DIRS: tuple[str, ...] = ("scripts", "tools")
# 清单文件名（按优先级）
MANIFEST_NAMES: tuple[str, ...] = ("skill.yaml", "skill.yml", "skill.json")

# 各运行时的依赖清单文件
PYTHON_REQ = "requirements.txt"
NODE_MANIFEST = "package.json"
NODE_MODULES = "node_modules"

# 供 UI「查看清单格式」展示的模板（放在包根即生效）
MANIFEST_TEMPLATE = """# 技能清单（可选）。放在技能包根目录，文件名 skill.yaml / skill.yml / skill.json。
# 不写清单时：按扩展名与目录约定自动推断，行为与历史一致。
runtime: python                 # python | node | sh（也可省略，按入口扩展名推断）
entrypoints:
  - name: run                   # 工具名后缀：run_skill_script 的 script 参数用它
    path: scripts/run.py        # 包内相对路径
    args: stdin                 # stdin（默认，JSON 经 stdin）| positional（放 argv）| none
    timeout: 120                # 单次执行超时（秒）
    outputs: ["out/*.pptx"]     # 产物 glob，命中即回传为可下载附件
    description: 生成报告
dependencies:                   # 依赖清单（「安装依赖」按钮据此执行）
  python: requirements.txt      # pip install -r
  node: package.json            # npm ci
permissions:
  platform_tools: [knowledge_retrieval, http_request]   # 允许回调的平台只读工具白名单
"""


# ==================== 清单 ====================
@dataclass
class Entrypoint:
    """一个可执行入口。args 决定参数怎么传：positional / stdin / none。"""
    name: str
    path: str
    runtime: str = ""
    args: str = "stdin"           # stdin | positional | none
    timeout: int | None = None
    outputs: list[str] = field(default_factory=list)   # glob，显式产物
    description: str = ""


@dataclass
class SkillManifest:
    """技能清单（可选）。无清单时全字段为空 → 调用方按约定推断。"""
    runtime: str = ""
    entrypoints: list[Entrypoint] = field(default_factory=list)
    dependencies: dict = field(default_factory=dict)   # {python: requirements.txt, node: package.json}
    permissions: dict = field(default_factory=dict)    # {network: [...], platform_tools: [...]}
    outputs: list[str] = field(default_factory=list)   # 包级默认产物 glob
    raw: dict = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not (self.runtime or self.entrypoints or self.dependencies or self.outputs)


def load_manifest(pack_root: Path) -> SkillManifest:
    """读技能包清单。没有 / 解析失败 → 返回空清单（调用方走约定推断）。"""
    for name in MANIFEST_NAMES:
        f = pack_root / name
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            data = json.loads(text) if f.suffix == ".json" else _parse_yaml(text)
        except Exception:  # noqa: BLE001
            return SkillManifest()
        if not isinstance(data, dict):
            return SkillManifest()
        eps = []
        for e in data.get("entrypoints") or []:
            if isinstance(e, str):  # 简写：直接给路径
                eps.append(Entrypoint(name=Path(e).stem, path=e))
            elif isinstance(e, dict) and e.get("path"):
                eps.append(Entrypoint(
                    name=str(e.get("name") or Path(str(e["path"])).stem),
                    path=str(e["path"]),
                    runtime=str(e.get("runtime") or ""),
                    args=str(e.get("args") or "stdin"),
                    timeout=int(e["timeout"]) if e.get("timeout") else None,
                    outputs=[str(x) for x in (e.get("outputs") or [])],
                    description=str(e.get("description") or ""),
                ))
        return SkillManifest(
            runtime=str(data.get("runtime") or ""),
            entrypoints=eps,
            dependencies=dict(data.get("dependencies") or {}),
            permissions=dict(data.get("permissions") or {}),
            outputs=[str(x) for x in (data.get("outputs") or [])],
            raw=data,
        )
    return SkillManifest()


def _parse_yaml(text: str) -> dict:
    try:
        import yaml

        return yaml.safe_load(text) or {}
    except Exception:  # noqa: BLE001
        return {}


# ==================== 运行时 ====================
@dataclass
class RunContext:
    """一次脚本执行所需的全部上下文。"""
    root: Path
    script: Path
    args: dict
    extra_args: list[str]
    timeout: int
    env_extra: dict = field(default_factory=dict)   # 平台注入（桥接令牌等）


class Runtime:
    """运行时基类。子类实现 build_cmd / check_deps / install_deps。"""
    name = ""

    def build_cmd(self, ctx: RunContext) -> list[str]:
        raise NotImplementedError

    def check_deps(self, root: Path) -> tuple[bool, str]:
        """依赖是否就绪。返回 (ok, 说明)。"""
        return True, ""

    def install_hint(self) -> str:
        return ""

    def extra_env(self) -> dict:
        """该运行时需要的额外环境变量。"""
        return {}


class PythonRuntime(Runtime):
    name = "python"

    def build_cmd(self, ctx: RunContext) -> list[str]:
        # 关键：只加 -I（不用 -S）。-S 会屏蔽 site-packages → 技能无法用第三方库。
        return [sys.executable, "-I", str(ctx.script), *ctx.extra_args]

    def check_deps(self, root: Path) -> tuple[bool, str]:
        req = root / PYTHON_REQ
        if req.is_file():
            # 共享环境：这里不强制校验（装了什么用什么），仅在有清单时提示可装
            return True, ""
        return True, ""

    def install_hint(self) -> str:
        return "可点击「安装依赖」执行 pip install -r requirements.txt"

    def extra_env(self) -> dict:
        # 保留系统 site-packages（技能可用第三方库），但挡用户站点与字节码写入
        return {"PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}


class NodeRuntime(Runtime):
    name = "node"

    def build_cmd(self, ctx: RunContext) -> list[str]:
        node = shutil.which("node") or shutil.which("node.exe")
        if not node:
            raise RuntimeError("未检测到 Node.js（node 不在 PATH）")
        return [node, str(ctx.script), *ctx.extra_args]

    def check_deps(self, root: Path) -> tuple[bool, str]:
        if (root / NODE_MANIFEST).is_file() and not (root / NODE_MODULES).is_dir():
            return False, "该 Node 技能尚未安装依赖（npm ci）"
        return True, ""

    def install_hint(self) -> str:
        return "可点击「安装依赖」执行 npm ci"


class ShellRuntime(Runtime):
    name = "sh"

    def build_cmd(self, ctx: RunContext) -> list[str]:
        bash = shutil.which("bash") or shutil.which("sh")
        if not bash:
            raise RuntimeError("未检测到 shell（bash/sh）")
        return [bash, str(ctx.script), *ctx.extra_args]


RUNTIME_REGISTRY: dict[str, Runtime] = {
    r.name: r for r in (PythonRuntime(), NodeRuntime(), ShellRuntime())
}


def runtime_of(script_path: str, *, declared: str = "") -> str:
    """确定脚本运行时：清单声明优先，否则按扩展名。"""
    if declared and declared in RUNTIME_REGISTRY:
        return declared
    return SCRIPT_RUNTIMES.get(Path(script_path).suffix.lower(), "python")


def get_runtime(name: str) -> Runtime | None:
    return RUNTIME_REGISTRY.get(name)


# ==================== 入口发现 ====================
def scan_entry_scripts(pack_root: Path, *, manifest: SkillManifest | None = None) -> list[dict]:
    """扫描包内可作为入口的脚本。

    - 有清单：以清单 entrypoints 为准（含 runtime/args/outputs）。
    - 无清单：扫 SCRIPT_DIRS 下的**直接子文件**，按扩展名推断（历史行为）。
    返回 [{name, path, description, runtime, args, outputs}]。
    """
    if manifest and manifest.entrypoints:
        out = []
        for e in manifest.entrypoints:
            out.append({
                "name": e.name, "path": e.path, "description": e.description,
                "runtime": e.runtime or runtime_of(e.path, declared=manifest.runtime),
                "args": e.args, "outputs": e.outputs,
            })
        return out

    out: list[dict] = []
    seen: set[str] = set()
    for d in SCRIPT_DIRS:
        base = pack_root / d
        if not base.is_dir():
            continue
        for p in sorted(base.iterdir()):
            if not p.is_file():
                continue
            rt = SCRIPT_RUNTIMES.get(p.suffix.lower())
            if not rt:
                continue
            name = p.stem
            if name in seen:
                continue
            seen.add(name)
            out.append({"name": name, "path": f"{d}/{p.name}", "description": "",
                        "runtime": rt, "args": "stdin", "outputs": []})
    return out


def entry_for(entry_scripts: list[dict], name: str) -> dict | None:
    for s in entry_scripts or []:
        if s.get("name") == name:
            return s
    return None


def has_node_deps(pack_root: Path) -> bool:
    return (pack_root / NODE_MANIFEST).is_file() and not (pack_root / NODE_MODULES).is_dir()


def has_python_deps(pack_root: Path) -> bool:
    return (pack_root / PYTHON_REQ).is_file()


# ==================== 环境变量白名单 ====================
# 只把这些「运行必需」的变量传给技能子进程，其余（含密钥/DB连接串/后端配置）一律不传。
# 目的：技能脚本不应读到后端的 SECRET_KEY、DATABASE_URL、模型 API Key 等。
_ENV_ALLOW = (
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
    "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
    "LANG", "LC_ALL", "LC_CTYPE", "TZ",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS",
    # 运行时定位
    "PYTHONPATH", "PYTHONHOME", "PYTHONIOENCODING", "VIRTUAL_ENV",
    "NODE_PATH", "NODE_OPTIONS",
)
# 这些变量**始终丢弃**（即使名字像白名单，也防误配泄漏）
_ENV_DENY = (
    "SECRET_KEY", "DATABASE_URL", "OPENAI_API_KEY", "ANTHROPI_AUTH_TOKEN",
    "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY", "AWS_ACCESS_KEY_ID",
)


def build_child_env(*, runtime: Runtime, base: dict | None = None,
                    extra: dict | None = None) -> dict:
    """构造传给技能子进程的环境：白名单 + 运行时必需 + 显式注入项。

    base 缺省取 os.environ；只挑白名单内的键，并强制剔除 _ENV_DENY。
    """
    src = base if base is not None else os.environ
    env = {k: v for k, v in src.items() if k in _ENV_ALLOW and k not in _ENV_DENY}
    env.update(runtime.extra_env())
    env.update(extra or {})
    return env
