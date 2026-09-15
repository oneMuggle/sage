# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""http_download —— 流式下载文件到工作区（Round 5 B1：可靠性）。

与 ``bash`` + ``curl`` 的区别：走 EXTERNAL 风险类而非 EXEC，落盘路径受工作区
边界约束，且有双重大小上限。

**为什么不只依赖 ``_enforce_workspace``**：它在 ``policy.workspace_root`` 为
``None`` 时返回 ``None``（放行），而 legacy 聊天链路在会话无 workspace 绑定时
确实是 ``None``。下载的字节来自网络，写入位置不确定的风险高于本地文件操作，
所以这里未绑定就直接拒。

**Round 5 B1 可靠性（DL1 / DL3）**：

- ``.part`` 原子落盘：写入 ``<name>.part``，成功后 ``os.replace`` 到最终名；
  中断时 ``.part`` 与旁车 ``<name>.part.json``（url / etag / last_modified /
  total / written）保留，供续传；
- 重试 + 退避：可重试异常（连接 / 读超时 / 协议错 / 5xx / 429）指数退避
  ``1s·2^n + jitter``，429 / 503 尊重 ``Retry-After``（上限 60s）；
- Range 续传：``.part`` 存在且上次响应 ``Accept-Ranges: bytes`` 时发
  ``Range: bytes=<written>-`` + ``If-Range``；206 追加、200 重下、416 视为已完成；
- 完整性：``Content-Length`` 已知且实际字节不足 → ``incomplete_download``
  并保留 ``.part``；``expected_sha256`` 给定则校验；
- 超时拆分：connect / read / write / pool 分别设置，读超时按块计；
- 默认请求头：复用出网默认 UA / Accept（无 UA 请求被文献站 403 是常态）+
  ``Accept-Encoding: identity``（保证 Content-Length 与落盘字节可比）+
  ``Referer``（默认取目标 origin，很多文献站校 Referer）；
- 魔数嗅探（DL3）：期望是 PDF/ZIP/Office 而首块是 HTML → ``html_instead_of_file``
  立即中止，附页面摘要与路由指引（登录态 / 浏览器通道）。

安全口径不变：``.part`` / ``.json`` 同样经 ``_open_exclusive``；续传每一跳仍走
``check_host``；``If-Range`` 不匹配（服务器回 200）一律丢弃半成品重下，防止
拼接不同版本。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import random
import re
import time
import unicodedata
from email.message import Message
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional
from urllib.parse import unquote, urljoin, urlparse

import httpx

from backend.domain.network_policy import NetworkPolicy
from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.tools.http_factory import build_client, default_headers
from backend.tools.network_config import load_network_policy

from . import content_sniff
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

#: 默认重试次数（不含首次）；每次重试都是一次完整的"重定向链 + 请求"
DEFAULT_RETRIES = 3

#: 重试次数硬上限（防止模型传入过大值长时间占用 executor）
MAX_RETRIES = 6

#: 指数退避基数（秒）与上限（秒）
_BACKOFF_BASE_SECONDS = 1.0
_BACKOFF_MAX_SECONDS = 30.0

#: Retry-After 尊重上限（秒）
_RETRY_AFTER_CAP_SECONDS = 60.0

#: 可重试的 HTTP 状态码
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

#: 反爬 / 拒绝类状态码 —— 不重试（重试只会加深封禁），给路由指引
_ANTIBOT_STATUS = frozenset({401, 403})

#: 半成品后缀
PART_SUFFIX = ".part"

#: 半成品旁车元数据后缀
PART_META_SUFFIX = ".part.json"

#: 分段超时（秒）：connect / read（按块）/ write / pool
_CONNECT_TIMEOUT = 15.0
_WRITE_TIMEOUT = 30.0
_POOL_TIMEOUT = 10.0

_ANTIBOT_GUIDANCE = (
    "（站点疑似反爬 / 需要登录。出路：① 若已在浏览器登录，browser_cookies "
    "action=export 后以 credential_domain 重试；② 经 browser_launch + "
    "browser_navigate 真浏览器通道点击下载；③ 设置 → 网络中配置代理后重试）"
)

