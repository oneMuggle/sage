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
        "请基于 browser_snapshot 解析结果，输出 JSON 数组，每项字段: "
        "paper_key, title, authors, year, venue, abstract, url, doi。"
        "不要编造页面中不存在的文献或字段；不确定的字段留空并在 extra 标注。"
    )
