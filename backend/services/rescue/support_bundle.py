"""Rescue support bundle — 不依赖后端的诊断包打包。

打包范围（``<userData>`` 下）：

- ``diagnostics/manifest.json`` —— 元数据（版本、OS、locale、生成时间、EDR 快照）
- ``diagnostics/crash-journal.jsonl`` —— 崩溃事件日志
- ``diagnostics/last-run.json`` —— 启动时间线/运行状态
- ``diagnostics/compat.json`` —— 兼容档位
- ``diagnostics/rescue-actions.jsonl`` —— 处置动作审计
- ``logs/*.ndjson`` —— Electron NDJSON 日志（最近 N 天）
- ``backend-logs/*.log`` —— 后端 Python 日志（最近 N 天）
- ``sage-emergency.log`` —— 紧急日志
- ``config-summary.json`` —— 端点配置脱敏摘要（无明文 key）
- ``doctor.json`` —— doctor 报告（调用方传入）
- ``crashdumps/`` —— 仅包含文件名与大小（除非 ``include_crashdumps=True``）
- ``README.txt`` —— 隐私说明与反馈指引

隐私：

- 所有 apiKey/token/password 一律脱敏；
- 用户名/主机名默认替换（``--include-hostname`` 显式开启时保留）；
- 不打包 LLM prompt/trace（与现有 ``diagnosticExport`` 职责分离）。
"""
from __future__ import annotations

import json
import logging
import platform
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.services.rescue.config_wizard import redact_settings
from backend.services.rescue.paths import (
    compat_profile_path,
    crash_journal_path,
    diagnostics_dir,
    last_run_path,
    rescue_actions_log,
    resolve_db_path,
    resolve_user_data_dir,
)

logger = logging.getLogger(__name__)

#: 默认打包最近 N 天的日志
DEFAULT_LOG_DAYS = 3


def _read_lines(path: Path, max_bytes: int = 4_000_000) -> str:
    """读取文件（超过 max_bytes 时读尾部最近内容）。"""
    if not path.is_file():
        return ""
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(-max_bytes, 2)
            data = f.read(max_bytes)
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


_SECRET_PATTERNS = (
    (re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?bearer\s+)[^\s\"',}]+"), r"\1***"),
    (re.compile(r"(?i)(api[_-]?key[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+"), r"\1***"),
    (re.compile(r"(?i)(password[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+"), r"\1***"),
    (re.compile(r"(?i)(token[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+"), r"\1***"),
    (re.compile(r"sk-[A-Za-z0-9_-]{8,}"), "sk-***"),
)


def _redact_text(text: str) -> str:
    """对日志文本做常见密钥模式脱敏。"""
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def _recent_files(
    base: Path, pattern: str, days: int, max_bytes_each: int = 4_000_000
) -> List[tuple]:
    if not base.is_dir():
        return []
    cutoff = time.time() - days * 86400
    out: List[tuple] = []
    for f in base.glob(pattern):
        if not f.is_file():
            continue
        try:
            if f.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        out.append((f.relative_to(base), _redact_text(_read_lines(f, max_bytes=max_bytes_each))))
    return out


def _system_info() -> Dict[str, Any]:
    return {
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "hostname": platform.node(),
    }