#: 测试钩子：``None`` = 真实 ``time.sleep``；单测替换为 no-op 记录器
_sleep = time.sleep


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
    """避开同名文件。``a.pdf`` 冲突则依次试 ``a-1.pdf`` / ``a-2.pdf``。

    同时避开对应的 ``.part`` 半成品（另一个下载正在进行 / 中断残留且非本次
    续传目标）。
    """
    candidate = directory / filename
    if not candidate.exists() and not (directory / (filename + PART_SUFFIX)).exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for index in range(1, 1000):
        alt_name = f"{stem}-{index}{suffix}"
        alternative = directory / alt_name
        if not alternative.exists() and not (directory / (alt_name + PART_SUFFIX)).exists():
            return alternative
    raise OSError(f"无法为 {filename!r} 找到可用文件名（同名文件过多）")


def _open_exclusive(directory: Path, filename: str, append: bool = False):
    """Open a regular file without following a symlink.

    ``append=False``：``O_CREAT|O_EXCL`` 新建（名字已被占用即失败，不跟随链接）；
    ``append=True``：续传打开既有 ``.part``，``O_NOFOLLOW``（POSIX）拒绝符号链接，
    Windows 侧先以 ``lstat`` 拒绝 reparse point。
    """
    flags = os.O_WRONLY | os.O_APPEND if append else os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if os.name == "nt":
        # Windows 无 O_NOFOLLOW，但 O_CREAT|O_EXCL 映射 CreateFile(CREATE_NEW)：
        # 名字已被文件/符号链接占用时在目录项层面直接失败，不跟随链接，与
        # POSIX 侧同一条"拒绝竞争目录项"语义。dir_fd 不可用，TOCTOU 收窄靠 O_EXCL。
        full = directory / filename
        if append:
            st = os.lstat(str(full))
            if getattr(st, "st_file_attributes", 0) & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
                raise OSError("续传目标是符号链接 / reparse point，拒绝写入")
        return os.fdopen(
            os.open(str(full), flags | getattr(os, "O_BINARY", 0)), "ab" if append else "wb"
        )
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        raise OSError("下载写盘缺少可靠的 no-follow 原语")
    directory_fd = os.open(str(directory), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow)
    try:
        fd = os.open(filename, flags | nofollow, 0o600, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)
    return os.fdopen(fd, "ab" if append else "wb")


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    """解析 ``Retry-After``（秒数或 HTTP-date）；不可解析返回 ``None``。"""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        from email.utils import parsedate_to_datetime

        target = parsedate_to_datetime(value)
        delta = target.timestamp() - time.time()
        return max(0.0, delta)
    except Exception:  # noqa: BLE001 — 非法日期按无 Retry-After 处理
        return None


def _backoff_seconds(attempt: int, retry_after: Optional[float] = None) -> float:
    """第 ``attempt`` 次重试（从 0 起）前的等待秒数。"""
    if retry_after is not None:
        return min(retry_after, _RETRY_AFTER_CAP_SECONDS)
    base = min(_BACKOFF_BASE_SECONDS * (2**attempt), _BACKOFF_MAX_SECONDS)
    return base + random.uniform(0, base * 0.25)


def _parse_content_range_total(value: Optional[str]) -> Optional[int]:
    """``Content-Range: bytes 100-999/1000`` → 1000；``*`` 或非法返回 ``None``。"""
    if not value:
        return None
    match = re.match(r"^\s*bytes\s+(?:\d+-\d+|\*)/(\d+|\*)\s*$", value, re.IGNORECASE)
    if not match or match.group(1) == "*":
        return None
    return int(match.group(1))


