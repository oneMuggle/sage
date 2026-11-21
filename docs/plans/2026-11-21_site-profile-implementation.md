# SiteProfile 可插拔文献站点适配层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用声明式 YAML profile + 通用适配器把文献站点变成可插拔配置，xueshu789 作为首个实测样例，新增站点不改流水线代码。

**Architecture:** 新增 `backend/literature/` 纯 Python 层：领域模型（SiteProfile / PaperRecord）、三级 profile 存储（内置 / 用户 / 项目，后者覆盖前者）、LLM 指导文本渲染、以及一个 duck-typed 的 `ProfileBackedAdapter`。现有 `academic_adapters.get_site_adapter()` 在未命中内置适配器时回退到 profile 存储，从而让现有 `AcademicSearchSkill` 无需改动即可使用 xueshu789 等站点。站点差异只存在于 YAML 与可选 skill 说明，禁止在 pipeline 写站点分支。

**Tech Stack:** Python 3.10（开发）/ 3.8（release/win7 兼容写法）；PyYAML 6（已在 `backend/requirements.txt`）；dataclasses；pytest。

**Spec:** `docs/plans/2026-11-21_literature-research-paper-pipeline.md`（§5.3.1 站点适配协议）

## Global Constraints

- 代码必须同时兼容 Python 3.10（main）与 Python 3.8（release/win7）：使用 `typing.Optional/List/Dict/Tuple`，禁止 `X | Y`、`list[X]` 等 PEP 604/585 语法。
- 不新增第三方依赖；YAML 使用已有的 `pyyaml==6.0.1`。
- 行宽 100；双引号（ruff Q000）；提交前跑 `ruff check`。
- `backend/literature/` 不得 import `backend.tools` / `backend.api`；领域模型零后端依赖。
- 禁止在 pipeline / adapter 中写 `if site == "xueshu789"` 之类站点分支。
- 站点差异只允许出现在：`backend/literature/sites/*.yaml`、用户 profile、可选 skill `references/` 说明、窄接口脚本。
- 不捕获裸 `Exception`；只捕获明确的 `SiteProfileError` / `yaml.YAMLError` / `OSError`，避免触发 silent-exceptions 门禁。
- 测试必须 hermetic：不依赖 `~/.sage/` 或当前工作区真实 profile；用 `tmp_path` + `SAGE_LITERATURE_SITES_DIR` + `monkeypatch.chdir`。
- 合规：profile 可携带第三方站点（如 xueshu789），但默认 `default_enabled: false`；仅使用用户本人账号/机构授权；不绕过付费墙；验证码交还用户。

---

## File Structure

**Create**
- `backend/literature/__init__.py` — 包导出
- `backend/literature/models.py` — SiteProfile / PaperRecord / 校验 / URL 渲染 / 登录判断
- `backend/literature/profile_store.py` — 三级 profile 发现、加载、覆盖、错误收集
- `backend/literature/guidance.py` — 把 profile 渲染成给 LLM 的检索指导
- `backend/literature/academic_adapter.py` — `ProfileBackedAdapter`
- `backend/literature/sites/xueshu789.yaml` — 首个实测样例（draft 选择器待录制）
- `backend/literature/README.md` — schema 与新增站点指南
- `backend/tests/unit/test_literature_site_profiles.py` — 全部单测

**Modify**
- `backend/skills/builtin/academic_adapters.py` — `get_site_adapter()` 未命中时回退 profile store
- `docs/plans/2026-11-21_literature-research-paper-pipeline.md` — 标注 M0 已实施部分（完成后）

**Carry-over（已在主检出完成、未提交）**
- `backend/tools/browser_tool.py` — navigate/login 路径应用下载目录
- `electron/agentBrowserHost.ts` — http(s) 弹窗放行 + 下载兜底

---

## Task 0: 带走浏览器下载/弹窗修复并提交

**Files:**
- Modify: `backend/tools/browser_tool.py`
- Modify: `electron/agentBrowserHost.ts`

**Interfaces:**
- Consumes: 无
- Produces: xueshu789 下载链路所需的行为（navigate/login 自动设置下载目录；http(s) 弹窗不被无条件拒绝）

- [ ] **Step 1: 确认工作区已包含补丁**

Run:
```bash
cd /home/fz/project/sage/.worktrees/feat-literature-research-pipeline
git diff --stat
```
Expected: 两个文件有改动（browser_tool.py +27，agentBrowserHost.ts +36/-7）。

- [ ] **Step 2: 后端语法检查**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m py_compile backend/tools/browser_tool.py
```
Expected: 无输出、退出码 0。

- [ ] **Step 3: 跑相关后端测试**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit -k "browser" -q
```
Expected: 通过（若存在环境性失败，记录并继续）。

- [ ] **Step 4: Commit**

```bash
git add backend/tools/browser_tool.py electron/agentBrowserHost.ts
git commit -m "fix(browser): ensure download dir for auto-launched sessions and allow http(s) popups"
```

---

## Task 1: 领域模型、URL 渲染与登录判断

