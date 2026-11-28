# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""受控浏览器安全层（M4）。

四块能力：

- **站点授权**：持久策略（``browser_site_policies`` JSON）与会话级临时
  授权；导航前由工具层查询，返回 allow / confirm / block。
- **敏感动作分类**：把 browser_interact 的（action + 元素元数据）映射为
  ok / confirm / hard_block 三档，硬性禁止项不允许经由用户确认放行。
- **注入告警**：对页面文本做提示注入特征扫描，命中只告警不阻断。
- **待确认登记**：线程安全的 confirmation 注册表，带 pending / 批准 /
  拒绝三套 TTL；批准是一次性指纹，拒绝在 TTL 内持续生效。

设计约束：本模块不依赖浏览器层，持久化失败只记录日志（读失败按空策略
处理），保证浏览器动作链路不会因安全层自身异常而崩溃。
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

#: 站点策略持久化 key（SettingsRepository 白名单内）
SETTINGS_KEY_SITE_POLICIES = "browser_site_policies"

#: 待确认有效期（秒）
PENDING_TTL_SECONDS = 600.0
#: 一次性批准有效期（秒）
APPROVAL_TTL_SECONDS = 120.0
#: 拒绝指纹有效期（秒）—— 期间同一操作不再重复弹确认
DENIAL_TTL_SECONDS = 300.0

SITE_ACCESS_OPTIONS: Tuple[str, ...] = ("session", "always", "deny")
SENSITIVE_ACTION_OPTIONS: Tuple[str, ...] = ("approve", "deny")

_VALID_POLICY_MODES = ("allow", "block")
_VALID_GRANT_MODES = ("session", "always", "block")

_MAX_DESCRIPTION = 120


def _now() -> float:
    """单调时钟（单测可 monkeypatch 推进 TTL）。"""
    return time.monotonic()


def _wall_ms() -> int:
    return int(time.time() * 1000)


def _truncate(text: str, limit: int = _MAX_DESCRIPTION) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)] + "…"


# ---------------------------------------------------------------------------
# 站点策略
# ---------------------------------------------------------------------------


def normalize_domain(value: str) -> str:
    """把主机名（或 URL）归一为小写、去端口、去末点的域名。"""
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if "//" in raw:
        raw = raw.split("//", 1)[1]
    raw = raw.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    # 去掉 userinfo 与端口（IPv6 字面量不在受控浏览器的常见范围）
    if "@" in raw:
        raw = raw.rsplit("@", 1)[1]
    if raw.startswith("["):
        end = raw.find("]")
        return raw[: end + 1] if end > 0 else raw
    return raw.split(":", 1)[0].rstrip(".")


def domain_of(url: str) -> str:
    """从 URL 取域名；about:/data: 等无主机 scheme 返回空串。"""
    try:
        parts = urlsplit(str(url or "").strip())
    except ValueError:
        return ""
    return normalize_domain(parts.hostname or "")


def _load_policies() -> Dict[str, Dict[str, Any]]:
    """读取持久策略；任何失败按空策略（fail-open，不阻断浏览器）。"""
    try:
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get_json(SETTINGS_KEY_SITE_POLICIES)
    except Exception:  # noqa: BLE001 — 设置读取失败不阻断浏览器动作
        logger.debug("读取 browser_site_policies 失败", exc_info=True)
        return {}
    if not isinstance(raw, dict):
        return {}
    policies: Dict[str, Dict[str, Any]] = {}
    for domain, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        mode = str(entry.get("mode") or "").strip().lower()
        if mode not in _VALID_POLICY_MODES:
            continue
        policies[normalize_domain(str(domain))] = {
            "mode": mode,
            "updated_at": int(entry.get("updated_at") or 0),
        }
    return policies


def _save_policies(policies: Dict[str, Dict[str, Any]]) -> None:
    try:
        from backend.data.settings_repo import SettingsRepository

        SettingsRepository().set_json(SETTINGS_KEY_SITE_POLICIES, policies)
    except Exception:  # noqa: BLE001 — 持久化失败只记录，不抛给调用方
        logger.warning("写入 browser_site_policies 失败", exc_info=True)


#: 会话级临时授权：session_id -> {domain}
_SESSION_GRANTS: Dict[str, Set[str]] = {}
_SESSION_LOCK = threading.Lock()