def _edr_snapshot() -> Dict[str, Any]:
    """轻量 EDR / 安全产品清单（仅信息，不做处置）。

    Win32 环境尝试读取 ``SecurityCenter2`` WMI 类与若干常见服务；
    非 Win32 环境返回空清单。任何查询失败都静默吞掉 —— 这是信息
    收集，不是阻断操作。
    """
    result: Dict[str, Any] = {"av_products": [], "services": [], "errors": []}
    if platform.system() != "Windows":
        return result
    try:
        proc = subprocess.run(
            [
                "wmic",
                "/namespace:\\\\root\\SecurityCenter2",
                "path",
                "AntiVirusProduct",
                "get",
                "displayName,productState",
                "/format:csv",
            ],
            capture_output=True,
            text=True,
            timeout=5, check=False,
        )
        for line in (proc.stdout or "").splitlines():
            if not line.strip() or line.startswith("Node,"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                result["av_products"].append(
                    {"displayName": parts[-2], "productState": parts[-1]}
                )
    except Exception as exc:
        result["errors"].append(f"wmic: {exc}")

    for svc in (
        "360tray",
        "QHSafeTray",
        "VrvProtect",
        "edrservice",
        "TopSecGuard",
        "BaiduAn",
    ):
        try:
            proc = subprocess.run(
                ["sc", "query", svc], capture_output=True, text=True, timeout=3, check=False
            )
            if "STATE" in proc.stdout and "RUNNING" in proc.stdout:
                result["services"].append(svc)
        except Exception as exc:
            result["errors"].append(f"sc {svc}: {exc}")
    return result


def _app_version() -> str:
    try:
        # 打包布局下 package.json 不在 parents[3]，优先用 backend 版本。
        from backend import __version__

        if __version__:
            return str(__version__)
    except Exception:
        pass
    try:
        root = Path(__file__).resolve().parents[3]  # dev: backend/services/rescue → repo root
        pkg_json = root / "package.json"
        if pkg_json.is_file():
            return json.loads(pkg_json.read_text(encoding="utf-8")).get("version", "unknown")
    except Exception:
        pass
    return "unknown"


_README_TEXT = """\
Sage Support Bundle
===================

生成时间: (见 manifest.json 的 generatedAt 字段)

本压缩包用于故障诊断。默认已脱敏：

- apiKey / token / password 替换为 "***"
- 主机名默认隐藏（除非打包时显式 --include-hostname）
- LLM prompt / trace 不在包内（与 "导出诊断包" 工具职责分离）

如需发送给支持人员，请通过可信渠道传递。

包含内容：

- manifest.json        元数据（版本/OS/EDR 清单）
- diagnostics/         崩溃 journal / 启动时间线 / 兼容档位 / 处置审计
- doctor.json          救援工具诊断报告
- logs/                Electron NDJSON 日志（最近 3 天）
- backend-logs/        后端 Python 日志（最近 3 天）
- sage-emergency.log   崩溃事件纯文本兜底日志
- config-summary.json  端点配置脱敏摘要（无明文 key）
- crashdumps/          minidump 索引（默认仅索引，不含内容）

隐私：Sage 不会自动上传任何诊断数据。本包仅供你手动发送给支持人员。
"""


def collect_support_bundle(
    *,
    output_dir: Optional[Path] = None,
    user_data_dir: Optional[Path] = None,
    doctor_report: Optional[Dict[str, Any]] = None,
    log_days: int = DEFAULT_LOG_DAYS,
    include_crashdumps: bool = False,
    include_hostname: bool = False,
) -> Path:
    """生成支持包 zip，返回 zip 文件路径。"""
    base = user_data_dir or resolve_user_data_dir()
    if output_dir is None:
        output_dir = diagnostics_dir(base)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    zip_path = output_dir / f"sage-support-{stamp}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1) manifest
        manifest = {
            "schema": 1,
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "appVersion": _app_version(),
            "system": _system_info(),
            "edr": _edr_snapshot(),
            "includeHostname": include_hostname,
            "includeCrashdumps": include_crashdumps,
        }
        if not include_hostname:
            manifest["system"]["hostname"] = "<redacted>"
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

        # 2) diagnostics JSON 文件（全部读取，不存在则跳过）
        for name, path in (
            ("crash-journal.jsonl", crash_journal_path(base)),
            ("last-run.json", last_run_path(base)),
            ("compat.json", compat_profile_path(base)),
            ("rescue-actions.jsonl", rescue_actions_log(base)),
            ("doctor-last.json", diagnostics_dir(base) / "doctor-last.json"),
        ):
            if path.is_file():
                zf.writestr(f"diagnostics/{name}", _read_lines(path, max_bytes=8_000_000))

        # 3) doctor report
        if doctor_report is not None:
            zf.writestr("doctor.json", json.dumps(doctor_report, ensure_ascii=False, indent=2))

        # 4) 日志文件（最近 N 天）
        logs_dir = base / "logs"
        for rel, content in _recent_files(logs_dir, "*.ndjson", log_days):
            zf.writestr(f"logs/{rel}", content)

        backend_logs_dir = base / "backend-logs"
        if not backend_logs_dir.is_dir():
            # 开发/测试环境可能叫 backend/logs
            backend_logs_dir = base / "backend" / "logs"
        for rel, content in _recent_files(backend_logs_dir, "*.log", log_days):
            zf.writestr(f"backend-logs/{rel}", content)

        # 5) emergency log（完整打包）
        emergency = base / "sage-emergency.log"
        if emergency.is_file():
            zf.writestr(
                "sage-emergency.log",
                _redact_text(_read_lines(emergency, max_bytes=8_000_000)),
            )

        # 6) config summary (脱敏)
        try:
            from backend.data.database import Database
            from backend.data.settings_repo import SettingsRepository

            if user_data_dir is not None:
                # 显式 userData（测试 / 诊断包指定目录）→ 只读该目录下的 DB
                db_path = base / "sage.db"
            else:
                db_path = resolve_db_path()
                if not db_path.is_file():
                    db_path = base / "sage.db"
            if db_path.is_file():
                db = Database(db_path=str(db_path))
                settings = SettingsRepository(db).get_json("app_settings") or {}
                summary = redact_settings(settings)
                zf.writestr(
                    "config-summary.json",
                    json.dumps(summary, ensure_ascii=False, indent=2),
                )
                db.close()
        except Exception as exc:
            zf.writestr(
                "config-summary.json",
                json.dumps({"_error": str(exc)}, ensure_ascii=False, indent=2),
            )

        # 7) crashdumps 索引（或内容）
        crash_dir = base / "Crashpad" / "reports"
        if not crash_dir.is_dir():
            crash_dir = base / "Crashpad"
        if crash_dir.is_dir():
            index: List[Dict[str, Any]] = []
            for f in crash_dir.glob("*.dmp"):
                try:
                    st = f.stat()
                    index.append(
                        {
                            "name": f.name,
                            "size_bytes": st.st_size,
                            "mtime": time.strftime(
                                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)
                            ),
                        }
                    )
                    if include_crashdumps:
                        zf.writestr(f"crashdumps/{f.name}", f.read_bytes())
                except Exception:
                    continue
            if index:
                zf.writestr(
                    "crashdumps/index.json",
                    json.dumps(index, ensure_ascii=False, indent=2),
                )

        # 8) README
        zf.writestr("README.txt", _README_TEXT)

    return zip_path
