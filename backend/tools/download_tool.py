# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""http_download —— 流式下载文件到工作区。

与 ``bash`` + ``curl`` 的区别：走 EXTERNAL 风险类而非 EXEC，落盘路径受工作区
边界约束，且有双重大小上限。

**为什么不只依赖 ``_enforce_workspace``**：它在 ``policy.workspace_root`` 为
``None`` 时返回 ``None``（放行），而 legacy 聊天链路在会话无 workspace 绑定时
确实是 ``None``。下载的字节来自网络，写入位置不确定的风险高于本地文件操作，
所以这里未绑定就直接拒。
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from email.message import Message
from pathlib import Path, PurePosixPath
from typing import Optional
from urllib.parse import unquote, urljoin, urlparse

import httpx

from backend.domain.network_policy import NetworkPolicy
from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.tools.network_config import load_network_policy

from .base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

#: 单文件默认上限 100 MiB。文献 PDF 通常几 MB，留足余量
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024

#: 流式写入的块大小
_CHUNK_BYTES = 64 * 1024

#: 文件名保留：ASCII 字母数字 + 点 + 下划线 + 连字符 + 空格 + CJK
_UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._一-鿿\- ]")

_FALLBACK_NAME = "download.bin"

#: 文件名长度上限，给冲突后缀留余量（Windows MAX_PATH 与 ext4 255 字节都够）
_MAX_NAME_CHARS = 120

#: 手动跟随重定向的最大跳数
_MAX_REDIRECTS = 5


def sanitize_filename(name: Optional[str]) -> str:
    """把任意来源的文件名净化成安全的 basename。

    剥路径分隔符（正反斜杠都算）、NUL 字节、首尾点与空格；不安全字符换下划线。
    净化后为空或全是下划线则回退 ``download.bin``。
    """
    if not name:
        return _FALLBACK_NAME
    cleaned = unicodedata.normalize("NFC", name).replace("\x00", "")
    # 反斜杠先转正斜杠，让 PurePosixPath 能剥掉 Windows 风格路径
    cleaned = PurePosixPath(cleaned.replace("\\", "/")).name
    cleaned = _UNSAFE_NAME_RE.sub("_", cleaned).strip(" .")
    if not cleaned or set(cleaned) <= {"_"}:
        return _FALLBACK_NAME
    return cleaned[:_MAX_NAME_CHARS]


def _filename_from_disposition(value: Optional[str]) -> Optional[str]:
    """从 ``Content-Disposition`` 取文件名。

    用 ``Message.get_filename()`` 而非 ``get_param("filename")``：前者同时处理
    ``filename="x"`` 与 RFC 5987 的 ``filename*=UTF-8''%XX``（后者对 ``filename*``
    恒返回 ``None``，会漏掉所有中文附件名）。
    """
    if not value:
        return None
    msg = Message()
    msg["content-disposition"] = value
    name = msg.get_filename()
    return str(name) if name else None


def derive_filename(url: str, disposition: Optional[str] = None) -> str:
    """决定落盘文件名：``Content-Disposition`` 优先，否则取 URL path 末段。"""
    from_header = _filename_from_disposition(disposition)
    if from_header:
        return sanitize_filename(from_header)
    from_url = PurePosixPath(unquote(urlparse(url).path)).name
    return sanitize_filename(from_url)


def _unique_path(directory: Path, filename: str) -> Path:
    """避开同名文件。``a.pdf`` 冲突则依次试 ``a-1.pdf`` / ``a-2.pdf``。"""
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for index in range(1, 1000):
        alternative = directory / f"{stem}-{index}{suffix}"
        if not alternative.exists():
            return alternative
    raise OSError(f"无法为 {filename!r} 找到可用文件名（同名文件过多）")