def check_site(session_id: str, url: str) -> str:
    """导航前站点判定：``allow`` / ``confirm`` / ``block``。

    优先级：持久 block > 持久 allow > 会话授权 > 默认需确认。
    无主机名的 scheme（about:/data:）直接放行。
    """
    domain = domain_of(url)
    if not domain:
        return "allow"
    policies = _load_policies()
    entry = policies.get(domain)
    if entry is not None:
        return "allow" if entry["mode"] == "allow" else "block"
    with _SESSION_LOCK:
        grants = set(_SESSION_GRANTS.get(session_id or "", set()))
    return "allow" if domain in grants else "confirm"


def grant_site(session_id: str, domain: str, mode: str) -> None:
    """授予站点访问：``session``（临时）/ ``always``（持久允许）/ ``block``（持久禁止）。"""
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in _VALID_GRANT_MODES:
        raise ValueError(f"未知授权模式: {mode}（合法值：{'|'.join(_VALID_GRANT_MODES)}）")
    normalized_domain = normalize_domain(domain)
    if not normalized_domain:
        raise ValueError("domain 不能为空")
    if normalized_mode == "session":
        with _SESSION_LOCK:
            _SESSION_GRANTS.setdefault(session_id or "", set()).add(normalized_domain)
        return
    policies = _load_policies()
    policies[normalized_domain] = {
        "mode": "allow" if normalized_mode == "always" else "block",
        "updated_at": _wall_ms(),
    }
    _save_policies(policies)


def list_site_policies() -> List[Dict[str, Any]]:
    """持久策略列表（按域名排序），供设置页展示。"""
    policies = _load_policies()
    return [
        {"domain": domain, "mode": entry["mode"], "updated_at": entry["updated_at"]}
        for domain, entry in sorted(policies.items())
    ]


def set_site_policy(domain: str, mode: str) -> Dict[str, Any]:
    """直接写一条持久策略（REST PUT 用）；返回落库后的条目。"""
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in _VALID_POLICY_MODES:
        raise ValueError(f"未知策略模式: {mode}（合法值：{'|'.join(_VALID_POLICY_MODES)}）")
    normalized_domain = normalize_domain(domain)
    if not normalized_domain:
        raise ValueError("domain 不能为空")
    entry = {"mode": normalized_mode, "updated_at": _wall_ms()}
    policies = _load_policies()
    policies[normalized_domain] = entry
    _save_policies(policies)
    return {"domain": normalized_domain, "mode": entry["mode"], "updated_at": entry["updated_at"]}


def remove_site_policy(domain: str) -> bool:
    """删除持久策略；返回是否确实删除了条目。"""
    normalized_domain = normalize_domain(domain)
    if not normalized_domain:
        return False
    policies = _load_policies()
    if normalized_domain not in policies:
        return False
    del policies[normalized_domain]
    _save_policies(policies)
    return True


def reset_session(session_id: str) -> None:
    """清理会话级授权与待确认登记（浏览器关闭时调用）。"""
    with _SESSION_LOCK:
        _SESSION_GRANTS.pop(session_id or "", None)
    reset_confirmations_for_session(session_id)


def reset_site_policies_for_tests() -> None:
    """测试隔离：清空进程内会话授权。"""
    with _SESSION_LOCK:
        _SESSION_GRANTS.clear()


# ---------------------------------------------------------------------------
# 敏感动作分类
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SafetyVerdict:
    """分类结论：kind = ok / confirm / hard_block。"""

    kind: str
    code: str
    description: str


_PASSWORD_TYPE = re.compile(r"^password$", re.IGNORECASE)
_CREDENTIAL_WORDS = re.compile(
    r"(otp|验证码|卡号|card\s*number|cvv|cvc|安全码)", re.IGNORECASE
)
_PAYMENT_WORDS = re.compile(
    r"(支付|付款|购买|下单|转账|充值|checkout|pay\s*now|purchase|transfer\s*money)",
    re.IGNORECASE,
)
_ACCOUNT_CREATE_WORDS = re.compile(
    r"(注册|创建账号|sign\s*up|register\s*account|create\s*account)", re.IGNORECASE
)
_ACCOUNT_DELETE_WORDS = re.compile(
    r"(注销账户|删除账户|delete\s*account)", re.IGNORECASE
)
_SUBMIT_WORDS = re.compile(
    r"(提交|发送|发布|确认|同意|授权|订阅|submit|send|publish|confirm|authorize|subscribe)",
    re.IGNORECASE,
)
_DESTRUCTIVE_WORDS = re.compile(r"(删除|移除|delete|remove)", re.IGNORECASE)

