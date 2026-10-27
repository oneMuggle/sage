# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容，保留 typing 注解
"""全局规则 (~/.sage/SAGE.md) 读写路由 —— P0（G1）。

后端 ``backend/chat/project_context.py:_user_level_entries`` 已把
``~/.sage/SAGE.md`` 作为 L1 全局规则层注入 system prompt。本模块提供
设置页所需的读写入口，路径与注入侧**保持同一计算方式**，不接受客户端传参。

安全约束：
- 路径硬编码为 ``Path.home() / ".sage" / "SAGE.md"``；
- 写入前经 ``get_scanner().scan(level="all")`` 扫描，拦截提示注入与敏感信息。
  刻意不用 ``scan_write`` 的 strict 档：其持久化攻击模式（"always respond"、
  "remember to always"）正是全局规则的正常写法，用于用户主动编写的规则会误杀；
- 目标文件若是符号链接 → 拒绝写入（防止覆写 ``~/.ssh/id_rsa`` 等）；
- 同目录 tmp + ``os.replace`` 原子写，避免半写坏文件。
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.memory.safety import get_scanner

logger = logging.getLogger(__name__)

router = APIRouter()

# 与 backend/chat/project_context.py:PER_FILE_CHAR_CAP 保持一致。此处不 import
# 该模块，避免 settings 路由连带加载 backend.data 的 ORM 模型。
PER_FILE_CHAR_CAP = 8_000

# 单次请求体上限：全局规则是 prompt 片段，64KB 已远超实际需要。
MAX_CONTENT_BYTES = 64 * 1024


def _global_rules_path() -> Path:
    """与 ``project_context._user_level_entries`` 保持同一路径，勿加环境变量覆盖。"""
    return Path.home() / ".sage" / "SAGE.md"


class GlobalRulesUpdateRequest(BaseModel):
    content: str = ""


_TEMPLATES: List[Dict[str, str]] = [
    {
        "id": "zh-output",
        "name": "中文输出规范",
        "content": (
            "# 输出语言\n\n"
            "- 始终使用简体中文回答，专有名词、代码、命令行保持原文。\n"
            "- 代码注释与提交信息可使用英文。\n"
        ),
    },
    {
        "id": "code-style",
        "name": "代码风格",
        "content": (
            "# 代码风格\n\n"
            "- 函数保持短小，单个函数不超过 50 行。\n"
            "- 优先使用早返回，避免超过 4 层的嵌套。\n"
            "- 不做未要求的重构，改动范围与任务匹配。\n"
        ),
    },
    {
        "id": "safety",
        "name": "安全规范",
        "content": (
            "# 安全规范\n\n"
            "- 不在代码或配置中硬编码密钥、密码、令牌。\n"
            "- 删除文件、重置分支、推送远端等操作前先确认。\n"
            "- 外部输入一律视为不可信，在系统边界处校验。\n"
        ),
    },
]


def _build_state(content: str, path: Path, exists: bool, read_error: str = "") -> Dict:
    size = len(content.encode("utf-8"))
    mtime = None
    symlink = False
    if exists:
        try:
            st = path.stat()
            size = st.st_size
            mtime = int(st.st_mtime)
        except OSError:
            pass
        symlink = path.is_symlink()
    state: Dict = {
        "content": content,
        "path": str(path),
        "exists": exists,
        "size": size,
        "mtime": mtime,
        "truncated": size > PER_FILE_CHAR_CAP,
        "char_limit": PER_FILE_CHAR_CAP,
        "symlink": symlink,
    }
    if read_error:
        state["read_error"] = read_error
    return state


def _read_global_rules(path: Path) -> Dict:
    if not path.is_file():
        return _build_state("", path, exists=False)
    try:
        # 与注入侧一致：读取 realpath 内容（符号链接仅标记，不阻断读取）。
        resolved = Path(os.path.realpath(str(path)))
        content = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("[GLOBAL-RULES] read failed: %s", exc)
        return _build_state("", path, exists=False, read_error=str(exc))
    return _build_state(content, path, exists=True)


@router.get("/settings/global-rules")
def get_global_rules() -> Dict:
    """读取 ~/.sage/SAGE.md 全文与状态；不存在返回空内容，不抛 404。"""
    return _read_global_rules(_global_rules_path())


@router.put("/settings/global-rules")
def update_global_rules(req: GlobalRulesUpdateRequest) -> Dict:
    """原子写入全局规则，写入前做安全扫描（level="all"，非 strict 档）。"""
    content = req.content
    if not content.strip():
        raise HTTPException(
            status_code=422,
            detail={"type": "empty_content", "message": "全局规则不能为空"},
        )
    if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"type": "content_too_large", "message": "内容超过 64KB 上限"},
        )

    scan = get_scanner().scan(content, level="all")
    if scan.blocked:
        logger.warning("[GLOBAL-RULES] write blocked: %s", scan.reason)
        raise HTTPException(
            status_code=422,
            detail={
                "type": "unsafe_content",
                "message": "内容未通过安全扫描",
                "reason": scan.reason,
                "threat_level": scan.threat_level,
            },
        )

    path = _global_rules_path()
    if path.is_symlink():
        raise HTTPException(
            status_code=422,
            detail={"type": "symlink_target", "message": "目标文件是符号链接，拒绝写入"},
        )

    try:
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)
        # `mkdir(mode=...)` 只作用于新创建的目录；若 `~/.sage` 已存在（比如先前
        # 由 project_context 在首次聊天时创建），权限可能过宽。显式 chmod 收紧。
        # 部分文件系统（FAT、网络挂载）不支持 chmod；不阻断写入。
        with contextlib.suppress(OSError):
            parent.chmod(0o700)
        fd, tmp_name = tempfile.mkstemp(dir=str(parent), prefix=".SAGE.md.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(content)
            # os.replace 替换的是 SAGE.md 这个目录项本身：即使检查后被换成
            # 符号链接，也只会覆盖链接而不触碰其指向的文件。
            tmp_path = Path(tmp_name)
            tmp_path.replace(path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise
    except OSError as exc:
        logger.error("[GLOBAL-RULES] write failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={"type": "write_failed", "message": "写入全局规则失败"},
        ) from exc

    logger.info("[GLOBAL-RULES] saved %d bytes", len(content.encode("utf-8")))
    return _read_global_rules(path)


@router.delete("/settings/global-rules")
def delete_global_rules() -> Dict:
    """删除全局规则文件；不存在时幂等返回。"""
    path = _global_rules_path()
    try:
        path.unlink()
    except FileNotFoundError:
        return {"status": "ok", "deleted": False}
    except OSError as exc:
        logger.error("[GLOBAL-RULES] delete failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail={"type": "delete_failed", "message": "删除全局规则失败"},
        ) from exc
    logger.info("[GLOBAL-RULES] deleted")
    return {"status": "ok", "deleted": True}


@router.get("/settings/global-rules/templates")
def list_templates() -> Dict:
    """起步模板列表（静态常量，不含用户数据）。"""
    return {"templates": _TEMPLATES}
