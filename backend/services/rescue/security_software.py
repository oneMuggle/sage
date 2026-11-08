"""遗留管控软件识别与处置。

适用场景：内网管控软件为 2014 年前后开发的遗留产品，厂商已停止维护，
IT 无法协助放行。本模块提供**用户显式确认后**的主动处置能力：

- 识别：服务 / 进程 / 注入模块（仅 Windows；非 Windows 返回空清单）
- 处置：临时结束进程 / 停止服务 / 禁用服务 / 禁用启动项 / 修改白名单配置
- 回滚：处置前备份服务状态，``restore_all`` 一键恢复

安全边界：

- 所有处置动作默认 ``confirm=False``（dry-run）；显式 ``confirm=True`` 才执行；
- 每个动作前把服务原始状态写入 ``<userData>/backups/security/*.json``；
- 不提供永久删除/卸载；不修改内核驱动（高风险动作单独评审后再加）；
- 非 Windows 平台所有动作返回 ``unsupported``。

实现方式：封装 ``sc`` / ``taskkill`` / ``reg`` 子进程，所有命令通过可注入的
``_run`` 执行，便于测试与审计。
"""
from __future__ import annotations

import json
import logging
import platform
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from backend.services.rescue.paths import security_backups_dir

logger = logging.getLogger(__name__)


#: 常见 2014 年代遗留管控软件的服务/进程特征。
#: 仅用于**识别与提示**，不自动处置。
KNOWN_SERVICE_PATTERNS: Dict[str, str] = {
    "360tray": "360 天擎 / 360 安全卫士",
    "qhsafetray": "360 安全卫士",
    "vrvprotect": "北信源 VRV",
    "edrservice": "EDR 终端服务",
    "topsecguard": "天融信终端管控",
    "baiduan": "百度杀毒",
    "sangfor": "深信服 EDR",
    "qianxin": "奇安信终端管控",
    "huorong": "火绒安全",
}

KNOWN_PROCESS_PATTERNS: Dict[str, str] = {
    "360tray.exe": "360 天擎 / 360 安全卫士",
    "360Safe.exe": "360 安全卫士",
    "VrvProtect.exe": "北信源 VRV",
    "TopSecGuard.exe": "天融信终端管控",
    "HipsTray.exe": "火绒安全",
}


@dataclass
class SecurityProduct:
    """检测到的一个安全/管控产品组件。"""

    name: str
    kind: str  # service / process / driver
    target: str  # 服务名或进程名
    status: str  # RUNNING / STOPPED / PRESENT / UNKNOWN
    raw: Optional[str] = None


@dataclass
class ActionResult:
    """处置动作结果。"""

    action: str
    target: str
    ok: bool
    message: str
    dry_run: bool = False
    backup_path: Optional[str] = None
    rollback: Optional[str] = None
    output: str = ""


def _is_windows() -> bool:
    return platform.system() == "Windows"


_PROCESS_RE = re.compile(r"^[A-Za-z0-9._-]+\.exe$")
_SERVICE_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _valid_process_name(name: str) -> bool:
    return bool(_PROCESS_RE.match(name))


def _valid_service_name(name: str) -> bool:
    return bool(_SERVICE_RE.match(name))


def _run(cmd: Sequence[str], timeout: int = 10) -> subprocess.CompletedProcess:
    """执行外部命令。测试中可 monkeypatch。"""
    kwargs: Dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "timeout": timeout,
        "check": False,
    }
    if platform.system() == "Windows":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(list(cmd), **kwargs)  # noqa: PLW1510 — check 在 kwargs 中


# ============================================================
# 识别
# ============================================================


def _service_status(name: str) -> str:
    """查询服务状态；不存在返回 ``"MISSING"``。"""
    try:
        proc = _run(["sc", "query", name], timeout=5)
    except Exception:
        return "UNKNOWN"
    text = (proc.stdout or "") + (proc.stderr or "")
    if "FAILED 1060" in text or "does not exist" in text:
        return "MISSING"
    if "RUNNING" in text:
        return "RUNNING"
    if "STOPPED" in text or "STOP_PENDING" in text:
        return "STOPPED"
    return "PRESENT"