_HARD_BLOCK_DESCRIPTIONS = {
    "password_entry": "禁止代填密码，请接管",
    "sensitive_credential": "禁止填写验证码/银行卡等敏感凭据，请接管",
    "payment": "禁止执行支付/转账类操作，请接管",
    "account_creation": "禁止代替用户注册/创建账号，请接管",
    "account_deletion": "禁止删除/注销账号，请接管",
}


def _target_label(target: Optional[Dict[str, Any]]) -> str:
    if not isinstance(target, dict):
        return ""
    parts = [
        target.get("name"),
        target.get("placeholder"),
        target.get("aria_label"),
        target.get("role"),
        target.get("tag"),
    ]
    return " ".join(str(part) for part in parts if part)


def _target_type(target: Optional[Dict[str, Any]]) -> str:
    if not isinstance(target, dict):
        return ""
    return str(target.get("type") or "").strip().lower()


def _verdict(kind: str, code: str, description: str) -> SafetyVerdict:
    return SafetyVerdict(kind=kind, code=code, description=_truncate(description))


def classify_interact(  # noqa: PLR0911 — 每个分类分支独立返回，扁平更直读
    action: str,
    *,
    target: Optional[Dict[str, Any]],
    value: str = "",
    selector: str = "",
    key: str = "",
    metadata_unavailable: bool = False,
) -> SafetyVerdict:
    """把交互动作分类为 ok / confirm / hard_block。

    ``hard_block`` 仅覆盖明确的高危动作（密码、敏感凭据、支付、注册/
    注销账号）；其余敏感动作一律降级为 ``confirm``，由用户确认放行。

    ``press`` 仅 Enter/Return 会触发焦点元素的默认提交/点击语义，按
    ``click`` 同口径分类；其他按键放行。``metadata_unavailable`` 表示
    调用方提供了定位但读不到目标元数据且无 text 名称 —— 对可产生副作用
    的动作 fail-closed 为 ``confirm``（``safety_unknown``），避免只读 JS
    失败时密码框/支付按钮被误判为 ok。
    """
    normalized_action = str(action or "").strip().lower()
    label = _target_label(target)
    target_type = _target_type(target)

    if normalized_action == "press":
        if str(key or "").strip().lower() not in ("enter", "return"):
            return _verdict("ok", "", "")
        # Enter/Return 触发焦点元素默认动作 → 与 click 同一分类路径
        normalized_action = "click"

    if normalized_action == "upload":
        return _verdict("confirm", "file_upload", "上传文件需用户确认")

    if metadata_unavailable and not label and normalized_action in (
        "type",
        "click",
        "select",
        "check",
        "uncheck",
    ):
        return _verdict("confirm", "safety_unknown", "无法确认目标元素，请确认后执行")

    if normalized_action == "type":
        if _PASSWORD_TYPE.match(target_type):
            return _verdict(
                "hard_block", "password_entry", _HARD_BLOCK_DESCRIPTIONS["password_entry"]
            )
        if _CREDENTIAL_WORDS.search(label):
            return _verdict(
                "hard_block",
                "sensitive_credential",
                _HARD_BLOCK_DESCRIPTIONS["sensitive_credential"],
            )
        return _verdict("ok", "", "")

    if normalized_action == "click":
        if _PAYMENT_WORDS.search(label):
            return _verdict("hard_block", "payment", _HARD_BLOCK_DESCRIPTIONS["payment"])
        if _ACCOUNT_CREATE_WORDS.search(label):
            return _verdict(
                "hard_block", "account_creation", _HARD_BLOCK_DESCRIPTIONS["account_creation"]
            )
        if _ACCOUNT_DELETE_WORDS.search(label):
            return _verdict(
                "hard_block", "account_deletion", _HARD_BLOCK_DESCRIPTIONS["account_deletion"]
            )
        if _SUBMIT_WORDS.search(label):
            return _verdict("confirm", "sensitive_submit", f"提交/发送类操作需确认：{label}")
        if _DESTRUCTIVE_WORDS.search(label):
            return _verdict("confirm", "destructive_click", f"删除/移除类操作需确认：{label}")
        return _verdict("ok", "", "")

    if normalized_action in ("select", "check", "uncheck"):
        if (
            _PAYMENT_WORDS.search(label)
            or _ACCOUNT_CREATE_WORDS.search(label)
            or _ACCOUNT_DELETE_WORDS.search(label)
            or _SUBMIT_WORDS.search(label)
            or _DESTRUCTIVE_WORDS.search(label)
        ):
            return _verdict("confirm", "sensitive_submit", f"敏感选择/勾选需确认：{label}")
        return _verdict("ok", "", "")

    return _verdict("ok", "", "")


