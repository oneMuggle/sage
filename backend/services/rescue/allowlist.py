"""给 IT 的放行清单生成（§6.5.2）。

不修改任何安全软件配置；只生成路径 / 进程链 / 端口 / 哈希清单，
由单位 IT 管理员按制度评估放行。
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.services.rescue.paths import diagnostics_dir, resolve_user_data_dir


def _sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def build_allowlist(
    *,
    install_dir: Optional[Path] = None,
    user_data_dir: Optional[Path] = None,
    port: int = 8765,
) -> Dict[str, Any]:
    """构造放行清单数据（不写文件）。"""
    base = user_data_dir or resolve_user_data_dir()
    install = Path(install_dir) if install_dir else Path(sys.executable).parent

    candidates = [
        install / "Sage.exe",
        install / "resources" / "python" / "python.exe",
        install / "resources" / "python" / "python",
    ]
    executables: List[Dict[str, Any]] = []
    for path in candidates:
        if path.is_file():
            executables.append(
                {
                    "path": str(path),
                    "sha256": _sha256(path),
                    "size_bytes": path.stat().st_size,
                }
            )

    return {
        "schema": 1,
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": "请由单位 IT 管理员按制度评估放行；本工具不修改任何安全软件配置。",
        "executables": executables,
        "processChain": [
            "Sage.exe",
            "Sage.exe → resources\\python\\python.exe (backend.main)",
            "Sage.exe → renderer / GPU / utility 子进程（Chromium）",
        ],
        "directories": [
            str(install),
            str(base),
            str(base / "logs"),
            str(base / "backups"),
        ],
        "ports": [
            {"address": "127.0.0.1", "port": port, "service": "FastAPI backend (仅本机)"},
        ],
        "dataPaths": {
            "userData": str(base),
            "db": str(base / "sage.db"),
            "logs": str(base / "logs"),
        },
    }


def _render_markdown(data: Dict[str, Any]) -> str:
    lines = [
        "# Sage 放行清单（供 IT 管理员参考）",
        "",
        f"生成时间: {data['generatedAt']}",
        "",
        f"> {data['note']}",
        "",
        "## 可执行文件（含 SHA-256）",
        "",
    ]
    if data["executables"]:
        for exe in data["executables"]:
            lines.append(f"- `{exe['path']}`")
            lines.append(f"  - SHA-256: `{exe['sha256'] or 'N/A'}`")
            lines.append(f"  - 大小: {exe['size_bytes']} 字节")
    else:
        lines.append("（未在预期路径找到可执行文件；请手动确认安装目录）")
    lines += ["", "## 进程链", ""]
    lines += [f"- {item}" for item in data["processChain"]]
    lines += ["", "## 目录", ""]
    lines += [f"- `{d}`" for d in data["directories"]]
    lines += ["", "## 本机回环端口", ""]
    for p in data["ports"]:
        lines.append(f"- `{p['address']}:{p['port']}` — {p['service']}")
    lines += [
        "",
        "## 说明",
        "",
        "- 本清单只描述 Sage 正常运行所需的最小权限面。",
        "- 是否放行、以何种方式放行，由单位 IT 管理员按制度决定。",
        "- 本工具不修改、不关闭、不绕过任何安全软件配置。",
        "",
    ]
    return "\n".join(lines)


def write_allowlist(
    output_path: Optional[Path] = None,
    *,
    install_dir: Optional[Path] = None,
    user_data_dir: Optional[Path] = None,
) -> Path:
    """生成 ``allowlist.md`` + ``allowlist.json``，返回 markdown 路径。"""
    base = user_data_dir or resolve_user_data_dir()
    data = build_allowlist(install_dir=install_dir, user_data_dir=base)
    if output_path is None:
        out_dir = diagnostics_dir(base)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
        md_path = out_dir / f"sage-allowlist-{stamp}.md"
    else:
        md_path = Path(output_path)
        md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path = md_path.with_suffix(".json")
    md_path.write_text(_render_markdown(data), encoding="utf-8")
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return md_path
