"""
搜索工具 - glob 文件名搜索 + grep 内容搜索（移植 claw-code file_ops.rs）

两者均为 READ 能力工具：按 M1 读写非对称设计**不做** workspace 边界
强制（工作区外只读保持可用）。默认搜索根取 ``policy.workspace_root``
（会话绑定的工作区；``ToolExecutionContext`` 本身不携带路径，workspace
绑定在 ToolPolicy 上），未绑定时回退当前目录。

共用约束:

- 默认跳过 ``node_modules`` / ``.git`` / ``__pycache__`` / ``dist``；
- grep 跳过二进制文件（复用 file_tool 的 NUL/BOM 嗅探）与超过读限额的
  大文件；
- 结果硬上限（glob 200 / grep content 100 行 / grep files 200），超限
  置 ``truncated=True``；
- grep ReDoS **缓解**（mitigation，不是根治——in-process ``re`` 对恶意
  模式无法保证线性时间，线程也无法被 asyncio 超时杀死）：正则长度上限
  ``GREP_MAX_PATTERN_LENGTH``（1 000 字符，超限直接报错）；content 模式
  逐行匹配时超过 ``GREP_MAX_LINE_LENGTH``（10 000 字符）的行跳过并计入
  ``skipped_long_lines``——把回溯炸弹能烧掉的资源压在有限输入上；
- 错误一律走 ``ToolResult(success=False)``，execute 永不抛异常。
"""

import fnmatch
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from .base import BaseTool, ToolResult, ToolSchema
from .file_tool import MAX_READ_SIZE_BYTES, _contains_binary_marker, detect_bom_encoding

logger = logging.getLogger(__name__)

#: 默认跳过的目录名（与 claw-code should_skip_glob_dir 同源）
IGNORED_DIR_NAMES = frozenset({"node_modules", ".git", "__pycache__", "dist"})

#: glob 结果条数上限
GLOB_MAX_RESULTS = 200
#: grep content 模式匹配行上限
GREP_CONTENT_MAX_MATCHES = 100
#: grep files 模式文件数上限
GREP_FILES_MAX_MATCHES = 200
#: grep 正则长度上限（ReDoS 缓解：超限模式直接拒绝，见模块 docstring）
GREP_MAX_PATTERN_LENGTH = 1_000
#: grep 单行长度上限（ReDoS 缓解：超长行不喂给不可信正则，跳过并计数）
GREP_MAX_LINE_LENGTH = 10_000


def _walk_files(root: str) -> Iterator[str]:
    """递归遍历 ``root`` 下的常规文件，原地剪掉 IGNORED_DIR_NAMES。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIR_NAMES]
        for name in filenames:
            yield os.path.join(dirpath, name)


def _resolve_search_root(tool: BaseTool, path: Optional[str]) -> Tuple[Optional[str], Optional[ToolResult]]:
    """解析搜索根目录: 显式 ``path`` 优先，否则绑定 workspace / cwd。

    返回 ``(root, None)`` 表示放行；``(None, ToolResult)`` 表示路径非法，
    调用方直接返回该错误结果。
    """
    if path:
        root = str(Path(path).expanduser())
        if not Path(root).exists():
            return None, ToolResult(success=False, error=f"搜索路径不存在: {path}")
        if not Path(root).is_dir():
            return None, ToolResult(success=False, error=f"不是目录: {path}")
        return root, None
    root = tool._policy.workspace_root or str(Path.cwd())  # noqa: SLF001 — 同包内策略读取
    return root, None


def _build_glob_matcher(pattern: str, root: str) -> Callable[[str, str], bool]:
    """构造 glob 匹配函数: ``(relative_posix_path, basename) -> bool``。

    fnmatch 的 ``*`` 天然跨目录匹配，故先把 ``**`` 归一成 ``*``；
    不含路径分隔符的 pattern（如 ``*.py``）按 basename 匹配任意深度文件，
    含分隔符的（如 ``src/*.py``）按相对路径匹配；绝对 pattern 按绝对路径。
    """
    normalized = pattern.replace("\\", "/").replace("**/", "*").replace("**", "*")
    if Path(pattern).is_absolute():
        # FIX-8: 拼出的绝对路径同样归一成 "/" 分隔——Windows 上 os.path.join
        # 产出 "\\" 分隔符，直接与 "/" 归一后的 pattern 匹配会永远落空
        return lambda rel, _base: fnmatch.fnmatch(
            os.path.join(root, rel).replace(os.sep, "/"), normalized
        )
    if "/" in normalized:
        return lambda rel, _base: fnmatch.fnmatch(rel, normalized)
    return lambda _rel, base: fnmatch.fnmatch(base, normalized)