# ---------------------------------------------------------------------------
# 提示注入告警
# ---------------------------------------------------------------------------

#: 提示注入特征（英文 / 中文），命中即告警，不阻断
INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"忽略(之前|以上|上面)的?(所有)?(指示|指令)"),
    re.compile(r"system\s*prompt", re.IGNORECASE),
    re.compile(r"系统提示"),
    re.compile(r"你现在是"),
    re.compile(r"you\s+are\s+now", re.IGNORECASE),
    re.compile(r"请立即执行"),
    re.compile(r"do\s+not\s+tell\s+the\s+user", re.IGNORECASE),
    re.compile(r"不要告诉用户"),
)

_INJECTION_CONTEXT_BEFORE = 20
_INJECTION_CONTEXT_AFTER = 60


def scan_untrusted_text(text: str) -> Optional[str]:
    """扫描不可信页面文本；命中返回告警摘要（含上下文片段），否则 None。"""
    if not isinstance(text, str) or not text:
        return None
    for pattern in INJECTION_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        start = max(0, match.start() - _INJECTION_CONTEXT_BEFORE)
        end = min(len(text), match.end() + _INJECTION_CONTEXT_AFTER)
        snippet = re.sub(r"\s+", " ", text[start:end]).strip()
        return _truncate(f"疑似提示注入：…{snippet}…")
    return None


# ---------------------------------------------------------------------------
# 待确认登记（线程安全）
# ---------------------------------------------------------------------------

#: 确认条内嵌缩略图上限（字节）与最长边（像素）。缩略图位于数据目录，
#: 不在 sage-file:// 白名单内，因此由后端直接内联为 data URL。
THUMBNAIL_MAX_BYTES = 100 * 1024
THUMBNAIL_MAX_EDGE = 320
#: 不尝试读取超过该大小的源截图（异常大的文件不值得内联）
_THUMBNAIL_SOURCE_MAX_BYTES = 8 * 1024 * 1024


def _encode_thumbnail(data: bytes) -> str:
    """把截图字节压成 ≤``THUMBNAIL_MAX_BYTES`` 的 data URL；不可行返回空串。

    Pillow 是可选依赖（随 OCR 引擎附带，不做硬依赖）：可用时降采样到
    ``THUMBNAIL_MAX_EDGE`` 并按 PNG→JPEG 质量阶梯压缩；不可用时只在原文件
    本身 ≤100KB 时直接 base64。
    """
    try:
        from PIL import Image  # type: ignore
    except Exception:  # noqa: BLE001 — Pillow 缺失按无缩放路径处理
        Image = None  # type: ignore[assignment]
    if Image is not None:
        try:
            with Image.open(io.BytesIO(data)) as source:
                img = source.convert("RGB") if source.mode not in ("RGB", "RGBA", "L") else source
                width, height = img.size
                long_edge = max(width, height)
                if long_edge > THUMBNAIL_MAX_EDGE:
                    scale = THUMBNAIL_MAX_EDGE / float(long_edge)
                    img = img.resize(
                        (max(1, int(width * scale)), max(1, int(height * scale)))
                    )
                buf = io.BytesIO()
                img.save(buf, format="PNG", optimize=True)
                thumb = buf.getvalue()
                mime = "image/png"
                if len(thumb) > THUMBNAIL_MAX_BYTES:
                    # JPEG 不支持 alpha；先转 RGB（PNG 阶段保留透明度）。
                    jpeg_img = img if img.mode == "RGB" else img.convert("RGB")
                    for quality in (70, 55, 40):
                        buf = io.BytesIO()
                        jpeg_img.save(buf, format="JPEG", quality=quality, optimize=True)
                        thumb = buf.getvalue()
                        mime = "image/jpeg"
                        if len(thumb) <= THUMBNAIL_MAX_BYTES:
                            break
                if len(thumb) <= THUMBNAIL_MAX_BYTES:
                    encoded = base64.b64encode(thumb).decode("ascii")
                    return f"data:{mime};base64,{encoded}"
        except Exception:  # noqa: BLE001 — 解码失败退回原文件判断
            logger.debug("确认缩略图压缩失败", exc_info=True)
    if len(data) <= THUMBNAIL_MAX_BYTES:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            mime = "image/png"
        elif data[:3] == b"\xff\xd8\xff":
            mime = "image/jpeg"
        else:
            mime = "application/octet-stream"
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    return ""