def _process_exists(name: str) -> bool:
    try:
        proc = _run(["tasklist", "/FI", f"IMAGENAME eq {name}"], timeout=5)
    except Exception:
        return False
    return name.lower() in (proc.stdout or "").lower()


def detect_products() -> List[SecurityProduct]:
    """检测本机已知遗留管控软件组件。

    非 Windows 平台返回空列表。任何查询失败都静默跳过（fail-open）。
    """
    if not _is_windows():
        return []
    found: List[SecurityProduct] = []
    for service, label in KNOWN_SERVICE_PATTERNS.items():
        status = _service_status(service)
        if status != "MISSING":
            found.append(
                SecurityProduct(
                    name=label,
                    kind="service",
                    target=service,
                    status=status,
                )
            )
    for proc_name, label in KNOWN_PROCESS_PATTERNS.items():
        if _process_exists(proc_name):
            found.append(
                SecurityProduct(
                    name=label,
                    kind="process",
                    target=proc_name,
                    status="PRESENT",
                )
            )
    return found


def detect_injected_modules(process_name: str = "Sage.exe") -> List[str]:
    """列出注入到目标进程的非系统 DLL（Windows only，尽力而为）。"""
    if not _is_windows():
        return []
    try:
        proc = _run(["tasklist", "/m", "/FI", f"IMAGENAME eq {process_name}"], timeout=5)
    except Exception:
        return []
    modules: List[str] = []
    for raw_line in (proc.stdout or "").splitlines():
        line = raw_line.strip()
        if not line or "映像名称" in line or "Image Name" in line or "=" in line:
            continue
        parts = line.split()
        if len(parts) >= 3:
            modules.extend(parts[2:])
    return [
        m
        for m in modules
        if not m.lower().startswith(("kernel", "ntdll", "user32", "gdi32", "msvcrt"))
    ]


# ============================================================
# 备份 / 回滚
# ============================================================


def _service_config(name: str) -> str:
    try:
        proc = _run(["sc", "qc", name], timeout=5)
        return (proc.stdout or "") + (proc.stderr or "")
    except Exception:
        return ""


def _parse_start_type(config_text: str) -> Optional[str]:
    """从 ``sc qc`` 输出解析可用于 ``sc config start=`` 的启动类型。

    ``sc qc`` 输出形如 ``START_TYPE : 2   AUTO_START``；数字 0-4 需映射为
    ``boot/system/auto/demand/disabled``，``2 + DELAYED`` → ``delayed-auto``。
    直接回填数字会让 ``sc config <svc> start= 2`` 失败，导致无法回滚。
    """
    numeric_map = {
        "0": "boot",
        "1": "system",
        "2": "auto",
        "3": "demand",
        "4": "disabled",
    }
    symbolic_map = {
        "BOOT_START": "boot",
        "SYSTEM_START": "system",
        "AUTO_START": "auto",
        "DEMAND_START": "demand",
        "DISABLED": "disabled",
    }
    for line in config_text.splitlines():
        if "START_TYPE" not in line:
            continue
        after = line.split(":", 1)[1].strip() if ":" in line else ""
        tokens = after.split()
        if not tokens:
            continue
        token = tokens[0]
        if token in numeric_map:
            if token == "2" and "DELAYED" in after.upper():
                return "delayed-auto"
            return numeric_map[token]
        return symbolic_map.get(token.upper(), "demand")
    return None


