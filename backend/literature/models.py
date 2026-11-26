"""文献站点 profile 与检索结果的领域模型（Python 3.8 兼容）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote, urlparse

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HTTP_SCHEMES = ("http", "https")
_ACCESS_MODES = frozenset({"browser", "rest", "hybrid"})
_SEARCH_MODES = frozenset({"url", "interactive"})
_PROFILE_STATUSES = frozenset({"ready", "draft"})
_URL_FROM_DECODES = frozenset({"none", "base64", "url"})


class SiteProfileError(ValueError):
    """站点 profile 无效或不可用。"""


@dataclass(frozen=True)
class SiteField:
    selector: str = ""
    attr: str = "text"


@dataclass(frozen=True)
class LoginSpec:
    method: str = "manual"
    url: Optional[str] = None
    account_label: Optional[str] = None
    password_label: Optional[str] = None
    url_contains: Optional[str] = None
    title_not_contains: Optional[str] = None


@dataclass(frozen=True)
class AccessSpec:
    mode: str = "browser"
    login: LoginSpec = field(default_factory=LoginSpec)


@dataclass(frozen=True)
class PaginationSpec:
    type: str = "click_text"
    text: str = ""


@dataclass(frozen=True)
class SearchSpec:
    url_template: str = ""
    wait_for: Tuple[str, ...] = ()
    pagination: Optional[PaginationSpec] = None
    result_fields: Dict[str, SiteField] = field(default_factory=dict)
    mode: str = "url"
    entry_url: Optional[str] = None
    entry_click: Optional[str] = None
    input_selectors: Tuple[str, ...] = ()
    submit_key: str = "Enter"
    wait_after_s: float = 0.0
    result_hint: str = ""


@dataclass(frozen=True)
class UrlFromSpec:
    """从结果行链接中推导详情/摘要页 URL 的声明式规则。

    适用于「结果链接是跳转/代理地址，真正的详情页 URL 藏在其某个查询参数里」的站点：
    读取 ``selector`` 命中的元素 href，取查询参数 ``param``，按 ``decode`` 解码后即为详情页 URL。
    """

    selector: str = ""
    param: str = ""
    decode: str = "none"


@dataclass(frozen=True)
class DetailSpec:
    open_by: str = "click_text"
    fields: Dict[str, SiteField] = field(default_factory=dict)
    url_from: Optional[UrlFromSpec] = None


@dataclass(frozen=True)
class PdfInterstitialSpec:
    """下载中间页声明：入口先落到「准备中」页、随后再跳最终下载地址的站点。

    ``url_contains`` 用于在标签页 URL 中识别中间页/最终跳转地址；
    ``host_fallbacks`` 是在最终地址上依次替换主机的回退列表（原域放最后兜底）。
    """

    url_contains: Tuple[str, ...] = ()
    host_fallbacks: Tuple[str, ...] = ()
    tab_timeout_s: float = 6.0
    sleep_after_open_s: float = 2.5
    attempt_timeout_s: float = 15.0


@dataclass(frozen=True)
class PdfSpec:
    entry_selector: Optional[str] = None
    entry_text: Optional[str] = None
    forbid: Tuple[str, ...] = ("CAJ",)
    magic: str = "%PDF-"
    title_match: bool = True
    post_click_wait_s: float = 0.0
    interstitial: Optional[PdfInterstitialSpec] = None
    note: Optional[str] = None


@dataclass(frozen=True)
class RateLimitSpec:
    min_interval_s: int = 5
    max_batch: int = 20


@dataclass(frozen=True)
class ComplianceSpec:
    note: str = ""
    default_enabled: bool = False


@dataclass(frozen=True)
class SiteProfile:
    id: str
    display_name: str
    home_url: str
    domains: Tuple[str, ...]
    access: AccessSpec = field(default_factory=AccessSpec)
    capabilities: Dict[str, bool] = field(default_factory=dict)
    search: SearchSpec = field(default_factory=SearchSpec)
    detail: Optional[DetailSpec] = None
    pdf: Optional[PdfSpec] = None
    rate_limit: RateLimitSpec = field(default_factory=RateLimitSpec)
    compliance: ComplianceSpec = field(default_factory=ComplianceSpec)
    version: str = "1"
    status: str = "ready"
    last_verified_at: Optional[str] = None
    source_path: Optional[str] = None
    source_layer: str = "builtin"


@dataclass(frozen=True)
class PaperRecord:
    """跨站点统一的文献记录；下游去重/证据/核验只认这个结构。"""

    paper_key: str
    title: str
    authors: Tuple[str, ...] = ()
    year: Optional[str] = None
    venue: Optional[str] = None
    abstract: Optional[str] = None
    url: Optional[str] = None
    doi: Optional[str] = None
    source_site: str = ""
    source_query: Optional[str] = None
    retrieved_at: Optional[str] = None
    fulltext_path: Optional[str] = None
    language: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "paper_key": self.paper_key,
            "title": self.title,
            "authors": list(self.authors),
            "year": self.year,
            "venue": self.venue,
            "abstract": self.abstract,
            "url": self.url,
            "doi": self.doi,
            "source_site": self.source_site,
            "source_query": self.source_query,
            "retrieved_at": self.retrieved_at,
            "fulltext_path": self.fulltext_path,
            "language": self.language,
            "extra": dict(self.extra),
        }


def _require_dict(value: Any, field_name: str) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SiteProfileError(f"{field_name} 必须是对象")
    return value


def _require_str(value: Any, field_name: str, *, required: bool = False) -> str:
    if value is None:
        if required:
            raise SiteProfileError(f"{field_name} 必填")
        return ""
    if not isinstance(value, str):
        raise SiteProfileError(f"{field_name} 必须是字符串")
    text = value.strip()
    if required and not text:
        raise SiteProfileError(f"{field_name} 不能为空")
    return text


def _optional_str(value: Any, field_name: str) -> Optional[str]:
    text = _require_str(value, field_name)
    return text or None


def _str_tuple(value: Any, field_name: str) -> Tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):  # noqa: UP038 — py38 兼容 tuple isinstance
        raise SiteProfileError(f"{field_name} 必须是字符串数组")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise SiteProfileError(f"{field_name} 不能包含空值")
        result.append(item.strip())
    return tuple(result)


def _site_field(value: Any, field_name: str) -> SiteField:
    if isinstance(value, str):
        return SiteField(selector=value.strip())
    raw = _require_dict(value, field_name)
    return SiteField(
        selector=_require_str(raw.get("selector"), f"{field_name}.selector"),
        attr=_require_str(raw.get("attr"), f"{field_name}.attr") or "text",
    )


def _site_fields(value: Any, field_name: str) -> Dict[str, SiteField]:
    raw = _require_dict(value, field_name)
    return {str(key): _site_field(item, f"{field_name}.{key}") for key, item in raw.items()}


def _parse_url_from(value: Any) -> Optional[UrlFromSpec]:
    if value is None:
        return None
    data = _require_dict(value, "detail.url_from")
    selector = _require_str(data.get("selector"), "detail.url_from.selector", required=True)
    param = _require_str(data.get("param"), "detail.url_from.param", required=True)
    decode = _require_str(data.get("decode"), "detail.url_from.decode") or "none"
    if decode not in _URL_FROM_DECODES:
        raise SiteProfileError(
            f"detail.url_from.decode 必须是 {sorted(_URL_FROM_DECODES)} 之一"
        )
    return UrlFromSpec(selector=selector, param=param, decode=decode)


def _validate_http_url(value: str, field_name: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in _HTTP_SCHEMES or not parsed.netloc:
        raise SiteProfileError(f"{field_name} 必须是 http(s) URL: {value!r}")
    return value


def _parse_login(raw: Any) -> LoginSpec:
    data = _require_dict(raw, "access.login")
    return LoginSpec(
        method=_require_str(data.get("method"), "access.login.method") or "manual",
        url=_optional_str(data.get("url"), "access.login.url"),
        account_label=_optional_str(data.get("account_label"), "access.login.account_label"),
        password_label=_optional_str(
            data.get("password_label"), "access.login.password_label"
        ),
        url_contains=_optional_str(data.get("url_contains"), "access.login.url_contains"),
        title_not_contains=_optional_str(
            data.get("title_not_contains"), "access.login.title_not_contains"
        ),
    )


def _parse_pdf_interstitial(raw: Any) -> Optional[PdfInterstitialSpec]:
    if raw is None:
        return None
    data = _require_dict(raw, "pdf.interstitial")
    url_contains = _str_tuple(data.get("url_contains"), "pdf.interstitial.url_contains")
    if not url_contains:
        raise SiteProfileError("pdf.interstitial.url_contains 不能为空")
    return PdfInterstitialSpec(
        url_contains=url_contains,
        host_fallbacks=_str_tuple(
            data.get("host_fallbacks"), "pdf.interstitial.host_fallbacks"
        ),
        tab_timeout_s=float(data.get("tab_timeout_s", 6.0)),
        sleep_after_open_s=float(data.get("sleep_after_open_s", 2.5)),
        attempt_timeout_s=float(data.get("attempt_timeout_s", 15.0)),
    )


def _parse_pdf(raw: Any) -> Optional[PdfSpec]:
    if raw is None:
        return None
    data = _require_dict(raw, "pdf")
    entry = data.get("entry")
    entry_selector = None
    entry_text = None
    if isinstance(entry, str):
        entry_selector = entry.strip()
    elif isinstance(entry, dict):
        entry_selector = _optional_str(entry.get("selector"), "pdf.entry.selector")
        entry_text = _optional_str(entry.get("text"), "pdf.entry.text")
    validate = _require_dict(data.get("validate"), "pdf.validate")
    return PdfSpec(
        entry_selector=entry_selector,
        entry_text=entry_text,
        forbid=_str_tuple(data.get("forbid"), "pdf.forbid") or ("CAJ",),
        magic=_require_str(validate.get("magic"), "pdf.validate.magic") or "%PDF-",
        title_match=bool(validate.get("title_match", True)),
        post_click_wait_s=float(data.get("post_click_wait_s", 0.0)),
        interstitial=_parse_pdf_interstitial(data.get("interstitial")),
        note=_optional_str(data.get("note"), "pdf.note"),
    )


def profile_from_dict(
    raw: Dict[str, Any],
    source_path: Optional[str] = None,
    source_layer: str = "builtin",
) -> SiteProfile:
    """把 YAML dict 校验并转成 SiteProfile；失败抛 SiteProfileError。"""
    if not isinstance(raw, dict):
        raise SiteProfileError("profile 根节点必须是对象")

    site_id = _require_str(raw.get("id"), "id", required=True)
    if not _ID_RE.match(site_id):
        raise SiteProfileError(
            f"id 必须是小写字母/数字/连字符（且以字母或数字开头）: {site_id!r}"
        )

    home_url = _validate_http_url(
        _require_str(raw.get("home_url"), "home_url", required=True), "home_url"
    )
    domains = tuple(domain.lower() for domain in _str_tuple(raw.get("domains"), "domains"))
    if not domains:
        raise SiteProfileError("domains 不能为空")
    for domain in domains:
        if "://" in domain or "/" in domain or " " in domain:
            raise SiteProfileError(f"domains 只能写主机名（不带协议/路径）: {domain!r}")

    access_raw = _require_dict(raw.get("access"), "access")
    mode = _require_str(access_raw.get("mode"), "access.mode") or "browser"
    if mode not in _ACCESS_MODES:
        raise SiteProfileError(
            f"access.mode 必须是 {sorted(_ACCESS_MODES)} 之一，收到 {mode!r}"
        )
    access = AccessSpec(mode=mode, login=_parse_login(access_raw.get("login")))

    search_raw = _require_dict(raw.get("search"), "search")
    capabilities = {
        str(key): bool(value)
        for key, value in _require_dict(raw.get("capabilities"), "capabilities").items()
    }
    url_template = _require_str(search_raw.get("url_template"), "search.url_template")
    mode = _require_str(search_raw.get("mode"), "search.mode") or "url"
    if mode not in _SEARCH_MODES:
        raise SiteProfileError(
            f"search.mode 必须是 {sorted(_SEARCH_MODES)} 之一，收到 {mode!r}"
        )
    entry_url = _optional_str(search_raw.get("entry_url"), "search.entry_url")
    entry_click = _optional_str(search_raw.get("entry_click"), "search.entry_click")
    input_selectors = _str_tuple(
        search_raw.get("input_selectors"), "search.input_selectors"
    )
    submit_key = _require_str(search_raw.get("submit_key"), "search.submit_key") or "Enter"
    wait_after_s = float(search_raw.get("wait_after_s", 0.0))
    result_hint = _require_str(search_raw.get("result_hint"), "search.result_hint")
    if capabilities.get("search", True):
        if mode == "url":
            if not url_template:
                raise SiteProfileError("search.url_template 必填")
            if "{query}" not in url_template:
                raise SiteProfileError("search.url_template 必须包含 {query} 占位符")
        else:
            if not (entry_url or url_template):
                raise SiteProfileError(
                    "interactive 模式需要 search.entry_url 或 search.url_template"
                )
            if not input_selectors:
                raise SiteProfileError(
                    "interactive 模式需要 search.input_selectors"
                )
            if wait_after_s < 0:
                raise SiteProfileError("search.wait_after_s 不能为负")

    pagination_raw = search_raw.get("pagination")
    pagination = None
    if pagination_raw is not None:
        data = _require_dict(pagination_raw, "search.pagination")
        pagination = PaginationSpec(
            type=_require_str(data.get("type"), "search.pagination.type") or "click_text",
            text=_require_str(data.get("text"), "search.pagination.text"),
        )

    detail_raw = raw.get("detail")
    detail = None
    if detail_raw is not None:
        data = _require_dict(detail_raw, "detail")
        detail = DetailSpec(
            open_by=_require_str(data.get("open_by"), "detail.open_by") or "click_text",
            fields=_site_fields(data.get("fields"), "detail.fields"),
            url_from=_parse_url_from(data.get("url_from")),
        )

    rate_raw = _require_dict(raw.get("rate_limit"), "rate_limit")
    compliance_raw = _require_dict(raw.get("compliance"), "compliance")
    last_verified_at = _optional_str(raw.get("last_verified_at"), "last_verified_at")
    if last_verified_at is not None and not _DATE_RE.match(last_verified_at):
        raise SiteProfileError("last_verified_at 必须是 YYYY-MM-DD")

    status = _require_str(raw.get("status"), "status") or "ready"
    if status not in _PROFILE_STATUSES:
        raise SiteProfileError(f"status 必须是 {sorted(_PROFILE_STATUSES)} 之一")

    return SiteProfile(
        id=site_id,
        display_name=_require_str(
            raw.get("display_name"), "display_name", required=True
        ),
        home_url=home_url,
        domains=domains,
        access=access,
        capabilities=capabilities,
        search=SearchSpec(
            url_template=url_template,
            wait_for=_str_tuple(search_raw.get("wait_for"), "search.wait_for"),
            pagination=pagination,
            result_fields=_site_fields(
                search_raw.get("result_fields"), "search.result_fields"
            ),
            mode=mode,
            entry_url=entry_url,
            entry_click=entry_click,
            input_selectors=input_selectors,
            submit_key=submit_key,
            wait_after_s=wait_after_s,
            result_hint=result_hint,
        ),
        detail=detail,
        pdf=_parse_pdf(raw.get("pdf")),
        rate_limit=RateLimitSpec(
            min_interval_s=int(rate_raw.get("min_interval_s", 5)),
            max_batch=int(rate_raw.get("max_batch", 20)),
        ),
        compliance=ComplianceSpec(
            note=_require_str(compliance_raw.get("note"), "compliance.note"),
            default_enabled=bool(compliance_raw.get("default_enabled", False)),
        ),
        version=_require_str(raw.get("version"), "version") or "1",
        status=status,
        last_verified_at=last_verified_at,
        source_path=source_path,
        source_layer=source_layer,
    )


def is_allowed_host(host: str, domains: Tuple[str, ...]) -> bool:
    host = (host or "").lower().strip(".")
    if not host:
        return False
    for domain in domains:
        normalized = domain.lower().strip(".")
        if host == normalized or host.endswith("." + normalized):
            return True
    return False


def render_search_url(profile: SiteProfile, query: str, limit: int = 10) -> str:
    """渲染检索 URL；校验 scheme 与域名，防止 profile 指向任意主机。"""
    text = (query or "").strip()
    if not text:
        raise SiteProfileError("query 不能为空")
    template = profile.search.url_template
    if not template:
        raise SiteProfileError(f"站点 {profile.id} 未配置 search.url_template")

    try:
        url = template.format(query=quote(text, safe=""), limit=str(int(limit)))
    except (KeyError, ValueError) as exc:
        raise SiteProfileError(
            f"站点 {profile.id} 的 search.url_template 渲染失败: {exc}"
        ) from exc

    parsed = urlparse(url)
    if parsed.scheme not in _HTTP_SCHEMES or not parsed.hostname:
        raise SiteProfileError(f"检索 URL 必须是 http(s): {url!r}")
    if not is_allowed_host(parsed.hostname, profile.domains):
        raise SiteProfileError(
            f"检索 URL 域名 {parsed.hostname!r} 不在站点域名 {list(profile.domains)} 内"
        )
    return url


def is_logged_in(
    profile: SiteProfile,
    page_url: Optional[str],
    page_title: Optional[str],
) -> Optional[bool]:
    """根据 profile 的登录态检查返回 True/False；未配置检查时返回 None。"""
    login = profile.access.login
    checks = []
    if login.url_contains:
        checks.append(login.url_contains in (page_url or ""))
    if login.title_not_contains:
        checks.append(login.title_not_contains not in (page_title or ""))
    if not checks:
        return None
    return all(checks)
