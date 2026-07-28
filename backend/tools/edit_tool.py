"""
精确编辑工具 - 字符串替换式编辑（移植 claw-code file_ops.rs ``edit_file``）

与 ``write_file`` 的整文件覆写不同，``edit_file`` 只做局部替换：

- 文件必须已存在（创建是 ``write_file`` 的职责）；
- ``old_string`` 必须逐字符精确匹配（含空白）；
- 默认要求匹配唯一，多处匹配需显式 ``replace_all=true``；
- 复用 M1 加固设施：写 10 MiB 硬限额（``file_tool.MAX_WRITE_SIZE_BYTES``）、
  二进制嗅探（``file_tool._contains_binary_marker``）、BOM 识别
  （``file_tool.detect_bom_encoding``，UTF-16/.reg 类文件按原编码回写）；
- WRITE 能力工具：``BaseTool._enforce_workspace`` 在入口强制 workspace
  边界（与 file_tool 写路径同源的 resolve 前缀语义，拦 ``../`` 穿越 +
  symlink 逃逸）。
"""

import difflib
import logging
from pathlib import Path
from typing import Optional, Tuple

from .base import BaseTool, ToolResult, ToolSchema
from .file_tool import MAX_WRITE_SIZE_BYTES, _contains_binary_marker, detect_bom_encoding

logger = logging.getLogger(__name__)


def _not_found_hint(text: str, old_string: str) -> str:
    """old_string 未命中时生成排查提示（空白差异优先，其次最近行）。

    返回拼在错误信息后的中文括号提示串；无可用线索时返回空串。
    """
    lines = text.splitlines()
    old_lines = old_string.splitlines()
    first_line = old_lines[0] if old_lines else ""

    # 线索 1: strip 后内容相同 → 几乎必然是空白/缩进差异
    stripped = first_line.strip()
    if stripped:
        for index, line in enumerate(lines, start=1):
            if line.strip() == stripped and line != first_line:
                return (
                    f"（疑似空白差异：第 {index} 行去除首尾空白后与 old_string 首行一致："
                    f"{stripped[:80]!r}，请检查缩进/行尾空格）"
                )

    # 线索 2: difflib 最近行（cutoff 0.6，避免噪音）
    nearest = difflib.get_close_matches(first_line, lines, n=1, cutoff=0.6)
    if nearest:
        return f"（最接近的行：{nearest[0][:80]!r}）"
    return ""


def _count_logical_lines(fragment: str) -> int:
    """片段占用的逻辑行数（空串记 0 行）。"""
    if not fragment:
        return 0
    return fragment.count("\n") + 1


def _validate_edit_params(old_string: str, new_string: str) -> Optional[ToolResult]:
    """参数级前置检查（与文件无关）；返回 None 表示放行。"""
    if old_string == new_string:
        return ToolResult(success=False, error="old_string 与 new_string 必须不同")
    if not old_string:
        return ToolResult(success=False, error="old_string 不能为空")
    return None


def _validate_target_file(target: Path, file_path: str) -> Optional[ToolResult]:
    """目标文件前置检查：存在 / 常规文件 / 非二进制；返回 None 表示放行。"""
    if not target.exists():
        return ToolResult(
            success=False,
            error=f"文件不存在: {file_path}（edit_file 只编辑现有文件，创建请用 write_file）",
        )
    if not target.is_file():
        return ToolResult(success=False, error=f"不是文件: {file_path}")
    if _contains_binary_marker(target):
        return ToolResult(success=False, error="binary_file: 检测到二进制文件，不支持精确编辑")
    return None


def _resolve_matches(
    original: str, old_string: str, replace_all: bool
) -> Tuple[Optional[int], Optional[ToolResult]]:
    """计算替换次数：0 处 → 带提示错误；多处且非 replace_all → 唯一性错误。

    返回 ``(次数, None)`` 放行或 ``(None, ToolResult)`` 拒绝。
    """
    match_count = original.count(old_string)
    if match_count == 0:
        hint = _not_found_hint(original, old_string)
        return None, ToolResult(success=False, error=f"old_string 未在文件中找到{hint}")
    if match_count > 1 and not replace_all:
        return None, ToolResult(
            success=False,
            error=f"匹配不唯一（{match_count} 处），请提供更多上下文或用 replace_all",
        )
    return match_count, None