**Files:**
- Create: `backend/literature/__init__.py`
- Create: `backend/literature/models.py`
- Test: `backend/tests/unit/test_literature_site_profiles.py`

**Interfaces:**
- Produces:
  - `SiteProfileError(ValueError)`
  - `SiteProfile`（字段见下）
  - `PaperRecord.to_dict() -> Dict[str, Any]`
  - `profile_from_dict(raw: Dict[str, Any], source_path: Optional[str] = None, source_layer: str = "builtin") -> SiteProfile`
  - `render_search_url(profile: SiteProfile, query: str, limit: int = 10) -> str`
  - `is_logged_in(profile: SiteProfile, page_url: Optional[str], page_title: Optional[str]) -> Optional[bool]`

- [ ] **Step 1: 写失败测试**

Create `backend/tests/unit/test_literature_site_profiles.py`:

```python
"""SiteProfile 领域模型 / 存储 / 适配器单元测试。"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from backend.literature.models import (
    PaperRecord,
    SiteProfileError,
    is_logged_in,
    profile_from_dict,
    render_search_url,
)

pytestmark = pytest.mark.unit


def _raw_profile(**overrides):
    raw = {
        "id": "demo",
        "display_name": "Demo 学术站",
        "home_url": "https://demo.example/",
        "domains": ["demo.example"],
        "access": {
            "mode": "browser",
            "login": {
                "method": "form",
                "account_label": "卡号",
                "password_label": "密码",
                "url_contains": "/home/",
                "title_not_contains": "登录",
            },
        },
        "capabilities": {"search": True, "pdf_download": True},
        "search": {
            "url_template": "https://demo.example/search?q={query}&n={limit}",
            "wait_for": [".result-list"],
            "result_fields": {"title": {"selector": ".title"}},
        },
        "pdf": {"entry": {"selector": "a.downloadlink"}, "forbid": ["CAJ"]},
        "compliance": {"note": "仅个人学习", "default_enabled": False},
    }
    raw.update(overrides)
    return raw


class TestProfileModel:
    def test_minimal_profile_parses(self):
        profile = profile_from_dict(_raw_profile())
        assert profile.id == "demo"
        assert profile.display_name == "Demo 学术站"
        assert profile.access.mode == "browser"
        assert profile.access.login.account_label == "卡号"
        assert profile.search.wait_for == (".result-list",)
        assert profile.pdf is not None
        assert profile.pdf.entry_selector == "a.downloadlink"
        assert profile.status == "ready"
        assert profile.source_layer == "builtin"

    def test_rejects_invalid_id(self):
        with pytest.raises(SiteProfileError, match="id"):
            profile_from_dict(_raw_profile(id="Bad ID"))

    def test_rejects_missing_domains(self):
        with pytest.raises(SiteProfileError, match="domains"):
            profile_from_dict(_raw_profile(domains=[]))

    def test_rejects_unknown_access_mode(self):
        raw = _raw_profile()
        raw["access"]["mode"] = "magic"
        with pytest.raises(SiteProfileError, match="access.mode"):
            profile_from_dict(raw)

    def test_rejects_url_template_without_query_placeholder(self):
        raw = _raw_profile()
        raw["search"]["url_template"] = "https://demo.example/search"
        with pytest.raises(SiteProfileError, match="\\{query\\}"):
            profile_from_dict(raw)

    def test_rejects_non_http_home_url(self):
        with pytest.raises(SiteProfileError, match="home_url"):
            profile_from_dict(_raw_profile(home_url="file:///etc/passwd"))

    def test_rejects_bad_last_verified_at(self):
        with pytest.raises(SiteProfileError, match="last_verified_at"):
            profile_from_dict(_raw_profile(last_verified_at="2026/11/21"))


class TestUrlRendering:
    def test_encodes_chinese_query_and_limit(self):
        profile = profile_from_dict(_raw_profile())
        url = render_search_url(profile, "机器学习 综述", limit=5)
        parsed = urlparse(url)
        assert parsed.netloc == "demo.example"
        qs = parse_qs(parsed.query)
        assert qs["q"] == ["机器学习 综述"]
        assert qs["n"] == ["5"]

    def test_rejects_empty_query(self):
        profile = profile_from_dict(_raw_profile())
        with pytest.raises(SiteProfileError, match="query"):
            render_search_url(profile, "   ")

    def test_rejects_host_outside_domains(self):
        profile = profile_from_dict(_raw_profile())
        object.__setattr__(profile.search, "url_template", "https://evil.example/x?q={query}")
        with pytest.raises(SiteProfileError, match="域名"):
            render_search_url(profile, "x")


class TestLoginCheck:
    def test_logged_in_when_all_checks_pass(self):
        profile = profile_from_dict(_raw_profile())
        assert is_logged_in(profile, "https://demo.example/home/1", "文献列表") is True

    def test_not_logged_in_when_url_check_fails(self):
        profile = profile_from_dict(_raw_profile())
        assert is_logged_in(profile, "https://demo.example/login", "文献列表") is False

    def test_not_logged_in_when_title_check_fails(self):
        profile = profile_from_dict(_raw_profile())
        assert is_logged_in(profile, "https://demo.example/home/1", "登录 - Demo") is False

    def test_unknown_when_no_checks_configured(self):
        raw = _raw_profile()
        raw["access"]["login"] = {"method": "manual"}
        profile = profile_from_dict(raw)
        assert is_logged_in(profile, None, None) is None


class TestPaperRecord:
    def test_round_trip_to_dict(self):
        record = PaperRecord(
            paper_key="doi:10.1000/demo",
            title="示例论文",
            authors=("张三", "李四"),
            year="2026",
            source_site="demo",
            source_query="示例",
        )
        data = record.to_dict()
        assert data["authors"] == ["张三", "李四"]
        assert data["paper_key"] == "doi:10.1000/demo"
        assert data["source_site"] == "demo"
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
cd /home/fz/project/sage/.worktrees/feat-literature-research-pipeline
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_site_profiles.py -q
```
Expected: `ModuleNotFoundError: No module named 'backend.literature'`。