def backup_service_state(
    name: str,
    *,
    user_data_dir: Optional[Path] = None,
) -> Optional[Path]:
    """备份服务原始配置到 ``backups/security/<name>-<ts>.json``。"""
    if not _is_windows():
        return None
    if not _valid_service_name(name):
        return None
    config_text = _service_config(name)
    if not config_text:
        return None
    backup_dir = security_backups_dir(user_data_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    path = backup_dir / f"service-{name}-{stamp}.json"
    payload = {
        "kind": "service",
        "name": name,
        "startType": _parse_start_type(config_text),
        "wasRunning": _service_status(name) == "RUNNING",
        "config": config_text,
        "backedUpAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ============================================================
# 处置动作
# ============================================================


def end_process(
    process_name: str,
    *,
    confirm: bool = False,
    user_data_dir: Optional[Path] = None,
) -> ActionResult:
    """结束进程（先优雅退出，失败再强杀）。"""
    if not _is_windows():
        return ActionResult("end_process", process_name, False, "unsupported: 仅 Windows 支持")
    if not _valid_process_name(process_name):
        return ActionResult(
            "end_process",
            process_name,
            False,
            "非法进程名：只允许字母/数字/._- 且必须以 .exe 结尾（禁止通配符）",
        )
    if not confirm:
        return ActionResult("end_process", process_name, False, "未确认：需要 confirm=True", dry_run=True)
    try:
        proc = _run(["taskkill", "/IM", process_name, "/T"], timeout=10)
        output = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            # 优雅退出失败 → 强杀（仍可重启恢复）
            proc = _run(["taskkill", "/F", "/IM", process_name, "/T"], timeout=10)
            output += (proc.stdout or "") + (proc.stderr or "")
        ok = proc.returncode == 0
        return ActionResult(
            "end_process",
            process_name,
            ok,
            "已结束进程" if ok else "结束进程失败",
            output=output,
            rollback="重启应用/系统后进程会自动恢复",
        )
    except Exception as exc:
        return ActionResult("end_process", process_name, False, f"执行失败: {exc}")


def stop_service(
    service_name: str,
    *,
    confirm: bool = False,
    user_data_dir: Optional[Path] = None,
) -> ActionResult:
    """停止服务（可恢复）。"""
    if not _is_windows():
        return ActionResult("stop_service", service_name, False, "unsupported: 仅 Windows 支持")
    if not _valid_service_name(service_name):
        return ActionResult("stop_service", service_name, False, "非法服务名")
    if not confirm:
        return ActionResult("stop_service", service_name, False, "未确认：需要 confirm=True", dry_run=True)
    backup = backup_service_state(service_name, user_data_dir=user_data_dir)
    try:
        proc = _run(["sc", "stop", service_name], timeout=15)
        output = (proc.stdout or "") + (proc.stderr or "")
        ok = "FAILED" not in output
        return ActionResult(
            "stop_service",
            service_name,
            ok,
            "服务已停止" if ok else "停止服务失败",
            backup_path=str(backup) if backup else None,
            rollback=f"sc start {service_name}",
            output=output,
        )
    except Exception as exc:
        return ActionResult("stop_service", service_name, False, f"执行失败: {exc}")


def disable_service(
    service_name: str,
    *,
    confirm: bool = False,
    user_data_dir: Optional[Path] = None,
) -> ActionResult:
    """禁用服务（重启后仍禁用；先备份原始启动类型）。"""
    if not _is_windows():
        return ActionResult("disable_service", service_name, False, "unsupported: 仅 Windows 支持")
    if not _valid_service_name(service_name):
        return ActionResult("disable_service", service_name, False, "非法服务名")
    if not confirm:
        return ActionResult("disable_service", service_name, False, "未确认：需要 confirm=True", dry_run=True)
    backup = backup_service_state(service_name, user_data_dir=user_data_dir)
    if backup is None:
        return ActionResult(
            "disable_service",
            service_name,
            False,
            "无法备份服务原始状态，已中止禁用（避免不可逆变更）",
        )
    original = None
    if backup and backup.is_file():
        try:
            original = json.loads(backup.read_text(encoding="utf-8")).get("startType")
        except Exception:
            original = None
    try:
        proc = _run(["sc", "config", service_name, "start=", "disabled"], timeout=10)
        output = (proc.stdout or "") + (proc.stderr or "")
        # 用退出码判定，避免依赖本地化输出（中文 Windows 的 sc 输出是“成功”）。
        ok = proc.returncode == 0 and "FAILED" not in output
        return ActionResult(
            "disable_service",
            service_name,
            ok,
            "服务已禁用" if ok else "禁用服务失败",
            backup_path=str(backup) if backup else None,
            rollback=f"sc config {service_name} start= {original or 'demand'}",
            output=output,
        )
    except Exception as exc:
        return ActionResult("disable_service", service_name, False, f"执行失败: {exc}")


def enable_service(
    service_name: str,
    *,
    start_type: str = "demand",
    confirm: bool = False,
) -> ActionResult:
    """恢复服务启动类型（``sc config <name> start= <start_type>``）。"""
    if not _is_windows():
        return ActionResult("enable_service", service_name, False, "unsupported: 仅 Windows 支持")
    if not _valid_service_name(service_name):
        return ActionResult("enable_service", service_name, False, "非法服务名")
    if not confirm:
        return ActionResult("enable_service", service_name, False, "未确认：需要 confirm=True", dry_run=True)
    try:
        proc = _run(["sc", "config", service_name, "start=", start_type], timeout=10)
        output = (proc.stdout or "") + (proc.stderr or "")
        ok = "FAILED" not in output
        return ActionResult(
            "enable_service",
            service_name,
            ok,
            f"服务启动类型已恢复为 {start_type}" if ok else "恢复失败",
            output=output,
        )
    except Exception as exc:
        return ActionResult("enable_service", service_name, False, f"执行失败: {exc}")


def restore_all(*, user_data_dir: Optional[Path] = None) -> List[ActionResult]:
    """从 ``backups/security/*.json`` 恢复所有备份过的服务启动类型。"""
    results: List[ActionResult] = []
    backup_dir = security_backups_dir(user_data_dir)
    if not backup_dir.is_dir():
        return results
    for f in sorted(backup_dir.glob("service-*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        name = data.get("name")
        start_type = data.get("startType") or "demand"
        if not isinstance(name, str):
            continue
        results.append(enable_service(name, start_type=start_type, confirm=True))
        if data.get("wasRunning"):
            try:
                proc = _run(["sc", "start", name], timeout=15)
                output = (proc.stdout or "") + (proc.stderr or "")
                results.append(
                    ActionResult(
                        "start_service",
                        name,
                        proc.returncode == 0 and "FAILED" not in output,
                        "服务已重新启动" if proc.returncode == 0 else "服务启动失败",
                        output=output,
                    )
                )
            except Exception as exc:
                results.append(
                    ActionResult("start_service", name, False, f"执行失败: {exc}")
                )
    return results


def plan_bypass() -> Dict[str, Any]:
    """生成"绕过启动链"建议（不执行文件操作）。

    常见老产品按路径前缀/进程文件名匹配；建议：

    - 用 ``explorer.exe`` 作为父进程启动 Sage（避免 Electron 直接父子链）；
    - 把 Sage 安装副本放到非受管目录（如 ``%LOCALAPPDATA%\\SageAlt``）；
    - 延迟启动（先启动 Sage，再让管控软件加载 hook）。

    返回结构化建议，由用户/UI 决定是否执行。
    """
    return {
        "modes": [
            {
                "id": "parent",
                "title": "更换父进程启动",
                "description": "通过 explorer.exe 启动 Sage，避免‘父进程为 electron.exe’类规则",
                "risk": "低",
            },
            {
                "id": "dir",
                "title": "复制到非受管目录",
                "description": "将安装目录复制到 %LOCALAPPDATA%\\SageAlt 后启动（需重新指向 userData）",
                "risk": "中",
            },
            {
                "id": "delay",
                "title": "延迟启动",
                "description": "先启动 Sage，再等待管控软件注入；仅对启动期 hook 有效",
                "risk": "低",
            },
        ],
        "unsupported": ["内核驱动卸载（高风险，需单独评审）", "永久删除/卸载管控软件"],
    }