class GlobSearchTool(BaseTool):
    """glob 文件名搜索工具"""

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="glob_search",
            description=(
                "按 glob 模式搜索文件路径（如 '**/*.py'、'src/*.ts'）。"
                "结果按修改时间倒序排列（最新在前），最多返回 200 条；"
                "默认跳过 node_modules/.git/__pycache__/dist。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "glob 模式（支持 * / ? / **）"},
                    "path": {
                        "type": "string",
                        "description": "搜索根目录 (可选，默认工作区根目录或当前目录)",
                    },
                },
                "required": ["pattern"],
            },
        )

    def execute(self, pattern: str = "", path: Optional[str] = None, **kwargs) -> ToolResult:
        """
        执行 glob 搜索

        Args:
            pattern: glob 模式
            path:    搜索根目录（缺省 → policy.workspace_root 或 cwd）

        Returns:
            ToolResult；content 含 files / num_files / total_matches /
            truncated / root。
        """
        try:
            if kwargs:
                names = ", ".join(sorted(kwargs))
                return ToolResult(
                    success=False,
                    error=f"未知参数: {names}（合法参数: pattern, path）",
                )
            if not isinstance(pattern, str) or not pattern.strip():
                return ToolResult(success=False, error="pattern 不能为空")

            root, blocked = _resolve_search_root(self, path)
            if blocked is not None:
                return blocked
            assert root is not None  # blocked 为 None 时 root 必然有值

            matcher = _build_glob_matcher(pattern, root)
            collected: List[Tuple[float, str]] = []
            for file_path in _walk_files(root):
                relative = os.path.relpath(file_path, root).replace(os.sep, "/")
                if not matcher(relative, os.path.basename(file_path)):
                    continue
                try:
                    mtime = Path(file_path).stat().st_mtime
                except OSError:
                    mtime = 0.0  # 断链 symlink 等：保留结果但排到最后
                collected.append((mtime, file_path))

            collected.sort(key=lambda item: item[0], reverse=True)
            total = len(collected)
            truncated = total > GLOB_MAX_RESULTS
            files = [file_path for _, file_path in collected[:GLOB_MAX_RESULTS]]

            return ToolResult(
                success=True,
                content={
                    "pattern": pattern,
                    "root": str(Path(root).resolve()),
                    "files": files,
                    "num_files": len(files),
                    "total_matches": total,
                    "truncated": truncated,
                },
            )

        except Exception as e:  # noqa: BLE001 — 工具约定：错误走 ToolResult 不抛
            logger.error("glob_search 执行失败: %s", e)
            return ToolResult(success=False, error=f"搜索失败: {e}")


def _validate_grep_params(
    kwargs: Dict[str, Any], pattern: str, output_mode: str
) -> Optional[ToolResult]:
    """grep 调用形态检查：未知参数 / output_mode / pattern 非空 / 长度上限。

    pattern 长度上限是 ReDoS 缓解的一部分（见模块 docstring）：超长正则
    的回溯空间不可控，直接拒绝而非喂给 ``re.compile``。
    """
    if kwargs:
        names = ", ".join(sorted(kwargs))
        return ToolResult(
            success=False,
            error=(
                f"未知参数: {names}（合法参数: pattern, path, "
                "case_insensitive, output_mode）"
            ),
        )
    if output_mode not in ("content", "files"):
        return ToolResult(success=False, error="output_mode 必须是 content 或 files")
    if not isinstance(pattern, str) or not pattern:
        return ToolResult(success=False, error="pattern 不能为空")
    if len(pattern) > GREP_MAX_PATTERN_LENGTH:
        return ToolResult(
            success=False,
            error=(
                f"正则表达式过长（{len(pattern)} 字符，上限 "
                f"{GREP_MAX_PATTERN_LENGTH}）——ReDoS 防护，请拆短模式"
            ),
        )
    return None