- [ ] **Step 3: 实现模型**

Create `backend/literature/__init__.py`:

```python
"""文献调研领域层：站点 profile、检索结果模型与适配器。

设计约束：本包不依赖 backend.tools / backend.api；站点差异放在 profile
（YAML）里，而不是代码分支里。
"""

from .models import (
    PaperRecord,
    SiteProfile,
    SiteProfileError,
    is_logged_in,
    profile_from_dict,
    render_search_url,
)

__all__ = [
    "PaperRecord",
    "SiteProfile",
    "SiteProfileError",
    "is_logged_in",
    "profile_from_dict",
    "render_search_url",
]
```

Create `backend/literature/models.py`:

```python
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
_PROFILE_STATUSES = frozenset({"ready", "draft"})


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


@dataclass(frozen=True)
class DetailSpec:
    open_by: str = "click_text"
    fields: Dict[str, SiteField] = field(default_factory=dict)


@dataclass(frozen=True)
class PdfSpec:
    entry_selector: Optional[str] = None
    entry_text: Optional[str] = None
    forbid: Tuple[str, ...] = ("CAJ",)
    magic: str = "%PDF-"
    title_match: bool = True


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
    if not isinstance(value, (list, tuple)):
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
    if capabilities.get("search", True):
        if not url_template:
            raise SiteProfileError("search.url_template 必填")
        if "{query}" not in url_template:
            raise SiteProfileError("search.url_template 必须包含 {query} 占位符")

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
        domain = domain.lower().strip(".")
        if host == domain or host.endswith("." + domain):
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
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_site_profiles.py -q
```
Expected: 全部通过。