def _parse_content_range_start(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    match = re.match(r"^\s*bytes\s+(\d+)-\d+/(?:\d+|\*)\s*$", value, re.IGNORECASE)
    return int(match.group(1)) if match else None


class _RetryableError(Exception):  # noqa: N818 — internal signal
    """内部信号：本次尝试失败但可重试。"""

    def __init__(self, message: str, retry_after: Optional[float] = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class _DownloadTooLarge(Exception):  # noqa: N818 — internal signal exception, not part of public API
    """内部信号：实际字节数超过上限。不外泄给调用方。"""

    def __init__(self, written: int) -> None:
        super().__init__(f"download exceeded limit at {written} bytes")
        self.written = written


class _PartState:
    """半成品 ``.part`` + 旁车元数据的读写。"""

    def __init__(self, directory: Path, final_name: str) -> None:
        self.directory = directory
        self.final_name = final_name
        self.part_path = directory / (final_name + PART_SUFFIX)
        self.meta_path = directory / (final_name + PART_META_SUFFIX)

    def exists(self) -> bool:
        return self.part_path.is_file()

    def written(self) -> int:
        try:
            return self.part_path.stat().st_size
        except OSError:
            return 0

    def load_meta(self) -> Dict[str, Any]:
        try:
            parsed = json.loads(self.meta_path.read_text(encoding="utf-8"))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:  # noqa: BLE001 — 元数据坏了按无元数据处理（不续传）
            return {}

    def save_meta(self, meta: Dict[str, Any]) -> None:
        try:
            tmp = self.meta_path.with_name(self.meta_path.name + ".tmp")
            tmp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.meta_path)
        except Exception:  # noqa: BLE001 — 元数据写失败只影响续传，不阻断下载
            logger.debug("http_download: 写半成品元数据失败", exc_info=True)

    def discard(self) -> None:
        for path in (self.part_path, self.meta_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                logger.debug("http_download: 清理半成品失败 %s", path, exc_info=True)

    def resumable_from(self, url: str) -> Optional[Dict[str, Any]]:
        """可续传则返回元数据（含 url / etag / last_modified / total），否则 ``None``。"""
        if not self.exists() or self.written() <= 0:
            return None
        meta = self.load_meta()
        if not meta or meta.get("url") != url or not meta.get("accept_ranges"):
            return None
        return meta


class HttpDownloadTool(BaseTool):
    """http_download —— 流式下载到工作区（重试 / 续传 / 原子落盘 / 嗅探）。"""

    # 出网 + 写盘，取更严的语义：只读模式禁止，交互模式询问
    risk = RiskClass.EXTERNAL

    def __init__(
        self,
        policy: Optional[ToolPolicy] = None,
        network_policy: Optional[NetworkPolicy] = None,
    ) -> None:
        super().__init__(policy=policy)
        self._network_policy = network_policy
        # 兼容保留的常驻 client；实际请求走 _attempt 的逐跳现建 client
        # （经 http_factory 注入用户代理配置）。
        self.client = build_client(
            timeout=self._policy.timeout_seconds,
            follow_redirects=False,
            trust_env=not self._policy.subagent_only,
        )

    def _effective_network_policy(self) -> NetworkPolicy:
        if self._network_policy is not None:
            return self._network_policy
        return load_network_policy()

    def _timeout(self) -> httpx.Timeout:
        """分段超时：读超时用策略值（按块计），连接 / 写 / 池独立。"""
        read = float(self._policy.timeout_seconds or 30.0)
        return httpx.Timeout(
            connect=min(_CONNECT_TIMEOUT, read),
            read=read,
            write=_WRITE_TIMEOUT,
            pool=_POOL_TIMEOUT,
        )

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="http_download",
            description=(
                "下载文件到工作区。适用于文献 PDF、资源站附件等。"
                "filename 省略时从 URL 或 Content-Disposition 推断；"
                "只接受工作区内的相对路径。credential_domain 可携带 "
                "browser_cookies 导出的登录态（订阅源文献下载用）。"
                "内置重试（连接错误 / 超时 / 5xx / 429 指数退避）、断点续传"
                "（中断后再次调用同 URL 自动从 .part 续传）与魔数校验"
                "（期望 PDF/ZIP 却收到 HTML 登录页 / 反爬盾时报 html_instead_of_file，"
                "此时按提示换 credential_domain 或浏览器通道，不要反复重试）。"
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
                    "credential_domain": {
                        "type": "string",
                        "description": (
                            "凭据档案 domain（如 .cnki.net）：browser_cookies 导出的 cookie "
                            "或 credential_set 设置的头部凭据，命中域自动附加、跨域剥离；"
                            "过期报 credential_expired，被送到登录页报 login_required"
                        ),
                    },
                    "retries": {
                        "type": "integer",
                        "description": f"失败重试次数 (默认 {DEFAULT_RETRIES}，上限 {MAX_RETRIES}；0 = 不重试)",
                    },
                    "resume": {
                        "type": "boolean",
                        "description": "存在同名 .part 半成品时尝试 Range 续传 (默认 true)",
                    },
                    "expected_sha256": {
                        "type": "string",
                        "description": "可选：下载完成后校验 SHA-256（十六进制），不符则失败并删除文件",
                    },
                    "referer": {
                        "type": "string",
                        "description": "可选：覆盖 Referer 头（默认为目标 URL 的 origin）",
                    },
                },
                "required": ["url"],
            },
        )

    # ------------------------------------------------------------------ execute

    def execute(  # noqa: PLR0911, PLR0912 — 每个拒绝路径独立 return，扁平比提取辅助函数更直读
        self,
        url: str,
        filename: Optional[str] = None,
        max_bytes: int = MAX_DOWNLOAD_BYTES,
        credential_domain: str = "",
        retries: int = DEFAULT_RETRIES,
        resume: bool = True,
        expected_sha256: str = "",
        referer: str = "",
        **kwargs,
    ) -> ToolResult:
        """下载 ``url`` 到工作区。

        Args:
            url:       文件 URL
            filename:  工作区内相对文件名；``None`` 则自动推断
            max_bytes: 大小上限（声明值与实际字节双重校验）
            credential_domain: browser_cookies 档案 domain，附加登录态 cookie
            retries:   失败重试次数（可重试错误：连接 / 超时 / 5xx / 429）
            resume:    存在 ``.part`` 时尝试 Range 续传
            expected_sha256: 完成后校验的 SHA-256
            referer:   覆盖 Referer 头
        """
        url_error = self._validate_target_url(url)
        if url_error:
            return ToolResult(success=False, error=url_error)

        credential_headers: Optional[Dict[str, str]] = None
        if credential_domain.strip():
            from backend.tools.credential_vault import cookie_domain_matches, resolve_credential

            credential_domain = credential_domain.strip()
            resolution = resolve_credential(credential_domain, url=url)
            if resolution.status == "expired":
                return ToolResult(
                    success=False,
                    error=(
                        f"credential_expired: {credential_domain!r} 的凭据已全部过期"
                        f"（{', '.join(resolution.expired_names[:5])}）。"
                        "请在浏览器重新登录后 browser_cookies action=export，"
                        "或 credential_set 重新设置头部凭据"
                    ),
                )
            if resolution.status == "insecure_scheme":
                return ToolResult(
                    success=False,
                    error=(
                        f"credential_insecure_scheme: {credential_domain!r} 的头部凭据"
                        "不附加到明文 http 请求（仅 https 或本地回环允许）"
                    ),
                )
            if not resolution.ok or not resolution.headers:
                return ToolResult(
                    success=False,
                    error=(
                        f"credential_not_found: 无 {credential_domain!r} 的凭据档案"
                        "（先 browser_cookies action=export 导出，或 credential_set 设置头部凭据）"
                    ),
                )
            credential_headers = resolution.headers
            target_host = urlparse(url).hostname or ""
            if not cookie_domain_matches(target_host, credential_domain):
                return ToolResult(
                    success=False,
                    error=(
                        f"credential_domain_mismatch: 目标 host {target_host!r} "
                        f"不在凭据域 {credential_domain!r} 内（档案域按 cookie 归属）"
                    ),
                )

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

        expected_sha256 = (expected_sha256 or "").strip().lower()
        if expected_sha256 and not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            return ToolResult(
                success=False,
                error="invalid_expected_sha256: 须为 64 位十六进制字符串",
            )

        try:
            retries = int(retries)
        except (TypeError, ValueError):
            retries = DEFAULT_RETRIES
        retries = max(0, min(retries, MAX_RETRIES))

        network_policy = self._effective_network_policy()
        host_rejection = network_policy.check_host(url)
        if host_rejection:
            return ToolResult(success=False, error=host_rejection)

        started = time.monotonic()
        attempts = 0
        last_error = ""
        retry_after: Optional[float] = None
        ctx = _DownloadContext(
            url=url,
            filename=filename,
            max_bytes=max_bytes,
            root=Path(root),
            network_policy=network_policy,
            credential_headers=credential_headers,
            credential_domain=credential_domain.strip(),
            resume=bool(resume),
            expected_sha256=expected_sha256,
            referer=referer.strip(),
        )
        while True:
            attempts += 1
            try:
                result = self._attempt(ctx)
            except _RetryableError as exc:
                last_error = str(exc)
                retry_after = exc.retry_after
            except httpx.HTTPError as e:
                return ToolResult(success=False, error=f"HTTP 请求失败: {str(e)}")
            except Exception as e:  # noqa: BLE001 — 兜底：不可重试的失败统一包装
                return ToolResult(success=False, error=f"下载失败: {str(e)}")
            else:
                if result.success and isinstance(result.content, dict):
                    result.content["attempts"] = attempts
                    result.content["elapsed_ms"] = int((time.monotonic() - started) * 1000)
                return result

            if attempts > retries:
                break
            wait = _backoff_seconds(attempts - 1, retry_after)
            logger.info(
                "http_download: 第 %d 次尝试失败（%s），%.1fs 后重试", attempts, last_error, wait
            )
            _sleep(wait)

        suffix = "" if retries == 0 else f"（已重试 {retries} 次）"
        hint = ""
        if ctx.part_kept:
            hint = "；半成品 .part 已保留，再次调用同 URL 将自动续传"
        return ToolResult(
            success=False,
            error=f"download_failed: {last_error}{suffix}{hint}",
        )

    # ------------------------------------------------------------------ attempt

    def _attempt(self, ctx: _DownloadContext) -> ToolResult:  # noqa: PLR0911, PLR0912, PLR0915
        """一次完整尝试：重定向链 → 首块嗅探 → 流式落盘 → 完整性 → 原子改名。

        可重试的失败抛 ``_RetryableError``；不可重试的直接返回失败 ``ToolResult``
        或抛出其他异常（由 execute 包装）。
        """
        current_url = ctx.url
        for redirect_count in range(_MAX_REDIRECTS + 1):
            parsed = urlparse(current_url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                return ToolResult(
                    success=False,
                    error="无效的 URL，必须包含 http:// 或 https:// 以及主机名",
                )
            host_rejection = ctx.network_policy.check_host(current_url)
            if host_rejection:
                return ToolResult(success=False, error=host_rejection)

            hop_headers = self._hop_headers(ctx, current_url, parsed.hostname or "")

            # 续传：仅在已知落盘名（显式 filename 或上次元数据）且 .part 可用时
            part = ctx.part_for(current_url)
            resume_from = 0
            resume_meta: Optional[Dict[str, Any]] = None
            if part is not None and ctx.resume:
                resume_meta = part.resumable_from(ctx.url)
                if resume_meta:
                    resume_from = part.written()
                    hop_headers["Range"] = f"bytes={resume_from}-"
                    validator = resume_meta.get("etag") or resume_meta.get("last_modified")
                    if validator:
                        hop_headers["If-Range"] = str(validator)

            with build_client(
                timeout=self._timeout(),
                follow_redirects=False,
                verify=not ctx.network_policy.allows_insecure_tls(current_url),
                trust_env=not self._policy.subagent_only,
            ) as client:
                request = client.build_request("GET", current_url, headers=hop_headers)
                try:
                    response = client.send(request, stream=True)
                except (
                    httpx.ConnectError,
                    httpx.ConnectTimeout,
                    httpx.ReadTimeout,
                    httpx.WriteTimeout,
                    httpx.PoolTimeout,
                    httpx.RemoteProtocolError,
                    httpx.ReadError,
                    httpx.WriteError,
                ) as exc:
                    raise _RetryableError(f"{type(exc).__name__}: {exc}") from exc

                # AU2：命中域响应带 Set-Cookie → 回写档案（续期不丢）
                if "Cookie" in hop_headers and ctx.credential_domain:
                    self._writeback_set_cookies(response, current_url, ctx.credential_domain)

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
                    # AU2：带凭据却被 302 到登录 / SSO 页 → login_required
                    if ctx.credential_headers:
                        from backend.tools.credential_vault import looks_like_login_url

                        if looks_like_login_url(current_url) and not looks_like_login_url(ctx.url):
                            return ToolResult(
                                success=False,
                                error=(
                                    f"login_required: 携带 {ctx.credential_domain!r} 凭据下载仍被"
                                    f"重定向到登录页 {current_url}。凭据可能已失效：请在浏览器重新"
                                    "登录后 browser_cookies action=export 再试；或经 browser_launch + "
                                    "browser_navigate 真浏览器通道点击下载"
                                ),
                            )
                    continue

                status = response.status_code
                if status in _RETRYABLE_STATUS:
                    retry_after = _parse_retry_after(response.headers.get("retry-after"))
                    response.close()
                    raise _RetryableError(f"HTTP {status}", retry_after=retry_after)
                if status in _ANTIBOT_STATUS:
                    response.close()
                    return ToolResult(
                        success=False,
                        error=f"http_{status}: 站点拒绝访问（状态码 {status}）{_ANTIBOT_GUIDANCE}",
                    )
                if status == 416 and resume_from > 0 and part is not None:
                    # 请求范围越界：服务器认为文件已完整（.part 长度 == 总长）
                    response.close()
                    total = _parse_content_range_total(response.headers.get("content-range"))
                    if total is not None and total == resume_from:
                        return self._finalize(
                            ctx, part, resume_from, resume_meta or {}, response, resumed=True
                        )
                    # 长度对不上：半成品不可信，丢弃重下
                    part.discard()
                    raise _RetryableError("HTTP 416 且半成品长度与服务器不符，已丢弃重下")
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError:
                    response.close()
                    raise

                return self._consume(ctx, current_url, response, part, resume_from, resume_meta)

        return ToolResult(success=False, error="redirect_limit_exceeded: 重定向次数超限")

    @staticmethod
    def _writeback_set_cookies(response: httpx.Response, url: str, credential_domain: str) -> None:
        values = response.headers.get_list("set-cookie")
        if not values:
            return
        from backend.tools.credential_vault import merge_set_cookies

        try:
            merge_set_cookies(credential_domain, values, url)
        except Exception:  # noqa: BLE001 — 回写失败不影响下载
            logger.debug("Set-Cookie 回写失败", exc_info=True)

    def _hop_headers(
        self, ctx: _DownloadContext, current_url: str, hostname: str
    ) -> Dict[str, str]:
        headers: Dict[str, str] = dict(default_headers())
        # 下载不是导航：Accept 放宽为任意；identity 保证 Content-Length 可比
        headers["Accept"] = "*/*"
        headers["Accept-Encoding"] = "identity"
        parsed = urlparse(current_url)
        headers["Referer"] = ctx.referer or f"{parsed.scheme}://{parsed.netloc}/"
        # 登录态凭据（cookie / 头部）只附加到档案域命中的 hop（与 web_fetch 同口径）
        if ctx.credential_headers:
            from backend.tools.credential_vault import cookie_domain_matches

            if cookie_domain_matches(hostname, ctx.credential_domain):
                headers.update(ctx.credential_headers)
        return headers

    # ------------------------------------------------------------------ consume

    def _consume(  # noqa: PLR0911, PLR0912, PLR0915
        self,
        ctx: _DownloadContext,
        final_url: str,
        response: httpx.Response,
        part: Optional[_PartState],
        resume_from: int,
        resume_meta: Optional[Dict[str, Any]],
    ) -> ToolResult:
        """边下边写到 ``.part``；成功后校验并原子改名。"""
        try:
            status = response.status_code
            headers = response.headers
            declared_total: Optional[int] = None
            declared = headers.get("content-length", "")
            resumed = False

            if status == 206 and resume_from > 0 and part is not None:
                start = _parse_content_range_start(headers.get("content-range"))
                if start != resume_from:
                    # 服务器给的起点不是我们要的：半成品不可拼接
                    part.discard()
                    raise _RetryableError(
                        f"206 起点 {start} 与半成品长度 {resume_from} 不符，已丢弃重下"
                    )
                declared_total = _parse_content_range_total(headers.get("content-range"))
                if declared_total is None and declared.isdigit():
                    declared_total = resume_from + int(declared)
                resumed = True
            else:
                # 200（或服务器忽略 Range）：从头写；已有半成品作废
                if resume_from > 0 and part is not None:
                    part.discard()
                resume_from = 0
                if declared.isdigit():
                    declared_total = int(declared)

            if declared_total is not None and declared_total > ctx.max_bytes:
                return ToolResult(
                    success=False,
                    error=(
                        f"content_length_exceeds_limit: 服务器声明 {declared_total} 字节，"
                        f"超过上限 {ctx.max_bytes}"
                    ),
                )

            # 落盘名：显式 filename > Content-Disposition > URL 末段
            if part is None:
                name = (
                    sanitize_filename(ctx.filename)
                    if ctx.filename
                    else derive_filename(final_url, headers.get("content-disposition"))
                )
                ctx.root.mkdir(parents=True, exist_ok=True)
                target = _unique_path(ctx.root, name)
                part = _PartState(ctx.root, target.name)
                ctx.remember_part(part)

            # 首块嗅探（DL3）：期望是文件而实际是 HTML → 立即中止
            iterator = response.iter_bytes(_CHUNK_BYTES)
            first_chunk = b""
            if not resumed:
                try:
                    first_chunk = next(iterator)
                except StopIteration:
                    first_chunk = b""
                except (httpx.ReadTimeout, httpx.ReadError, httpx.RemoteProtocolError) as exc:
                    raise _RetryableError(f"{type(exc).__name__}: {exc}") from exc
                sniffed = content_sniff.sniff(
                    first_chunk[: content_sniff.SNIFF_BYTES],
                    headers.get("content-type", ""),
                    part.final_name,
                )
                if sniffed.mismatch:
                    excerpt = content_sniff.html_excerpt(first_chunk)
                    from backend.tools.credential_vault import looks_like_login_html

                    if looks_like_login_html(first_chunk.decode("utf-8", "replace")):
                        # AU2：拿到的是登录页（密码框）→ 语义更准的 login_required
                        carried = (
                            f"携带 {ctx.credential_domain!r} 凭据仍"
                            if ctx.credential_headers
                            else ""
                        )
                        return ToolResult(
                            success=False,
                            error=(
                                f"login_required: 期望 {sniffed.expected} 文件，{carried}"
                                f"收到登录页（含密码输入框）。页面摘要：{excerpt!r}。"
                                "请在浏览器登录后 browser_cookies action=export，"
                                "以 credential_domain 重试；或经浏览器通道点击下载"
                            ),
                        )
                    return ToolResult(
                        success=False,
                        error=(
                            f"html_instead_of_file: 期望 {sniffed.expected} 文件，"
                            f"服务器返回的是 HTML 页面（登录页 / 验证码 / 反爬盾 / 错误页）。"
                            f"页面摘要：{excerpt!r}{_ANTIBOT_GUIDANCE}"
                        ),
                    )

            # 元数据先落（续传依据）
            meta: Dict[str, Any] = {
                "url": ctx.url,
                "final_url": final_url,
                "etag": headers.get("etag"),
                "last_modified": headers.get("last-modified"),
                "total": declared_total,
                "accept_ranges": (headers.get("accept-ranges", "").lower() == "bytes")
                or status == 206,
                "content_type": headers.get("content-type", ""),
                "saved_at": int(time.time() * 1000),
            }
            part.save_meta(meta)

            written = resume_from
            hasher = hashlib.sha256() if (ctx.expected_sha256 and not resumed) else None
            owns_part = False
            try:
                with _open_exclusive(ctx.root, part.part_path.name, append=resumed) as handle:
                    owns_part = True
                    if first_chunk:
                        written += len(first_chunk)
                        if written > ctx.max_bytes:
                            raise _DownloadTooLarge(written)
                        handle.write(first_chunk)
                        if hasher:
                            hasher.update(first_chunk)
                    try:
                        for chunk in iterator:
                            written += len(chunk)
                            # Content-Length 是服务器说的，不可信；按实际字节兜底
                            if written > ctx.max_bytes:
                                raise _DownloadTooLarge(written)
                            handle.write(chunk)
                            if hasher:
                                hasher.update(chunk)
                    except (
                        httpx.ReadTimeout,
                        httpx.ReadError,
                        httpx.RemoteProtocolError,
                        httpx.WriteError,
                    ) as exc:
                        # 传输中断：保留 .part（若服务器支持 Range），交给重试续传
                        handle.flush()
                        ctx.part_kept = bool(meta["accept_ranges"])
                        if not ctx.part_kept:
                            part.discard()
                        raise _RetryableError(f"{type(exc).__name__}: {exc}") from exc
            except _DownloadTooLarge as exc:
                if owns_part:
                    part.discard()
                return ToolResult(
                    success=False,
                    error=f"download_exceeds_limit: 实际接收 {exc.written} 字节，超过上限 {ctx.max_bytes}",
                )
            except _RetryableError:
                raise
            except Exception:
                if owns_part:
                    part.discard()
                raise

            # 完整性：声明总长已知且不足 → 保留 .part 供续传
            if declared_total is not None and written < declared_total:
                ctx.part_kept = bool(meta["accept_ranges"])
                if not ctx.part_kept:
                    part.discard()
                raise _RetryableError(
                    f"incomplete_download: 期望 {declared_total} 字节，实际 {written}"
                )

            return self._finalize(
                ctx, part, written, meta, response, resumed=resumed, hasher=hasher
            )
        finally:
            response.close()

    def _finalize(
        self,
        ctx: _DownloadContext,
        part: _PartState,
        written: int,
        meta: Dict[str, Any],
        response: httpx.Response,
        resumed: bool,
        hasher: Optional[Any] = None,
    ) -> ToolResult:
        """校验 sha256（如需）→ 原子改名 → 记录产物。"""
        digest: Optional[str] = None
        if ctx.expected_sha256:
            digest = _sha256_file(part.part_path) if hasher is None else hasher.hexdigest()
            if digest != ctx.expected_sha256:
                part.discard()
                ctx.part_kept = False
                return ToolResult(
                    success=False,
                    error=(
                        f"sha256_mismatch: 期望 {ctx.expected_sha256}，实际 {digest}"
                        "（文件已删除）"
                    ),
                )

        target = ctx.root / part.final_name
        if target.exists():
            # 竞争：下载期间有人占了最终名 → 换名，不覆盖
            target = _unique_path(ctx.root, part.final_name)
        part.part_path.replace(target)
        with contextlib.suppress(OSError):
            part.meta_path.unlink()
        ctx.part_kept = False

        self._record_artifact(str(target), written)
        content: Dict[str, Any] = {
            "url": meta.get("final_url") or ctx.url,
            "path": str(target),
            "filename": target.name,
            "bytes_written": written,
            "content_type": meta.get("content_type") or response.headers.get("content-type", ""),
            "resumed": resumed,
        }
        if meta.get("total") is not None:
            content["total_bytes"] = meta["total"]
        if digest is not None:
            content["sha256"] = digest
        return ToolResult(success=True, content=content, output=str(target))

    # ------------------------------------------------------------------ misc

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


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(str(path), "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


class _DownloadContext:
    """一次 execute 内跨重试共享的状态。"""

    def __init__(
        self,
        url: str,
        filename: Optional[str],
        max_bytes: int,
        root: Path,
        network_policy: NetworkPolicy,
        credential_headers: Optional[Dict[str, str]],
        credential_domain: str,
        resume: bool,
        expected_sha256: str,
        referer: str,
    ) -> None:
        self.url = url
        self.filename = filename
        self.max_bytes = max_bytes
        self.root = root
        self.network_policy = network_policy
        self.credential_headers = credential_headers
        self.credential_domain = credential_domain
        self.resume = resume
        self.expected_sha256 = expected_sha256
        self.referer = referer
        #: 跨重试记住的半成品（首次尝试确定文件名后固定）
        self._part: Optional[_PartState] = None
        #: 失败时 .part 是否保留（决定错误文案的续传提示）
        self.part_kept = False

    def remember_part(self, part: _PartState) -> None:
        self._part = part

    def part_for(self, current_url: str) -> Optional[_PartState]:
        """本次尝试应使用的半成品。

        已记住的优先；否则按可预知的名字（显式 filename，或当前 hop URL 末段）
        查找元数据匹配本 URL 的 ``.part``。Content-Disposition 给出的名字无法在
        请求前预知，这类下载首次中断后不可续传（重下），属明示限制。
        """
        if self._part is not None:
            return self._part
        if not self.resume:
            return None
        candidates = []
        if self.filename:
            candidates.append(sanitize_filename(self.filename))
        else:
            candidates.append(derive_filename(current_url))
            if current_url != self.url:
                candidates.append(derive_filename(self.url))
        for name in candidates:
            candidate = _PartState(self.root, name)
            if candidate.resumable_from(self.url) and not (self.root / name).exists():
                self._part = candidate
                return candidate
        return None


__all__ = [
    "DEFAULT_RETRIES",
    "MAX_DOWNLOAD_BYTES",
    "MAX_RETRIES",
    "PART_META_SUFFIX",
    "PART_SUFFIX",
    "HttpDownloadTool",
    "derive_filename",
    "sanitize_filename",
]
