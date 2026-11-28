"""把 SiteProfile 渲染成给 LLM 的检索指导（不执行浏览器）。"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional

from .models import SiteField, SiteNote, SiteProfile, is_logged_in, render_search_url


def _selector_text(field: SiteField) -> str:
    return field.selector.strip() if field.selector.strip() else "（待录制）"


def _fields_lines(fields: dict) -> str:
    if not fields:
        return "（未配置，按页面语义自行识别并标注待复核）"
    return "\n".join(f"- {name}: {_selector_text(field)}" for name, field in fields.items())


#: 经验超过该天数未复验即在文本中标注「未复验」（spec §3.1）。
STALE_AFTER_DAYS = 180

#: 严重级别排序：blocker 在前。
_SEVERITY_ORDER = {"blocker": 0, "degraded": 1, "cosmetic": 2}


def _is_stale(note: SiteNote, today: Optional[date] = None) -> bool:
    """经验是否已超过 ``STALE_AFTER_DAYS`` 未复验。"""
    if note.verified_at:
        return False
    if not note.learned_at:
        return True
    reference = today or datetime.now(timezone.utc).date()  # noqa: UP017 — py38 兼容
    try:
        learned = date.fromisoformat(note.learned_at)
    except ValueError:
        return True
    return (reference - learned).days > STALE_AFTER_DAYS


def _relevant_notes(profile: SiteProfile, phase: str) -> List[SiteNote]:
    """筛出与当前阶段相关的经验，按严重级别排序。"""
    selected = [
        note
        for note in profile.notes
        if not note.applies_to or phase in note.applies_to
    ]
    return sorted(selected, key=lambda note: (_SEVERITY_ORDER.get(note.severity, 9), note.id))


def render_notes_section(profile: SiteProfile, phase: str = "search") -> str:
    """渲染「站点经验」段；无相关内容时返回空串。"""
    notes = _relevant_notes(profile, phase)
    if not notes:
        return ""
    lines = ["## 站点经验（按严重度排序，仅列与当前阶段相关的条目）"]
    for note in notes:
        stale = "（未复验）" if _is_stale(note) else ""
        lines.append(f"- [{note.severity}] {note.title}{stale}")
        lines.append(f"  - 现象: {note.symptom}")
        if note.cause:
            lines.append(f"  - 根因: {note.cause}")
        lines.append(f"  - 做法: {note.workaround}")
    return "\n".join(lines)


def render_backends_section(profile: SiteProfile) -> str:
    """渲染「可用检索后端」段；无后端时返回空串。"""
    if not profile.backends:
        return ""
    lines = ["## 可用检索后端"]
    for backend in profile.backends:
        if backend.status == "blocked":
            lines.append(
                f"- {backend.id}（{backend.label}）: 需人工完成验证"
                f"（{backend.reason or '站点侧要求人工交互'}），"
                "请用户在可见窗口操作后自行改为 ready"
            )
        elif backend.status == "unavailable":
            lines.append(f"- {backend.id}（{backend.label}）: 不可用（{backend.reason or '站点侧报错'}）")
        elif backend.status == "unknown":
            lines.append(f"- {backend.id}（{backend.label}）: 未探测，可执行一次探测")
        else:
            lines.append(f"- {backend.id}（{backend.label}）: 可用，入口 {backend.entry_url}")
    return "\n".join(lines)


def render_search_guidance(
    profile: SiteProfile,
    query: str,
    limit: int = 10,
    page_url: Optional[str] = None,
    page_title: Optional[str] = None,
    phase: str = "search",
) -> str:
    """生成检索阶段的 LLM 指导文本；真实页面解析仍由 LLM 基于 snapshot 完成。"""
    interactive = profile.search.mode == "interactive"
    if interactive:
        search_url = profile.search.entry_url or profile.search.url_template
        url_line = f"检索入口: {search_url}"
        input_selectors = ", ".join(profile.search.input_selectors) or "（未配置）"
        interactive_block = (
            f"检索模式: 交互式\n"
            f"入口点击: {profile.search.entry_click or '（无）'}\n"
            f"搜索输入框选择器: {input_selectors}\n"
            f"提交方式: press {profile.search.submit_key}\n"
            f"提交后等待: {profile.search.wait_after_s}s\n"
            f"结果提示: {profile.search.result_hint or '（无）'}\n"
        )
    else:
        search_url = render_search_url(profile, query, limit=limit)
        url_line = f"检索 URL: {search_url}"
        interactive_block = ""
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
    if profile.detail and profile.detail.url_from:
        uf = profile.detail.url_from
        detail += (
            f"\n详情 URL 推导: 读取 {uf.selector} 的 href，"
            f"取查询参数 {uf.param}，decode={uf.decode} 后作为详情/摘要页 URL"
        )
    pdf = "（未配置）"
    if profile.pdf:
        entry = profile.pdf.entry_selector or profile.pdf.entry_text or "（待录制）"
        pdf = (
            f"入口: {entry}；禁止: {', '.join(profile.pdf.forbid)}；"
            f"校验: magic={profile.pdf.magic}, title_match={profile.pdf.title_match}"
            f"{'；点击后等待 ' + str(profile.pdf.post_click_wait_s) + 's' if profile.pdf.post_click_wait_s else ''}"
            f"{'；备注: ' + profile.pdf.note if profile.pdf.note else ''}"
        )

    notes_block = render_notes_section(profile, phase)
    backends_block = render_backends_section(profile)
    extra = ""
    if backends_block:
        extra += backends_block + "\n"
    if notes_block:
        extra += notes_block + "\n"

    return (
        f"站点: {profile.display_name} ({profile.id})\n"
        f"profile 状态: {profile.status}"
        f"{'，选择器待录制' if profile.status == 'draft' else ''}\n"
        f"{url_line}\n"
        f"{interactive_block}"
        f"{login_line}\n"
        + ("\n".join(login_hint) + "\n" if login_hint else "")
        + f"结果等待选择器: {wait_for}\n"
        f"翻页方式: {pagination}\n"
        f"结果字段:\n{_fields_lines(profile.search.result_fields)}\n"
        f"详情打开: {detail}\n"
        f"PDF 下载: {pdf}\n"
        f"限速: 每篇间隔 >= {profile.rate_limit.min_interval_s}s；"
        f"单批 <= {profile.rate_limit.max_batch} 篇\n"
        f"合规: {profile.compliance.note or '遵守站点条款与机构授权'}\n\n"
        + extra
        + "请基于 browser_snapshot 解析结果，输出 JSON 数组，每项字段: "
        "paper_key, title, authors, year, venue, abstract, url, doi。"
        "不要编造页面中不存在的文献或字段；不确定的字段留空并在 extra 标注。"
    )