class GrepSearchTool(BaseTool):
    """grep 内容搜索工具"""

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="grep_search",
            description=(
                "按 Python 正则在工作区文件内容中搜索。"
                "output_mode=content 返回 'file:line:text' 匹配行（最多 100 行）；"
                "output_mode=files 只返回命中文件路径（最多 200 个）。"
                "自动跳过二进制文件与 node_modules/.git/__pycache__/dist。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Python 正则表达式"},
                    "path": {
                        "type": "string",
                        "description": "搜索根目录 (可选，默认工作区根目录或当前目录)",
                    },
                    "case_insensitive": {
                        "type": "boolean",
                        "description": "是否忽略大小写 (默认 false)",
                    },
                    "output_mode": {
                        "type": "string",
                        "enum": ["content", "files"],
                        "description": "输出模式: content=匹配行(默认) / files=仅文件路径",
                    },
                },
                "required": ["pattern"],
            },
        )

    def execute(
        self,
        pattern: str = "",
        path: Optional[str] = None,
        case_insensitive: bool = False,
        output_mode: str = "content",
        **kwargs,
    ) -> ToolResult:
        """
        执行 grep 搜索

        Args:
            pattern:          Python 正则（非法正则 → 干净错误，不抛异常）
            path:             搜索根目录（缺省 → policy.workspace_root 或 cwd）
            case_insensitive: 忽略大小写
            output_mode:      ``content`` / ``files``

        Returns:
            ToolResult；content 含 mode / matches 或 files / num_matches /
            files_scanned / skipped_binary / skipped_large / truncated。
        """
        try:
            invalid = _validate_grep_params(kwargs, pattern, output_mode)
            if invalid is not None:
                return invalid

            try:
                regex = re.compile(pattern, re.IGNORECASE if case_insensitive else 0)
            except re.error as exc:
                return ToolResult(success=False, error=f"非法正则表达式: {exc}")

            root, blocked = _resolve_search_root(self, path)
            if blocked is not None:
                return blocked
            assert root is not None

            content_matches: List[str] = []
            matched_files: List[str] = []
            total_match_count = 0
            files_scanned = 0
            skipped_binary = 0
            skipped_large = 0
            skipped_long_lines = 0
            truncated = False

            for file_path in _walk_files(root):
                target = Path(file_path)
                try:
                    size = target.stat().st_size
                except OSError:
                    continue
                if not target.is_file():
                    continue
                if size > MAX_READ_SIZE_BYTES:
                    skipped_large += 1
                    continue
                if _contains_binary_marker(target):
                    skipped_binary += 1
                    continue

                encoding = detect_bom_encoding(target) or "utf-8"
                try:
                    text = target.read_text(encoding=encoding, errors="replace")
                except (OSError, UnicodeError):
                    continue
                files_scanned += 1

                if output_mode == "files":
                    if regex.search(text):
                        matched_files.append(file_path)
                    continue

                # content 模式：逐行匹配，行级上限 100
                file_hit = False
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if len(line) > GREP_MAX_LINE_LENGTH:
                        # ReDoS 缓解：超长行不喂给不可信正则（见模块 docstring）
                        skipped_long_lines += 1
                        continue
                    if not regex.search(line):
                        continue
                    file_hit = True
                    total_match_count += 1
                    if len(content_matches) < GREP_CONTENT_MAX_MATCHES:
                        content_matches.append(f"{file_path}:{lineno}:{line}")
                    else:
                        truncated = True
                if file_hit:
                    matched_files.append(file_path)

            if output_mode == "files":
                # 扫完再判截断，恰好 == 上限时不误报 truncated
                truncated = len(matched_files) > GREP_FILES_MAX_MATCHES
                payload = {
                    "mode": "files",
                    "files": matched_files[:GREP_FILES_MAX_MATCHES],
                    "num_matches": len(matched_files),
                }
            else:
                payload = {
                    "mode": "content",
                    "matches": content_matches,
                    "num_matches": total_match_count,
                    "files_with_matches": matched_files,
                }
            payload.update(
                {
                    "root": str(Path(root).resolve()),
                    "files_scanned": files_scanned,
                    "skipped_binary": skipped_binary,
                    "skipped_large": skipped_large,
                    "skipped_long_lines": skipped_long_lines,
                    "truncated": truncated,
                }
            )
            return ToolResult(success=True, content=payload)

        except Exception as e:  # noqa: BLE001 — 工具约定：错误走 ToolResult 不抛
            logger.error("grep_search 执行失败: %s", e)
            return ToolResult(success=False, error=f"搜索失败: {e}")