@lru_cache(maxsize=32)
def _thumbnail_data_url(path: str, mtime_ns: int, size: int) -> str:
    """按 (path, mtime, size) 缓存的缩略图 data URL；读取失败返回空串。"""
    del mtime_ns, size  # 仅作为缓存键
    try:
        with open(path, "rb") as handle:
            data = handle.read(_THUMBNAIL_SOURCE_MAX_BYTES + 1)
    except OSError:
        return ""
    if not data or len(data) > _THUMBNAIL_SOURCE_MAX_BYTES:
        return ""
    return _encode_thumbnail(data)


def _thumbnail_for_path(path: str) -> str:
    """读取截图路径对应的内联缩略图；文件不存在/不可读返回空串。"""
    if not path:
        return ""
    try:
        stat = Path(path).stat()
    except OSError:
        return ""
    return _thumbnail_data_url(path, int(stat.st_mtime_ns), int(stat.st_size))


@dataclass
class PendingConfirmation:
    """一条等待用户裁决的确认项。"""

    id: str
    session_id: str
    kind: str  # site_access | sensitive_action
    code: str
    domain: str
    description: str
    options: List[str] = field(default_factory=list)
    screenshot_path: str = ""
    fingerprint: str = ""
    # 创建时所属聊天对话（服务端裁决归属校验用）；旧条目为空串。
    conversation_id: str = ""
    created_at: float = 0.0

    def to_public_dict(self) -> Dict[str, Any]:
        """REST 序列化：不暴露内部指纹；截图以有界 data URL 内联。"""
        public: Dict[str, Any] = {
            "id": self.id,
            "session_id": self.session_id,
            "kind": self.kind,
            "code": self.code,
            "domain": self.domain,
            "description": self.description,
            "options": list(self.options),
            "screenshot_path": self.screenshot_path,
            "conversation_id": self.conversation_id,
            "created_at": self.created_at,
        }
        thumbnail = _thumbnail_for_path(self.screenshot_path)
        if thumbnail:
            public["thumbnail_data_url"] = thumbnail
        elif self.screenshot_path:
            public["thumbnail_unavailable"] = True
        return public


