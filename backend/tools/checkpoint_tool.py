"""工作区检查点工具（对标增强方案 Phase-1 T2，docs/plans/2026-09-06）。

对标 ZCode rewind / Cursor checkpoints / Codex 回滚：代理批量修改工作区
文件前先打快照，出问题可恢复。此前 Sage 只有 office 文档有 pre-edit
snapshot（office/storage.py），任意工作区文件没有安全网。

实现口径：

- 快照 = stdlib ``zipfile``，存 **sage 自有数据目录**（不污染工作区、
  不出现在 git status）：
  ``${SAGE_USER_DATA_DIR:-~/.sage}/checkpoints/<workspace路径sha1>/``；
- 排除重目录（``.git`` / ``node_modules`` 等），单文件超 8MiB 跳过，
  总量超 256MiB 整体放弃；每工作区保留最近 10 份；
- 恢复 = 逐成员校验后覆盖写（防 zip-slip，兼容 py3.8 无
  ``Path.is_relative_to``）；只覆盖不删除 —— 快照之后新建的文件保留。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from zipfile import ZipFile

from backend.domain.risk import RiskClass

from .base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

#: 打快照时跳过的目录名（构建产物 / 依赖 / 版本库 / 自身数据）
EXCLUDED_DIRS = frozenset(
    {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".sage"}
)

#: 单文件快照上限（超限跳过并记录，不失败）
MAX_FILE_BYTES = 8 * 1024 * 1024

#: 单次快照总量上限（超限整体放弃，提示用户缩小工作区）
MAX_TOTAL_BYTES = 256 * 1024 * 1024

#: 每个工作区保留的快照份数（超出淘汰最旧）
RETENTION_COUNT = 10

#: 快照 zip 内的清单文件名（不参与恢复）
_MANIFEST_NAME = "__sage_checkpoint.json"

#: 历史命名兼容别名：测试/上层引用排除表
CHECKPOINT_EXCLUDED_DIRS = EXCLUDED_DIRS


class _SnapshotTooLargeError(Exception):
    """工作区总量超过快照上限 —— 触发整体放弃并清理临时文件。"""


def _user_data_root() -> Path:
    """与 main.py / theme_storage 同口径：env 优先，回退 ``~/.sage``。"""
    env = os.environ.get("SAGE_USER_DATA_DIR")
    return Path(env) if env else Path.home() / ".sage"


def _checkpoint_dir(workspace_root: str) -> Path:
    """某工作区的快照目录（路径 sha1 做 key，避免目录名歧义/非法字符）。"""
    key = hashlib.sha1(os.path.normcase(os.path.abspath(workspace_root)).encode("utf-8")).hexdigest()
    return _user_data_root() / "checkpoints" / key


def _safe_member_path(root: Path, arcname: str) -> Optional[Path]:
    """把 zip 成员名解析为 root 内的安全目标路径；越界返回 None。

    防 zip-slip：拒绝绝对路径、盘符、``..`` 段，以及 resolve 后逃出 root 的
    名字。py3.8 兼容（不用 ``Path.is_relative_to``）。
    """
    name = arcname.replace("\\", "/")
    segments = name.split("/")
    if not name or name.startswith("/") or ".." in segments:
        return None
    drive, _ = os.path.splitdrive(name)
    if drive:
        return None
    target = (root / "/".join(segments)).resolve()
    root_resolved = os.path.normcase(str(root.resolve()))
    target_norm = os.path.normcase(str(target))
    if target_norm != root_resolved and not target_norm.startswith(root_resolved + os.sep):
        return None
    return target


class CheckpointCreateTool(BaseTool):
    """为整个工作区创建快照（只追加 sage 自有数据，不改工作区 → READ）。"""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="checkpoint_create",
            description=(
                "为当前工作区创建检查点快照（zip 存到 Sage 数据目录，不动工作区）。"
                "批量修改文件前先建快照，出问题可用 checkpoint_restore 恢复。"
                "自动跳过 .git/node_modules 等目录和超过 8MiB 的单文件。"
            ),
            parameters={"type": "object", "properties": {}, "required": []},
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        if kwargs:
            return ToolResult(success=False, error="checkpoint_create 不接受参数")

        root = self._policy.workspace_root
        if not root:
            return ToolResult(
                success=False, error="checkpoint 工具需要绑定工作区（workspace）"
            )
        root_path = Path(root)
        if not root_path.is_dir():
            return ToolResult(success=False, error=f"工作区目录不存在: {root}")

        checkpoint_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        target_dir = _checkpoint_dir(root)
        target_dir.mkdir(parents=True, exist_ok=True)
        zip_path = target_dir / f"{checkpoint_id}.zip"
        tmp_path = target_dir / f"{checkpoint_id}.zip.tmp"

        files = 0
        skipped: List[str] = []
        total = 0
        try:
            with ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for current_dir, dir_names, file_names in os.walk(root_path):
                    # 原地剪枝：不进入重目录
                    dir_names[:] = sorted(d for d in dir_names if d not in EXCLUDED_DIRS)
                    for file_name in sorted(file_names):
                        file_path = Path(current_dir) / file_name
                        arcname = file_path.relative_to(root_path).as_posix()
                        try:
                            size = file_path.stat().st_size
                        except OSError:
                            skipped.append(arcname)
                            continue
                        if size > MAX_FILE_BYTES:
                            skipped.append(arcname)
                            continue
                        if total + size > MAX_TOTAL_BYTES:
                            raise _SnapshotTooLargeError()
                        try:
                            archive.write(file_path, arcname=arcname)
                        except OSError:
                            skipped.append(arcname)
                            continue
                        total += size
                        files += 1
                archive.writestr(
                    _MANIFEST_NAME,
                    json.dumps(
                        {
                            "checkpoint_id": checkpoint_id,
                            "workspace": str(root_path),
                            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "files": files,
                            "skipped": skipped,
                            "bytes": total,
                        },
                        ensure_ascii=False,
                    ),
                )
            tmp_path.replace(zip_path)
        except _SnapshotTooLargeError:
            tmp_path.unlink(missing_ok=True)
            return ToolResult(
                success=False,
                error=(
                    "工作区总量超过快照上限（256MiB），未创建检查点；"
                    "请缩小工作区或手工清理大文件后重试"
                ),
            )
        except OSError as exc:
            tmp_path.unlink(missing_ok=True)
            return ToolResult(success=False, error=f"快照写入失败: {exc}")

        self._apply_retention(target_dir)
        return ToolResult(
            success=True,
            content={
                "checkpoint_id": checkpoint_id,
                "files": files,
                "skipped": skipped,
                "bytes": total,
            },
        )

    @staticmethod
    def _apply_retention(target_dir: Path) -> List[str]:
        """保留最近 RETENTION_COUNT 份，返回被淘汰的 checkpoint_id。"""
        zips = sorted(target_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        removed = []
        for stale in zips[RETENTION_COUNT:]:
            try:
                stale.unlink()
                removed.append(stale.stem)
            except OSError:
                logger.warning("快照淘汰失败: %s", stale, exc_info=True)
        return removed


class CheckpointListTool(BaseTool):
    """列出当前工作区已有的检查点（新→旧）。"""

    risk = RiskClass.READ

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="checkpoint_list",
            description="列出当前工作区已有的检查点快照（新→旧），含 id、时间与大小。",
            parameters={"type": "object", "properties": {}, "required": []},
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        if kwargs:
            return ToolResult(success=False, error="checkpoint_list 不接受参数")

        root = self._policy.workspace_root
        if not root:
            return ToolResult(
                success=False, error="checkpoint 工具需要绑定工作区（workspace）"
            )
        target_dir = _checkpoint_dir(root)
        if not target_dir.is_dir():
            return ToolResult(success=True, content={"checkpoints": []})

        checkpoints: List[Dict[str, Any]] = []
        for zip_path in sorted(
            target_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            entry: Dict[str, Any] = {
                "checkpoint_id": zip_path.stem,
                "created_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%S", time.localtime(zip_path.stat().st_mtime)
                ),
                "bytes": zip_path.stat().st_size,
                "files": None,
            }
            try:
                with ZipFile(zip_path) as archive:
                    manifest = json.loads(archive.read(_MANIFEST_NAME).decode("utf-8"))
                entry["files"] = manifest.get("files")
            except (OSError, ValueError, KeyError):
                logger.warning("快照清单读取失败: %s", zip_path, exc_info=True)
            checkpoints.append(entry)
        return ToolResult(success=True, content={"checkpoints": checkpoints})


class CheckpointRestoreTool(BaseTool):
    """把指定快照覆盖恢复到工作区（WRITE_LOCAL，INTERACTIVE 先审批）。"""

    risk = RiskClass.WRITE_LOCAL

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="checkpoint_restore",
            description=(
                "把指定 checkpoint_id 的快照覆盖恢复到当前工作区（用 checkpoint_list "
                "查询可用 id）。只覆盖快照里存在的文件，不删除快照之后新建的文件。"
                "恢复前建议先 checkpoint_create 一份当前状态。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "checkpoint_id": {"type": "string", "description": "checkpoint_list 返回的快照 id"},
                },
                "required": ["checkpoint_id"],
            },
        )

    def execute(self, checkpoint_id: str = "", **kwargs: Any) -> ToolResult:
        if kwargs:
            return ToolResult(
                success=False,
                error=f"未知参数: {', '.join(sorted(kwargs))}（合法参数: checkpoint_id）",
            )
        # id 校验合一：非空 + 白名单字符（防路径拼接注入，id 只应是 <时间>-<hex> 形态）
        if (
            not isinstance(checkpoint_id, str)
            or not checkpoint_id.strip()
            or not checkpoint_id.replace("-", "").isalnum()
        ):
            return ToolResult(success=False, error="checkpoint_id 不能为空或格式非法")

        root = self._policy.workspace_root
        if not root:
            return ToolResult(
                success=False, error="checkpoint 工具需要绑定工作区（workspace）"
            )

        zip_path = _checkpoint_dir(root) / f"{checkpoint_id}.zip"
        if not zip_path.is_file():
            return ToolResult(success=False, error=f"快照不存在: {checkpoint_id}")

        rejection, restored = self._restore_archive(Path(root), zip_path)
        if rejection is not None:
            return rejection

        return ToolResult(success=True, content={"checkpoint_id": checkpoint_id, "restored": restored})

    @staticmethod
    def _restore_archive(root_path: Path, zip_path: Path):
        """解包快照覆盖工作区；返回 (拒绝结果, 恢复文件数)。"""
        restored = 0
        try:
            with ZipFile(zip_path) as archive:
                for member in archive.infolist():
                    if member.filename == _MANIFEST_NAME:
                        continue
                    target = _safe_member_path(root_path, member.filename)
                    if target is None:
                        return (
                            ToolResult(
                                success=False,
                                error=f"快照包含越界路径，已中止恢复: {member.filename}",
                            ),
                            restored,
                        )
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(member))
                    restored += 1
        except (OSError, zipfile.BadZipFile) as exc:
            return ToolResult(success=False, error=f"恢复失败: {exc}"), restored
        return None, restored


__all__ = [
    "CHECKPOINT_EXCLUDED_DIRS",
    "CheckpointCreateTool",
    "CheckpointListTool",
    "CheckpointRestoreTool",
]