- [ ] **Step 5: Ruff**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/ruff check backend/literature backend/tests/unit/test_literature_site_profiles.py
```
Expected: 无错误（必要时用 `--config backend/ruff.toml`）。

- [ ] **Step 6: Commit**

```bash
git add backend/literature/__init__.py backend/literature/models.py backend/tests/unit/test_literature_site_profiles.py
git commit -m "feat(literature): add site profile domain model and URL rendering"
```

---

## Task 2: 三级 profile 存储与覆盖

**Files:**
- Create: `backend/literature/profile_store.py`
- Test: `backend/tests/unit/test_literature_site_profiles.py`（追加）

**Interfaces:**
- Consumes: `SiteProfile`, `SiteProfileError`, `profile_from_dict`（Task 1）
- Produces:
  - `ProfileRoot(path: Path, layer: str)`
  - `SiteProfileStore(roots: Sequence[ProfileRoot]).discover() -> Dict[str, SiteProfile]`
  - `.get(site_id) -> SiteProfile`（未找到/无效抛 `SiteProfileError`）
  - `.list_ids() -> List[str]`
  - `.reload() -> None`
  - `get_default_store() -> SiteProfileStore`
  - `reset_default_store() -> None`（测试用）

- [ ] **Step 1: 追加失败测试**

在 `backend/tests/unit/test_literature_site_profiles.py` 末尾追加：

```python
class TestProfileStore:
    @staticmethod
    def _write(root: Path, filename: str, site_id: str, title: str) -> None:
        root.mkdir(parents=True, exist_ok=True)
        body = (
            f"id: {site_id}\n"
            f"display_name: {title}\n"
            "home_url: https://demo.example/\n"
            "domains: [demo.example]\n"
            "search:\n"
            "  url_template: https://demo.example/s?q={query}\n"
        )
        (root / filename).write_text(body, encoding="utf-8")

    def test_precedence_project_over_user_over_builtin(self, tmp_path):
        from backend.literature.profile_store import ProfileRoot, SiteProfileStore

        builtin = tmp_path / "builtin"
        user = tmp_path / "user"
        project = tmp_path / "project"
        self._write(builtin, "demo.yaml", "demo", "Builtin")
        self._write(user, "demo.yaml", "demo", "User")
        self._write(project, "demo.yaml", "demo", "Project")

        store = SiteProfileStore(
            [
                ProfileRoot(builtin, "builtin"),
                ProfileRoot(user, "user"),
                ProfileRoot(project, "project"),
            ]
        )
        profiles = store.discover()
        assert profiles["demo"].display_name == "Project"
        assert profiles["demo"].source_layer == "project"

    def test_invalid_profile_is_skipped_and_get_raises(self, tmp_path):
        from backend.literature.profile_store import ProfileRoot, SiteProfileStore

        root = tmp_path / "sites"
        root.mkdir()
        (root / "bad.yaml").write_text("id: Bad ID\n", encoding="utf-8")
        self._write(root, "good.yaml", "good", "Good")

        store = SiteProfileStore([ProfileRoot(root, "user")])
        profiles = store.discover()
        assert "good" in profiles
        with pytest.raises(SiteProfileError, match="无效"):
            store.get("bad")

    def test_get_unknown_lists_available(self, tmp_path):
        from backend.literature.profile_store import ProfileRoot, SiteProfileStore

        root = tmp_path / "sites"
        self._write(root, "good.yaml", "good", "Good")
        store = SiteProfileStore([ProfileRoot(root, "user")])
        with pytest.raises(SiteProfileError, match="good"):
            store.get("missing")

    def test_default_store_uses_env_dir(self, tmp_path, monkeypatch):
        from backend.literature import profile_store

        user_dir = tmp_path / "user-sites"
        self._write(user_dir, "envsite.yaml", "envsite", "Env Site")
        monkeypatch.setenv("SAGE_LITERATURE_SITES_DIR", str(user_dir))
        monkeypatch.chdir(tmp_path)
        profile_store.reset_default_store()

        store = profile_store.get_default_store()
        assert "envsite" in store.list_ids()
        profile_store.reset_default_store()
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_site_profiles.py -q
```
Expected: `ModuleNotFoundError` 或 `ImportError: profile_store`。

- [ ] **Step 3: 实现存储**

Create `backend/literature/profile_store.py`:

```python
"""三级站点 profile 存储：内置 < 用户 < 项目（后者覆盖前者）。"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence

import yaml

from .models import SiteProfile, SiteProfileError, profile_from_dict

logger = logging.getLogger(__name__)

_YAML_SUFFIXES = frozenset({".yaml", ".yml"})


class ProfileRoot(NamedTuple):
    path: Path
    layer: str


def _user_sites_dir() -> Path:
    env_dir = os.environ.get("SAGE_LITERATURE_SITES_DIR", "").strip()
    if env_dir:
        return Path(env_dir).expanduser()
    return Path.home() / ".sage" / "literature_sites"


class SiteProfileStore:
    """从多个根目录加载 profile；同 id 以更晚的根（项目）为准。"""

    def __init__(self, roots: Sequence[ProfileRoot]):
        self._roots = list(roots)
        self._profiles: Optional[Dict[str, SiteProfile]] = None
        self._errors: Dict[str, SiteProfileError] = {}

    @classmethod
    def default(cls) -> "SiteProfileStore":
        return cls(
            [
                ProfileRoot(Path(__file__).parent / "sites", "builtin"),
                ProfileRoot(_user_sites_dir(), "user"),
                ProfileRoot(Path.cwd() / ".sage" / "literature_sites", "project"),
            ]
        )

    def reload(self) -> None:
        self._profiles = None
        self._errors = {}

    def discover(self) -> Dict[str, SiteProfile]:
        if self._profiles is not None:
            return dict(self._profiles)

        profiles: Dict[str, SiteProfile] = {}
        errors: Dict[str, SiteProfileError] = {}

        for root in self._roots:
            if not root.path.is_dir():
                continue
            try:
                entries = sorted(root.path.iterdir())
            except OSError as exc:
                logger.warning("读取站点 profile 目录失败 %s: %s", root.path, exc)
                continue

            for path in entries:
                if path.name.startswith(".") or path.suffix.lower() not in _YAML_SUFFIXES:
                    continue
                if not path.is_file():
                    continue
                try:
                    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                    profile = profile_from_dict(
                        raw, source_path=str(path), source_layer=root.layer
                    )
                except SiteProfileError as exc:
                    errors[path.stem] = exc
                    logger.warning("跳过无效站点 profile %s: %s", path, exc)
                    continue
                except yaml.YAMLError as exc:
                    errors[path.stem] = SiteProfileError(f"YAML 解析失败: {exc}")
                    logger.warning("跳过无法解析的站点 profile %s: %s", path, exc)
                    continue
                except OSError as exc:
                    errors[path.stem] = SiteProfileError(f"读取失败: {exc}")
                    logger.warning("读取站点 profile 失败 %s: %s", path, exc)
                    continue
                profiles[profile.id] = profile

        self._profiles = profiles
        self._errors = errors
        return dict(profiles)

    def get(self, site_id: str) -> SiteProfile:
        self.discover()
        if site_id in self._errors:
            raise SiteProfileError(
                f"站点 {site_id!r} 的 profile 无效: {self._errors[site_id]}"
            )
        assert self._profiles is not None
        try:
            return self._profiles[site_id]
        except KeyError:
            raise SiteProfileError(
                f"未找到站点 profile: {site_id!r}. Available: {sorted(self._profiles)}"
            ) from None

    def list_ids(self) -> List[str]:
        self.discover()
        assert self._profiles is not None
        return sorted(self._profiles)


_DEFAULT_STORE: Optional[SiteProfileStore] = None


def get_default_store() -> SiteProfileStore:
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = SiteProfileStore.default()
    return _DEFAULT_STORE


def reset_default_store() -> None:
    global _DEFAULT_STORE
    _DEFAULT_STORE = None
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_site_profiles.py -q
```
Expected: 全部通过。

- [ ] **Step 5: Ruff + Commit**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/ruff check backend/literature backend/tests/unit/test_literature_site_profiles.py
git add backend/literature/profile_store.py backend/tests/unit/test_literature_site_profiles.py
git commit -m "feat(literature): add three-tier site profile store with precedence"
```

---

## Task 3: LLM 检索指导渲染

**Files:**
- Create: `backend/literature/guidance.py`
- Test: `backend/tests/unit/test_literature_site_profiles.py`（追加）

**Interfaces:**
- Consumes: `SiteProfile`, `render_search_url`, `is_logged_in`
- Produces: `render_search_guidance(profile, query, limit=10, page_url=None, page_title=None) -> str`

- [ ] **Step 1: 追加失败测试**

```python
class TestGuidance:
    def test_contains_site_login_selectors_and_compliance(self):
        from backend.literature.guidance import render_search_guidance
        profile = profile_from_dict(_raw_profile())
        text = render_search_guidance(profile, "机器学习", limit=5)
        assert "Demo 学术站" in text
        assert "demo.example" in text
        assert "卡号" in text
        assert ".result-list" in text
        assert "a.downloadlink" in text
        assert "仅个人学习" in text
        assert "{query}" not in text

    def test_reports_login_state(self):
        from backend.literature.guidance import render_search_guidance
        profile = profile_from_dict(_raw_profile())
        logged = render_search_guidance(
            profile, "x", page_url="https://demo.example/home/1", page_title="文献列表"
        )
        assert "登录态: 已登录" in logged
        anonymous = render_search_guidance(
            profile, "x", page_url="https://demo.example/login", page_title="登录"
        )
        assert "登录态: 未登录" in anonymous
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_site_profiles.py -q
```
Expected: `ModuleNotFoundError: backend.literature.guidance`。

- [ ] **Step 3: 实现 guidance**

Create `backend/literature/guidance.py`:

```python
"""把 SiteProfile 渲染成给 LLM 的检索指导（不执行浏览器）。"""

from __future__ import annotations

from typing import Optional

from .models import SiteField, SiteProfile, is_logged_in, render_search_url


def _selector_text(field: SiteField) -> str:
    return field.selector.strip() if field.selector.strip() else "（待录制）"


def _fields_lines(fields: dict) -> str:
    if not fields:
        return "（未配置，按页面语义自行识别并标注待复核）"
    return "\n".join(f"- {name}: {_selector_text(field)}" for name, field in fields.items())


def render_search_guidance(
    profile: SiteProfile,
    query: str,
    limit: int = 10,
    page_url: Optional[str] = None,
    page_title: Optional[str] = None,
) -> str:
    """生成检索阶段的 LLM 指导文本；真实页面解析仍由 LLM 基于 snapshot 完成。"""
    search_url = render_search_url(profile, query, limit=limit)
    login_state = is_logged_in(profile, page_url, page_title)
    if login_state is True:
        login_line = "登录态: 已登录"
    elif login_state is False:
        login_line = "登录态: 未登录（先调用 browser_login 完成登录，再继续）"
    else:
        login_line = "登录态: 未知（请先用 browser_snapshot 检查页面）"

    login = profile.access.login
    login_hint = []
    if login.account_label:
        login_hint.append(f"账号输入框提示: {login.account_label}")
    if login.password_label:
        login_hint.append(f"密码输入框提示: {login.password_label}")
    if login.url_contains:
        login_hint.append(f"登录成功 URL 应包含: {login.url_contains}")
    if login.title_not_contains:
        login_hint.append(f"登录后标题不应包含: {login.title_not_contains}")

    wait_for = ", ".join(profile.search.wait_for) or "（未配置）"
    pagination = (
        f"{profile.search.pagination.type}: {profile.search.pagination.text}"
        if profile.search.pagination
        else "（未配置）"
    )
    detail = (
        f"{profile.detail.open_by}；字段:\n{_fields_lines(profile.detail.fields)}"
        if profile.detail
        else "（未配置）"
    )
    pdf = "（未配置）"
    if profile.pdf:
        entry = profile.pdf.entry_selector or profile.pdf.entry_text or "（待录制）"
        pdf = (
            f"入口: {entry}；禁止: {', '.join(profile.pdf.forbid)}；"
            f"校验: magic={profile.pdf.magic}, title_match={profile.pdf.title_match}"
        )

    return (
        f"站点: {profile.display_name} ({profile.id})\n"
        f"profile 状态: {profile.status}"
        f"{'，选择器待录制' if profile.status == 'draft' else ''}\n"
        f"检索 URL: {search_url}\n"
        f"{login_line}\n"
        + ("\n".join(login_hint) + "\n" if login_hint else "")
        + f"结果等待选择器: {wait_for}\n"
        f"翻页方式: {pagination}\n"
        f"结果字段:\n{_fields_lines(profile.search.result_fields)}\n"
        f"详情打开: {detail}\n"
        f"PDF 下载: {pdf}\n"
        f"限速: 每篇间隔 >= {profile.rate_limit.min_interval_s}s；单批 <= {profile.rate_limit.max_batch} 篇\n"
        f"合规: {profile.compliance.note or '遵守站点条款与机构授权'}\n\n"
        "请基于 browser_snapshot 解析结果，输出 JSON 数组，每项字段: "
        "paper_key, title, authors, year, venue, abstract, url, doi。"
        "不要编造页面中不存在的文献或字段；不确定的字段留空并在 extra 标注。"
    )
```

- [ ] **Step 4: 运行测试 + Ruff + Commit**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_site_profiles.py -q
/home/fz/anaconda3/envs/sage-backend/bin/ruff check backend/literature backend/tests/unit/test_literature_site_profiles.py
git add backend/literature/guidance.py backend/tests/unit/test_literature_site_profiles.py
git commit -m "feat(literature): render profile-driven search guidance for LLM"
```

---

## Task 4: ProfileBackedAdapter 与 get_site_adapter 集成

**Files:**
- Create: `backend/literature/academic_adapter.py`
- Modify: `backend/skills/builtin/academic_adapters.py`
- Test: `backend/tests/unit/test_literature_site_profiles.py`（追加）

**Interfaces:**
- Consumes: `SiteProfile`, `render_search_url`, `render_search_guidance`
- Produces:
  - `ProfileBackedAdapter(profile).name -> str`
  - `.profile -> SiteProfile`
  - `.build_search_url(query, **kwargs) -> str`
  - `.render_guidance(query, **kwargs) -> str`
  - 现有 `get_site_adapter(name)` 对未注册名称回退 profile store

- [ ] **Step 1: 追加失败测试**

```python
class TestProfileBackedAdapter:
    def test_satisfies_existing_adapter_protocol(self):
        from backend.literature.academic_adapter import ProfileBackedAdapter
        from backend.skills.builtin.academic_adapters import AcademicSiteAdapter

        profile = profile_from_dict(_raw_profile())
        adapter = ProfileBackedAdapter(profile)
        assert adapter.name == "demo"
        assert isinstance(adapter, AcademicSiteAdapter)
        assert "demo.example" in adapter.build_search_url("x")
        assert "Demo 学术站" in adapter.render_guidance("x")

    def test_get_site_adapter_falls_back_to_profile_store(self, tmp_path, monkeypatch):
        from backend.literature import profile_store
        from backend.skills.builtin import academic_adapters

        sites = tmp_path / "user-sites"
        sites.mkdir()
        (sites / "demo.yaml").write_text(
            "id: demo\n"
            "display_name: Demo\n"
            "home_url: https://demo.example/\n"
            "domains: [demo.example]\n"
            "search:\n"
            "  url_template: https://demo.example/s?q={query}\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("SAGE_LITERATURE_SITES_DIR", str(sites))
        monkeypatch.chdir(tmp_path)
        profile_store.reset_default_store()
        academic_adapters._DEFAULT_ADAPTERS.pop("demo", None)

        adapter = academic_adapters.get_site_adapter("demo")
        assert adapter.name == "demo"
        assert "demo.example" in adapter.build_search_url("x")

        profile_store.reset_default_store()
        academic_adapters._DEFAULT_ADAPTERS.pop("demo", None)
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_site_profiles.py -q
```
Expected: `ModuleNotFoundError: backend.literature.academic_adapter` 或 `Unknown academic site`。

- [ ] **Step 3: 实现 adapter**

Create `backend/literature/academic_adapter.py`:

```python
"""把 SiteProfile 包装成现有 AcademicSiteAdapter 协议要求的形状。"""

from __future__ import annotations

from typing import Any

from .guidance import render_search_guidance
from .models import SiteProfile, render_search_url


class ProfileBackedAdapter:
    """Profile 驱动的站点适配器；不 import skills 层，靠 duck typing。"""

    def __init__(self, profile: SiteProfile):
        self._profile = profile

    @property
    def name(self) -> str:
        return self._profile.id

    @property
    def profile(self) -> SiteProfile:
        return self._profile

    def build_search_url(self, query: str, **kwargs: Any) -> str:
        return render_search_url(
            self._profile, query, limit=int(kwargs.get("limit", 10))
        )

    def render_guidance(self, query: str, **kwargs: Any) -> str:
        return render_search_guidance(self._profile, query, **kwargs)
```

- [ ] **Step 4: 修改 get_site_adapter**

Modify `backend/skills/builtin/academic_adapters.py`:

```python
def get_site_adapter(name: str) -> AcademicSiteAdapter:
    """根据站点名获取已注册的 adapter。

    先查代码注册表；未命中时回退到 ``backend.literature`` 的 YAML profile
    存储（内置 / 用户 / 项目三级）。这样新增浏览器站点只需加 profile，
    不需要改本模块。
    """
    if name in _DEFAULT_ADAPTERS:
        return _DEFAULT_ADAPTERS[name]

    from backend.literature.academic_adapter import ProfileBackedAdapter
    from backend.literature.models import SiteProfileError
    from backend.literature.profile_store import get_default_store

    store = get_default_store()
    try:
        profile = store.get(name)
    except SiteProfileError:
        profile = None
    if profile is not None:
        return ProfileBackedAdapter(profile)

    available = sorted(set(_DEFAULT_ADAPTERS) | set(store.list_ids()))
    raise ValueError(f"Unknown academic site: {name!r}. Available: {available}")
```

- [ ] **Step 5: 运行新增测试与既有测试**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_site_profiles.py backend/tests/unit/test_academic_adapters.py backend/tests/unit/test_academic_search.py -q
```
Expected: 全部通过（既有 `pubmed` 未知名用例仍应通过）。

- [ ] **Step 6: Ruff + Commit**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/ruff check backend/literature backend/skills/builtin/academic_adapters.py backend/tests/unit/test_literature_site_profiles.py
git add backend/literature/academic_adapter.py backend/skills/builtin/academic_adapters.py backend/tests/unit/test_literature_site_profiles.py
git commit -m "feat(literature): profile-backed adapter with get_site_adapter fallback"
```

---

## Task 5: xueshu789 样例 profile 与文档

**Files:**
- Create: `backend/literature/sites/xueshu789.yaml`
- Create: `backend/literature/README.md`
- Test: `backend/tests/unit/test_literature_site_profiles.py`（追加）

**Interfaces:**
- Consumes: `SiteProfileStore` / `profile_from_dict`
- Produces: 随包分发的 `xueshu789` profile（`status: draft`，选择器待录制）

- [ ] **Step 1: 追加失败测试**

```python
class TestShippedXueshu789Profile:
    def test_shipped_profile_loads_and_matches_observed_facts(self):
        from backend.literature.profile_store import ProfileRoot, SiteProfileStore

        builtin = Path(__file__).resolve().parents[2] / "literature" / "sites"
        store = SiteProfileStore([ProfileRoot(builtin, "builtin")])
        profile = store.get("xueshu789")
        assert profile.display_name == "学术资源站"
        assert "xueshu789.cc" in profile.domains
        assert profile.access.login.method == "form"
        assert profile.access.login.url_contains == "/dbList/"
        assert profile.pdf is not None
        assert profile.pdf.entry_selector == "a.downloadlink"
        assert profile.status == "draft"
        assert profile.compliance.default_enabled is False
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_site_profiles.py::TestShippedXueshu789Profile -q
```
Expected: `未找到站点 profile: 'xueshu789'`。

- [ ] **Step 3: 写 profile**

Create `backend/literature/sites/xueshu789.yaml`:

```yaml
id: xueshu789
display_name: 学术资源站
home_url: https://www.xueshu789.cc/
domains:
  - xueshu789.cc
access:
  mode: browser
  login:
    method: form
    url: https://www.xueshu789.cc/
    account_label: 您的卡号
    password_label: 您的密码
    url_contains: /dbList/
    title_not_contains: 登录
capabilities:
  search: true
  detail: true
  pdf_download: true
  fulltext: true
  citation_export: false
search:
  url_template: "https://www.xueshu789.cc/dbItem/1?kw={query}"
  wait_for:
    - ".result-list"
  pagination:
    type: click_text
    text: 下一页
  result_fields:
    title:
      selector: ""
    authors:
      selector: ""
    source:
      selector: ""
    year:
      selector: ""
detail:
  open_by: click_text
  fields:
    abstract:
      selector: ""
pdf:
  entry:
    selector: a.downloadlink
  forbid:
    - CAJ
  validate:
    magic: "%PDF-"
    title_match: true
rate_limit:
  min_interval_s: 5
  max_batch: 20
compliance:
  note: 仅使用本人账号/机构授权；不绕过付费墙；验证码交还用户
  default_enabled: false
version: "0.1.0"
status: draft
last_verified_at: "2026-11-21"
```

- [ ] **Step 4: 写 README**

Create `backend/literature/README.md`，内容至少覆盖：

```markdown
# 文献站点 profile（SiteProfile）

新增站点 = 新增一份 YAML，不改流水线代码。

## 三级目录（后者覆盖前者）

| 层 | 目录 |
|---|---|
| 内置 | `backend/literature/sites/*.yaml` |
| 用户 | `~/.sage/literature_sites/*.yaml`（可用 `SAGE_LITERATURE_SITES_DIR` 覆盖） |
| 项目 | `<workspace>/.sage/literature_sites/*.yaml` |

## 必填字段

`id` / `display_name` / `home_url` / `domains` / `search.url_template`（含 `{query}`）。

## 可选字段

`access`（登录方式与登录态判定）、`search.wait_for`、`search.pagination`、
`search.result_fields`、`detail`、`pdf`、`rate_limit`、`compliance`、
`status`（`ready` / `draft`）、`last_verified_at`（`YYYY-MM-DD`）。

## 设计规则

- 站点差异只写在这里或 skill 的 `references/`，禁止写进 pipeline 代码。
- 选择器未实测前用空字符串 + `status: draft`，由"录制模式"补齐。
- 第三方站点默认 `compliance.default_enabled: false`，用户显式启用。
- 不代填密码、不导出 cookie、不绕过付费墙；验证码交还用户。

## xueshu789 已实测事实

- 卡号 + 密码登录，成功后 URL 进入 `/dbList/`，标题不再包含「登录」。
- 站内为知网代理检索，行尾下载入口为 `a.downloadlink`；下载后校验 `%PDF-` 与题名。
```

- [ ] **Step 5: 运行测试 + Ruff + Commit**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_site_profiles.py -q
/home/fz/anaconda3/envs/sage-backend/bin/ruff check backend/literature backend/tests/unit/test_literature_site_profiles.py
git add backend/literature/sites/xueshu789.yaml backend/literature/README.md backend/tests/unit/test_literature_site_profiles.py
git commit -m "feat(literature): ship xueshu789 site profile example and schema docs"
```

---

## Task 6: 全量校验、文档标注与收尾

**Files:**
- Modify: `docs/plans/2026-11-21_literature-research-paper-pipeline.md`
- Verify: all new/modified files

**Interfaces:**
- Consumes: all previous tasks
- Produces: 可提交的 M0a 增量

- [ ] **Step 1: 跑目标测试集**

Run:
```bash
cd /home/fz/project/sage/.worktrees/feat-literature-research-pipeline
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_literature_site_profiles.py \
  backend/tests/unit/test_academic_adapters.py \
  backend/tests/unit/test_academic_search.py \
  backend/tests/unit/test_shipped_writing_skills.py \
  backend/tests/unit/test_skill_md_loader.py -q
```
Expected: 全部通过。

- [ ] **Step 2: Ruff 全量新文件**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/ruff check backend/literature backend/skills/builtin/academic_adapters.py backend/tests/unit/test_literature_site_profiles.py
```
Expected: 无错误。

- [ ] **Step 3: Python 3.8 语法兼容检查**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python scripts/check_py38_compat.py backend/literature backend/tests/unit/test_literature_site_profiles.py backend/skills/builtin/academic_adapters.py
```
Expected: 通过。若脚本不支持路径参数，改为 `--help` 查看用法并只检查新增文件；无法单文件检查时在 PR 说明中记录人工检查（typing.Optional/List/Dict、无 PEP 604）。

- [ ] **Step 4: 更新设计文档的 M0 勾选**

在 `docs/plans/2026-11-21_literature-research-paper-pipeline.md` 的 M0 中，把已完成的项改为 `[x]`：
- `SiteProfile schema 与三级加载器`
- 通用 `browser_adapter`（本增量实现的是 profile 解析与指导渲染；真实浏览器执行留到 M1，保留 `[ ]` 并在括号注明）
- xueshu789 profile 草稿（选择器录制留到 M1）

- [ ] **Step 5: 最终提交**

```bash
git add docs/plans/2026-11-21_literature-research-paper-pipeline.md
git commit -m "docs(plans): mark site profile milestone progress"
git log --oneline -6
```

---

## Self-Review

**Spec coverage**
- 声明式 SiteProfile：Task 1 / 2 / 5。
- 三级覆盖（内置/用户/项目）：Task 2。
- xueshu789 作为首个样例：Task 5。
- 不写死站点分支：Task 4 只做通用 fallback；profile 内容全部在 YAML。
- 登录/下载沿用安全边界：profile 只声明 label 与检查条件，不存密码；guidance 要求 browser_login。
- 校验与错误反馈：Task 1 的 schema 校验 + Task 2 的无效 profile 错误收集。
- 录制模式：本增量未实现，明确留在 M1（规格 §5.3.1 的三种生成方式之一）。
- 真实浏览器执行：本增量只到 guidance；browser adapter 的执行层留到 M1。

**Placeholder scan**
- 无 TBD/TODO 占位；xueshu789 的空选择器是**有意**的 `status: draft`，由测试断言该状态。

**Type consistency**
- `SiteProfile` / `PaperRecord` / `ProfileBackedAdapter` / `SiteProfileStore` 命名在各 Task 中一致。
- `get_site_adapter` 的返回类型仍是 duck-typed `AcademicSiteAdapter`，`ProfileBackedAdapter` 满足 `name` + `build_search_url`。