class ConfirmationRegistry:
    """线程安全的待确认登记表 + 一次性批准/拒绝指纹。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # id -> (pending, expires_at)
        self._pending: Dict[str, Tuple[PendingConfirmation, float]] = {}
        # fingerprint -> (expires_at, session_id)
        self._approvals: Dict[str, Tuple[float, str]] = {}
        # fingerprint -> (expires_at, session_id)
        self._denials: Dict[str, Tuple[float, str]] = {}

    def _purge(self, now: float) -> None:
        for key in [key for key, (_item, exp) in self._pending.items() if exp <= now]:
            self._pending.pop(key, None)
        for key in [key for key, (exp, _sid) in self._approvals.items() if exp <= now]:
            self._approvals.pop(key, None)
        for key in [key for key, (exp, _sid) in self._denials.items() if exp <= now]:
            self._denials.pop(key, None)

    def create(
        self,
        session_id: str,
        kind: str,
        *,
        code: str = "",
        domain: str = "",
        description: str = "",
        options: Optional[List[str]] = None,
        screenshot_path: str = "",
        fingerprint: str = "",
        conversation_id: str = "",
    ) -> PendingConfirmation:
        now = _now()
        pending = PendingConfirmation(
            id=uuid.uuid4().hex,
            session_id=session_id,
            kind=kind,
            code=code,
            domain=domain,
            description=_truncate(description),
            options=list(options or ()),
            screenshot_path=screenshot_path or "",
            fingerprint=fingerprint or "",
            conversation_id=conversation_id or "",
            created_at=time.time(),
        )
        with self._lock:
            self._purge(now)
            self._pending[pending.id] = (pending, now + PENDING_TTL_SECONDS)
        return pending

    def get(self, confirmation_id: str) -> Optional[PendingConfirmation]:
        now = _now()
        with self._lock:
            self._purge(now)
            item = self._pending.get(confirmation_id)
            return item[0] if item else None

    def list(
        self,
        session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> List[PendingConfirmation]:
        """列举待确认项；``conversation_id`` 给出时按对话过滤并优先于 session。

        HTTP 出网门禁创建的确认项没有浏览器实例（``session_id`` 为空），
        仅按对话过滤才能让右栏面板看到它们。
        """
        now = _now()
        with self._lock:
            self._purge(now)
            items = [item for item, _exp in self._pending.values()]
        if conversation_id is not None:
            items = [item for item in items if item.conversation_id == conversation_id]
        elif session_id is not None:
            items = [item for item in items if item.session_id == session_id]
        return sorted(items, key=lambda item: item.created_at)

    def resolve(self, confirmation_id: str, decision: str) -> Optional[PendingConfirmation]:
        """弹出待确认项并按 decision 登记批准/拒绝指纹；未知 id 返回 None。"""
        now = _now()
        normalized = str(decision or "").strip().lower()
        with self._lock:
            self._purge(now)
            entry = self._pending.pop(confirmation_id, None)
            if entry is None:
                return None
            pending = entry[0]
            if pending.fingerprint:
                if normalized == "approve":
                    self._approvals[pending.fingerprint] = (
                        now + APPROVAL_TTL_SECONDS,
                        pending.session_id,
                    )
                elif normalized == "deny":
                    self._denials[pending.fingerprint] = (
                        now + DENIAL_TTL_SECONDS,
                        pending.session_id,
                    )
        return pending

    def consume_approval(self, fingerprint: str, session_id: Optional[str] = None) -> bool:
        """消费一次性批准（命中即删除）；过期/缺失/会话不匹配返回 False。

        ``session_id`` 提供时强校验批准所属会话：指纹本身已包含会话，
        这里再做一次防御性比对，避免调用方手工构造指纹时跨会话复用。
        """
        if not fingerprint:
            return False
        now = _now()
        with self._lock:
            self._purge(now)
            entry = self._approvals.get(fingerprint)
            if entry is None:
                return False
            if session_id is not None and entry[1] != session_id:
                return False
            self._approvals.pop(fingerprint, None)
            return True

    def is_denied(self, fingerprint: str, session_id: Optional[str] = None) -> bool:
        """该指纹是否处于用户拒绝的有效期内（可选按会话强校验）。"""
        if not fingerprint:
            return False
        now = _now()
        with self._lock:
            self._purge(now)
            entry = self._denials.get(fingerprint)
            if entry is None:
                return False
            if session_id is not None and entry[1] != session_id:
                return False
            return True

    def reset_session(self, session_id: str) -> None:
        """清理某会话的待确认项、批准与拒绝指纹。"""
        with self._lock:
            for key in [
                key for key, (item, _exp) in self._pending.items() if item.session_id == session_id
            ]:
                self._pending.pop(key, None)
            for key in [
                key for key, (_exp, sid) in self._approvals.items() if sid == session_id
            ]:
                self._approvals.pop(key, None)
            for key in [
                key for key, (_exp, sid) in self._denials.items() if sid == session_id
            ]:
                self._denials.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._pending.clear()
            self._approvals.clear()
            self._denials.clear()


_REGISTRY: Optional[ConfirmationRegistry] = None
_REGISTRY_LOCK = threading.Lock()


def get_confirmation_registry() -> ConfirmationRegistry:
    """进程级单例（线程安全懒初始化）。"""
    global _REGISTRY
    if _REGISTRY is None:
        with _REGISTRY_LOCK:
            if _REGISTRY is None:
                _REGISTRY = ConfirmationRegistry()
    return _REGISTRY


def reset_confirmations_for_tests() -> None:
    """测试隔离：丢弃单例（清空全部登记与指纹）。"""
    global _REGISTRY
    with _REGISTRY_LOCK:
        _REGISTRY = None


def reset_confirmations_for_session(session_id: str) -> None:
    """清理某会话的待确认项（浏览器关闭时调用）。"""
    get_confirmation_registry().reset_session(session_id or "")


def action_fingerprint(
    tool: str,
    action: str,
    domain: str = "",
    ref: str = "",
    selector: str = "",
    target_name: str = "",
    session_id: str = "",
    scope: str = "",
) -> str:
    """操作指纹：
    ``sha256(tool|action|domain|ref 或 selector|target_name|session_id|scope)``。

    - ``session_id`` 把批准/拒绝绑定到具体浏览器会话，防止跨会话复用；
    - ``scope`` 承载动作参数（upload 的解析后路径 / select 的目标值），
      防止「批准上传 A 文件」被重放为上传 B 文件。
    """
    locator = ref or selector or ""
    raw = "|".join(
        [
            str(tool or ""),
            str(action or ""),
            str(domain or ""),
            str(locator),
            str(target_name or ""),
            str(session_id or ""),
            str(scope or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