def _open_exclusive(directory: Path, filename: str):
    """Open a new regular file without following a symlink."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if os.name != "posix" or not nofollow:
        raise OSError("下载写盘缺少可靠的 no-follow 原语")
    directory_fd = os.open(str(directory), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow)
    try:
        fd = os.open(filename, flags | nofollow, 0o600, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)
    return os.fdopen(fd, "wb")


class HttpDownloadTool(BaseTool):
    """http_download —— 流式下载到工作区。"""

    # 出网 + 写盘，取更严的语义：只读模式禁止，交互模式询问
    risk = RiskClass.EXTERNAL

    def __init__(
        self,
        policy: Optional[ToolPolicy] = None,
        network_policy: Optional[NetworkPolicy] = None,
    ) -> None:
        super().__init__(policy=policy)
        self._network_policy = network_policy
        self.client = httpx.Client(
            timeout=self._policy.timeout_seconds,
            follow_redirects=False,
            trust_env=not self._policy.subagent_only,
        )

    def _effective_network_policy(self) -> NetworkPolicy:
        if self._network_policy is not None:
            return self._network_policy
        return load_network_policy()

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="http_download",
            description=(
                "下载文件到工作区。适用于文献 PDF、资源站附件等。"
                "filename 省略时从 URL 或 Content-Disposition 推断；"
                "只接受工作区内的相对路径。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "文件 URL"},
                    "filename": {
                        "type": "string",
                        "description": "工作区内的相对文件名 (省略则自动推断)",
                    },
                    "max_bytes": {
                        "type": "integer",
                        "description": f"大小上限 (默认 {MAX_DOWNLOAD_BYTES})",
                    },
                },
                "required": ["url"],
            },
        )

    def execute(  # noqa: PLR0911 — 每个拒绝路径独立 return，扁平比提取辅助函数更直读
        self,
        url: str,
        filename: Optional[str] = None,
        max_bytes: int = MAX_DOWNLOAD_BYTES,
        **kwargs,
    ) -> ToolResult:
        """下载 ``url`` 到工作区。

        Args:
            url:       文件 URL
            filename:  工作区内相对文件名；``None`` 则自动推断
            max_bytes: 大小上限（声明值与实际字节双重校验）
        """
        url_error = self._validate_target_url(url)
        if url_error:
            return ToolResult(success=False, error=url_error)

        root = self._policy.workspace_root
        if not root:
            return ToolResult(
                success=False,
                error="workspace_not_bound: 下载需要先绑定工作区（会话未绑定时不允许写盘）",
            )

        if filename is not None:
            if Path(filename).is_absolute():
                return ToolResult(
                    success=False,
                    error="filename_must_be_relative: 只接受工作区内的相对文件名",
                )
            blocked = self._enforce_workspace(str(Path(root) / filename))
            if blocked is not None:
                return blocked

        network_policy = self._effective_network_policy()
        host_rejection = network_policy.check_host(url)
        if host_rejection:
            return ToolResult(success=False, error=host_rejection)

        try:
            return self._stream_to_disk(url, filename, max_bytes, Path(root), network_policy)
        except httpx.HTTPError as e:
            return ToolResult(success=False, error=f"HTTP 请求失败: {str(e)}")
        except Exception as e:
            return ToolResult(success=False, error=f"下载失败: {str(e)}")

    def _stream_to_disk(  # noqa: PLR0911 — 每个拒绝路径独立 return，保持下载流程直读
        self,
        url: str,
        filename: Optional[str],
        max_bytes: int,
        root: Path,
        network_policy: NetworkPolicy,
    ) -> ToolResult:
        """边下边写。返回成功或失败的 ``ToolResult``。"""
        current_url = url
        for redirect_count in range(_MAX_REDIRECTS + 1):
            parsed = urlparse(current_url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                return ToolResult(
                    success=False,
                    error="无效的 URL，必须包含 http:// 或 https:// 以及主机名",
                )
            host_rejection = network_policy.check_host(current_url)
            if host_rejection:
                return ToolResult(success=False, error=host_rejection)

            with httpx.Client(
                timeout=self._policy.timeout_seconds,
                follow_redirects=False,
                verify=not network_policy.allows_insecure_tls(current_url),
                trust_env=not self._policy.subagent_only,
            ) as client:
                request = client.build_request("GET", current_url)
                response = client.send(request, stream=True)
                if response.is_redirect:
                    if redirect_count >= _MAX_REDIRECTS:
                        response.close()
                        return ToolResult(
                            success=False,
                            error=f"redirect_limit_exceeded: 重定向次数超过 {_MAX_REDIRECTS} 次",
                        )
                    location = response.headers.get("location")
                    response.close()
                    if not location:
                        return ToolResult(
                            success=False, error="invalid_redirect: 重定向缺少 Location"
                        )
                    current_url = urljoin(current_url, location)
                    continue

                response.raise_for_status()

                declared = response.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > max_bytes:
                    response.close()
                    return ToolResult(
                        success=False,
                        error=(
                            f"content_length_exceeds_limit: 服务器声明 {declared} 字节，"
                            f"超过上限 {max_bytes}"
                        ),
                    )

                name = (
                    sanitize_filename(filename)
                    if filename
                    else derive_filename(current_url, response.headers.get("content-disposition"))
                )
                root.mkdir(parents=True, exist_ok=True)
                target = _unique_path(root, name)

                written = 0
                owns_target = False
                try:
                    with _open_exclusive(root, target.name) as handle:
                        owns_target = True
                        for chunk in response.iter_bytes(_CHUNK_BYTES):
                            written += len(chunk)
                            # Content-Length 是服务器说的，不可信；按实际字节兜底
                            if written > max_bytes:
                                raise _DownloadTooLarge(written)
                            handle.write(chunk)
                except _DownloadTooLarge as exc:
                    if owns_target:
                        target.unlink(missing_ok=True)
                    return ToolResult(
                        success=False,
                        error=f"download_exceeds_limit: 实际接收 {exc.written} 字节，超过上限 {max_bytes}",
                    )
                except Exception:
                    if owns_target:
                        target.unlink(missing_ok=True)
                    raise
                finally:
                    response.close()

            self._record_artifact(str(target), written)
            return ToolResult(
                success=True,
                content={
                    "url": current_url,
                    "path": str(target),
                    "filename": target.name,
                    "bytes_written": written,
                    "content_type": response.headers.get("content-type", ""),
                },
                output=str(target),
            )

        return ToolResult(success=False, error="redirect_limit_exceeded: 重定向次数超限")

    @staticmethod
    def _validate_target_url(url: str) -> Optional[str]:
        try:
            parsed = urlparse(url)
        except ValueError:
            return "无效的 URL，必须包含 http:// 或 https:// 以及主机名"
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return "无效的 URL，必须包含 http:// 或 https:// 以及主机名"
        return None

    @staticmethod
    def _record_artifact(path: str, size: int) -> None:
        """挂进 Artifacts 面板；失败静默（不影响下载结果）。"""
        try:
            from backend.tools.file_tool import _record_artifact_safely

            _record_artifact_safely(path, size)
        except Exception:  # noqa: BLE001 — 记录产物失败绝不阻断下载
            logger.debug("http_download: 记录产物失败", exc_info=True)


class _DownloadTooLarge(Exception):  # noqa: N818 — internal signal exception, not part of public API
    """内部信号：实际字节数超过上限。不外泄给调用方。"""

    def __init__(self, written: int) -> None:
        super().__init__(f"download exceeded limit at {written} bytes")
        self.written = written