class EditTool(BaseTool):
    """精确编辑工具 - 在现有文件中做精确字符串替换"""

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="edit_file",
            description=(
                "精确编辑现有文件：用 new_string 替换 old_string。"
                "old_string 必须与文件内容逐字符一致（含空白与缩进）；"
                "默认要求匹配唯一，多处匹配时须显式 replace_all=true。"
                "文件不存在时报错（创建新文件请用 write_file）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "要编辑的文件路径（必须已存在）"},
                    "old_string": {
                        "type": "string",
                        "description": "要被替换的原文本（精确匹配，含空白）",
                    },
                    "new_string": {"type": "string", "description": "替换后的新文本（可为空串表示删除）"},
                    "replace_all": {
                        "type": "boolean",
                        "description": "替换全部匹配处 (默认 false，仅允许唯一匹配)",
                    },
                },
                "required": ["file_path", "old_string", "new_string"],
            },
        )

    def execute(
        self,
        file_path: str,
        old_string: str = "",
        new_string: str = "",
        replace_all: bool = False,
        **kwargs,
    ) -> ToolResult:
        """
        执行精确替换编辑

        Args:
            file_path:   目标文件路径（必须存在）
            old_string:  待替换原文本（精确匹配）
            new_string:  新文本
            replace_all: 是否替换全部匹配

        Returns:
            ToolResult；content 含 path / replacements / lines_added /
            lines_removed / bytes_written 的变更摘要。
        """
        # M1: WRITE 能力 → workspace 边界强制（policy.workspace_root 绑定时）
        blocked = self._enforce_workspace(file_path)
        if blocked is not None:
            return blocked

        invalid = _validate_edit_params(old_string, new_string)
        if invalid is not None:
            return invalid

        try:
            return self._apply_edit(file_path, old_string, new_string, bool(replace_all))
        except Exception as e:  # noqa: BLE001 — 工具约定：错误走 ToolResult 不抛
            logger.error("edit_file 执行失败: %s", e)
            return ToolResult(success=False, error=f"编辑失败: {e}")

    def _apply_edit(
        self, file_path: str, old_string: str, new_string: str, replace_all: bool
    ) -> ToolResult:
        """参数校验通过后的读-匹配-替换-写主流程（保持 execute 扁平）。"""
        target = Path(file_path).expanduser()

        file_error = _validate_target_file(target, file_path)
        if file_error is not None:
            return file_error

        # BOM 识别：UTF-16/UTF-8 BOM 文件按原编码读写，回写保留 BOM
        encoding = detect_bom_encoding(target) or "utf-8"
        try:
            original = target.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            return ToolResult(success=False, error=f"文件解码失败（{encoding}）: {exc}")

        match_count, match_error = _resolve_matches(original, old_string, replace_all)
        if match_error is not None:
            return match_error

        replacements = match_count if replace_all else 1
        if replace_all:
            updated = original.replace(old_string, new_string)
        else:
            updated = original.replace(old_string, new_string, 1)

        # M1: 写入硬限额（复用 file_tool 常量，按编码后字节数计）
        updated_bytes = updated.encode(encoding)
        if len(updated_bytes) > MAX_WRITE_SIZE_BYTES:
            return ToolResult(
                success=False,
                error=(
                    f"content_too_large: 编辑后内容 {len(updated_bytes)} 字节超过写入上限 "
                    f"{MAX_WRITE_SIZE_BYTES} 字节 (10 MiB)"
                ),
            )

        target.write_bytes(updated_bytes)

        return ToolResult(
            success=True,
            content={
                "path": str(target.resolve()),
                "replacements": replacements,
                "lines_removed": _count_logical_lines(old_string) * replacements,
                "lines_added": _count_logical_lines(new_string) * replacements,
                "bytes_written": len(updated_bytes),
            },
        )
