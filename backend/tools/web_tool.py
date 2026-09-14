"""
Web 工具 - 网络搜索和网页获取
"""

# win7 py3.8: PEP 604 (X | Y) / PEP 585 (set[...]) 注解惰性化，避免 def 定义时报错
from __future__ import annotations

import ipaddress
import re
from ipaddress import IPv4Address, IPv6Address
from typing import Any, Dict, Optional, Set, Union
from urllib.parse import urljoin, urlparse

import httpx

from backend.domain.network_policy import NetworkMode, NetworkPolicy
from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.tools.http_factory import DEFAULT_HEADERS, build_client, default_headers, retrying_send
from backend.tools.network_config import load_network_policy
from backend.tools.search_config import load_search_config
from backend.tools.search_engines import SearchEngine, resolve_engine_chain
from backend.wiki.html_extract import decode_html, extract

from . import content_sniff, file_links, web_render
from .base import BaseTool, ToolResult, ToolSchema
from .web_render import RenderError

# 浏览器级默认请求头 —— 自 Round 5 起定义在 http_factory（三个出网工具共用）；
# 此处保留同名别名，兼容既有引用与测试。
_DEFAULT_HEADERS: Dict[str, str] = DEFAULT_HEADERS

#: 常见反爬拒绝状态码 → 路由指引文案（G1, Round 2）。
#: 出路顺序即成本顺序：真浏览器通道（真实 Chrome 指纹）> 代理 > 换搜索源。
_ANTIBOT_GUIDANCE = (
    "（该站点疑似反爬/风控拦截。出路：① 经 coder 用 browser_launch + "
    "browser_navigate 真浏览器通道；② 设置 → 网络中配置代理后重试；"
    "③ 搜索场景可更换搜索引擎或 API 引擎源）"
)

#: 触发 G1 指引的拒绝状态码
_ANTIBOT_STATUS_CODES = frozenset({403, 429, 503})

#: 反爬盾 / 验证码页特征（AB1，Round 5）：HTML 原文或抽取正文命中任一即视为"盾页"。
#: 覆盖 Cloudflare / Akamai / Imperva(Incapsula) / 阿里云 WAF / 腾讯云 WAF / 百度云加速 /
#: 知网 / 通用验证码提示。只在正文很短（真实页面不会只剩这些词）时判定，避免误伤
#: 讨论反爬技术的正常文章。
_ANTIBOT_PAGE_MARKERS = (
    "cf-browser-verification",
    "cf_chl_",
    "__cf_chl",
    "challenge-platform",
    "just a moment...",
    "checking your browser",
    "verify you are human",
    "attention required! | cloudflare",
    "_incapsula_resource",
    "incapsula incident",
    "akamai",
    "access denied",
    "request unsuccessful",
    "ddos-guard",
    "please enable javascript and cookies",
    "enable javascript to continue",
    "waf.tencent",
    "aliyun_waf",
    "errors.aliyun.com",
    "yundun.console.aliyun.com",
    "405 not allowed",  # 阿里云 WAF 默认拦截页
    "滑动验证",
    "安全验证",
    "人机验证",
    "请完成验证",
    "验证码",
    "访问过于频繁",
    "访问太频繁",
    "请求过于频繁",
    "异常访问",
    "拒绝访问",
    "页面正在加载中，请稍候",
)

#: 盾页判定的正文长度上限：正文长于此不判定为盾页
_ANTIBOT_PAGE_MAX_TEXT = 1200

_ANTIBOT_MARKER_RE = re.compile(
    "|".join(re.escape(marker) for marker in _ANTIBOT_PAGE_MARKERS), re.IGNORECASE
)


def looks_like_antibot_page(html: str, extracted_text: str) -> bool:
    """静态 / 渲染结果是否是反爬盾页（AB1，纯函数）。"""
    text = (extracted_text or "").strip()
    if len(text) > _ANTIBOT_PAGE_MAX_TEXT:
        return False
    sample = (html or "")[:200_000]
    return bool(_ANTIBOT_MARKER_RE.search(text) or _ANTIBOT_MARKER_RE.search(sample))


#: AU2 登录墙判定：密码框页面去标签后的词数上限（登录页几乎没有正文）
_LOGIN_PAGE_MAX_WORDS = 250
_TAG_RE = re.compile(r"<script\b.*?</script>|<style\b.*?</style>|<[^>]+>", re.I | re.S)


class _AntibotBlocked(Exception):  # noqa: N818 — internal signal
    """内部信号：静态通道被反爬拦截（状态码或盾页），可尝试升级到渲染通道。"""

    def __init__(self, reason: str, status: int = 0) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


class _RetryingClient(httpx.Client):
    """``send`` 走 ``retrying_send``（AB5）的 httpx.Client —— 搜索引擎链无需改动即获得
    重试 / Retry-After / 同 host 限速。经 ``build_client(client_class=...)`` 构造。"""

    def send(
        self, request: httpx.Request, *, stream: bool = False, **kwargs: Any
    ) -> httpx.Response:  # type: ignore[override]
        parent = super()

        class _Sender:
            @staticmethod
            def send(req: httpx.Request, stream: bool = False) -> httpx.Response:
                return parent.send(req, stream=stream, **kwargs)

        return retrying_send(_Sender(), request, stream=stream)  # type: ignore[arg-type]


class WebSearchTool(BaseTool):
    """网络搜索工具（多引擎链，方案 2026-09-13 §2.2）。

    沿 ``search_config.engine_order`` 逐个引擎尝试：首个返回非空结果的引擎
    胜出（content 附 ``engine`` 字段）；全部引擎无结果 → 空结果 + note（W3：
    绝不伪造）；全部引擎异常 → ``success=False``。配置每次现读 —— 用户改
    设置立即生效，不必重开会话。
    """

    # A1: 出网调用 — 最严门禁（只读模式禁止，交互模式询问）
    risk = RiskClass.EXTERNAL

    def __init__(self, policy: Optional[ToolPolicy] = None) -> None:
        super().__init__(policy=policy)
        # 兼容保留的常驻 client（UA 头测试引用）；execute 走逐调用现建，
        # 代理等配置改动即时生效。
        self.client = build_client(
            timeout=30.0,
            headers=default_headers(),
        )

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="web_search",
            description=(
                "搜索网络信息。返回搜索结果列表。默认引擎链 Bing → DuckDuckGo，"
                "可在设置中接入 Tavily/智谱等 API 引擎与调整顺序。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询"},
                    "limit": {"type": "integer", "description": "返回结果数量 (默认 5)"},
                    "refresh": {
                        "type": "boolean",
                        "description": "跳过缓存强制搜索（默认 false；5 分钟内同 query+limit 命中缓存）",
                    },
                },
                "required": ["query"],
            },
        )

    def execute(self, query: str, limit: int = 5, refresh: bool = False, **kwargs) -> ToolResult:
        """
        执行搜索

        Args:
            query: 搜索查询
            limit: 返回结果数量
            refresh: 跳过缓存强制搜索（Q1，默认 false；5 分钟内同 query+limit 命中）
        """
        # Q1：查询缓存——仅缓存"成功且非空"结果；键含 limit（不同截断互不干扰）
        cache_key = "search://" + (query or "").strip()
        cache_mode = f"limit={int(limit)}"
        if not refresh:
            from .web_cache import SEARCH_CACHE_TTL_SECONDS, get as _cache_get

            cached = _cache_get(cache_key, cache_mode, ttl_seconds=SEARCH_CACHE_TTL_SECONDS)
            if cached is not None:
                content: Dict[str, Any] = dict(cached)
                content["cached"] = True
                return ToolResult(success=True, content=content)

        engine_errors = []
        saw_completed = False
        try:
            with build_client(
                timeout=30.0,
                headers=default_headers(),
                trust_env=not self._policy.subagent_only,
                client_class=_RetryingClient,
            ) as client:
                for engine in resolve_engine_chain(load_search_config()):
                    try:
                        results = engine.search(query, limit, client=client)
                    except Exception as engine_exc:  # noqa: BLE001 — 单引擎失败降级下一引擎
                        engine_errors.append(f"{engine.name}: {engine_exc}")
                        continue
                    if results:
                        content = {
                            "query": query,
                            "engine": engine.name,
                            "results": results,
                        }
                        from .web_cache import put as _cache_put

                        # TTL 在 get 侧按 SEARCH_CACHE_TTL_SECONDS 生效
                        _cache_put(cache_key, cache_mode, content)
                        return ToolResult(success=True, content=content)
                    saw_completed = True
                    engine_errors.append(f"{engine.name}: 无可解析结果（可能被限流）")
        except Exception as e:
            return ToolResult(success=False, error=f"搜索失败: {str(e)}")

        if saw_completed:
            # W3：至少一个引擎正常完成但无结果 —— 搜索本身成功，明示无结果，
            # 绝不返回伪造占位条目（那会被模型当真实结果引用，成为幻觉源）。
            content = {
                "query": query,
                "results": [],
                "note": "搜索源未返回可解析结果（可能被限流），请勿编造结果",
            }
            if engine_errors:
                content["engine_errors"] = engine_errors
            return ToolResult(success=True, content=content)
        failure = "搜索失败: " + "; ".join(engine_errors)
        if any(code in failure for code in ("403", "429", "503")):
            # G1：拒绝类失败 → 指引代理 / API 引擎出路
            failure += _ANTIBOT_GUIDANCE
        return ToolResult(success=False, error=failure)

    def _clean_html(self, text: str) -> str:
        """兼容保留：清理 HTML 标签并解码实体（解析实现已迁入 search_engines）。"""
        return SearchEngine._clean_html(text)


class WebFetchTool(BaseTool):
    """获取网页内容工具"""

    # A1: 出网调用 — 最严门禁（只读模式禁止，交互模式询问）
    risk = RiskClass.EXTERNAL

    #: mode 合法取值。text 只给正文，links/tables 额外带对应段，raw 给原始 HTML
    VALID_MODES = ("text", "links", "tables", "raw", "files")
    #: mode=files 对 top-N 候选做首块探测（流式 GET 读首块即关）
    FILES_PROBE_TOP_N = 5

    #: render 合法取值：auto=检出 JS 壳自动渲染（默认）；always=强制；never=仅静态
    VALID_RENDER_MODES = ("auto", "never", "always")

    #: 只对这些 content-type 做 HTML 抽取；JSON / 纯文本直接给原文
    _HTML_CONTENT_TYPES = ("text/html", "application/xhtml")

    #: 手动跟随重定向的最大跳数
    _MAX_REDIRECTS = 5

    #: 网页响应体硬上限，避免 max_length 事后截断导致无限缓冲
    _MAX_RESPONSE_BYTES = 4 * 1024 * 1024

    #: C1：uncapped 抽取长度（缓存存全文，返回前按本次 max_length 裁剪）
    _UNCAPPED_LENGTH = 10**9

    def __init__(
        self,
        policy: Optional[ToolPolicy] = None,
        network_policy: Optional[NetworkPolicy] = None,
    ) -> None:
        super().__init__(policy=policy)
        # None 表示"每次 execute 现读 settings"——用户改白名单立即生效，不必
        # 重开会话。显式传入则固定（测试注入用）。
        self._network_policy = network_policy
        # 兼容保留的常驻 client；实际请求走 _get_with_redirects 的逐跳现建
        # client（代理/网络策略/TLS 豁免均按当前配置即时生效）。
        self.client = build_client(
            timeout=30.0,
            follow_redirects=False,
            trust_env=not self._policy.subagent_only,
            headers=default_headers(),
        )

    def _effective_network_policy(self) -> NetworkPolicy:
        if self._network_policy is not None:
            return self._network_policy
        return load_network_policy()

    @staticmethod
    def _literal_ip(url: str) -> Optional[Union[IPv4Address, IPv6Address]]:
        hostname = urlparse(url).hostname
        if not hostname:
            return None
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return None
        # win7 py3.8: ipaddress 不解包 IPv4-mapped IPv6（::ffff:x.x.x.x 的
        # is_global 按 IPv6 全局单播判定，会放行 ::ffff:100.64.0.1 这类
        # CGNAT 映射地址）。显式解包后按 IPv4 语义判定，与 py3.11 对齐。
        mapped = getattr(address, "ipv4_mapped", None)
        if mapped is not None:
            return mapped
        return address

    @staticmethod
    def _all_public(addresses: Set[Union[IPv4Address, IPv6Address]]) -> bool:
        return bool(addresses) and all(ip.is_global for ip in addresses)

    def _validate_subagent_url(self, url: str) -> Optional[str]:
        address = self._literal_ip(url)
        if address is None:
            return "subagent_web_fetch_blocked: 仅允许访问字面量公共 IP 地址"
        if not self._all_public({address}):
            return "subagent_web_fetch_blocked: 仅允许访问公共网络地址"
        return None

    def _validate_subagent_redirect(self, location: str) -> Optional[str]:
        address = self._literal_ip(location)
        if address is None:
            return "subagent_web_fetch_blocked: 重定向目标必须是字面量公共 IP 地址"
        if not self._all_public({address}):
            return "subagent_web_fetch_blocked: 重定向目标不是公共地址"
        return None

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="web_fetch",
            description=(
                "获取网页内容并抽取正文。mode=text 返回正文（默认），"
                "links 额外返回页面链接列表，tables 额外返回表格（文献列表页用），"
                "raw 返回未处理的原始 HTML。"
                "SPA/JS 动态页自动经受控 headless 浏览器渲染后取正文"
                "（render=auto 默认；always 强制渲染；never 仅静态 HTML）。"
                "credential_domain 可携带 browser_cookies 导出的登录态"
                "（仅附加到同域请求，跨域重定向自动剥离）。"
                "静态请求被反爬拦截时默认自动升级到真浏览器通道重放（escalate）。"
                "渲染分支内部会启动受控 headless 浏览器，不单独走启动审批。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "网页 URL"},
                    "mode": {
                        "type": "string",
                        "enum": list(self.VALID_MODES),
                        "description": (
                            "抽取模式 (默认 text)。files：嗅探页面内候选文件链接"
                            "（citation_pdf_url / <a download> / .pdf|.zip|.docx 后缀 / iframe|embed / "
                            "meta refresh / 「下载|全文|PDF」锚文本）并对 top 候选探测真实类型，"
                            "结果 files[] 可直接喂 http_download"
                        ),
                    },
                    "render": {
                        "type": "string",
                        "enum": list(self.VALID_RENDER_MODES),
                        "description": "JS 渲染策略 (默认 auto：检出 SPA 壳自动渲染)",
                    },
                    "max_length": {
                        "type": "integer",
                        "description": "正文最大长度 (默认 10000)",
                    },
                    "credential_domain": {
                        "type": "string",
                        "description": (
                            "凭据档案 domain（如 .cnki.net）：browser_cookies 导出的 "
                            "cookie 或 credential_set 设置的头部凭据（Bearer / API key），"
                            "命中域自动附加、跨域剥离；过期报 credential_expired，"
                            "被踢到登录页报 login_required"
                        ),
                    },
                    "wait_for": {
                        "type": "string",
                        "description": (
                            "CSS 选择器：渲染分支等它出现再取值（默认空 = "
                            "readyState+正文稳定即返回）"
                        ),
                    },
                    "refresh": {
                        "type": "boolean",
                        "description": "跳过缓存强制抓取（默认 false；15 分钟内同 URL 同 mode 命中缓存）",
                    },
                    "escalate": {
                        "type": "boolean",
                        "description": (
                            "静态请求被反爬拦截（403/429/503 或验证盾页）时自动改经受控 "
                            "headless 真浏览器重放一次（默认 true；render=never 时不升级）"
                        ),
                    },
                },
                "required": ["url"],
            },
        )

    def execute(  # noqa: PLR0911 — 每个拒绝路径独立 return，扁平比提取辅助函数更直读
        self,
        url: str,
        mode: str = "text",
        max_length: int = 10000,
        render: str = "auto",
        credential_domain: str = "",
        wait_for: str = "",
        refresh: bool = False,
        escalate: bool = True,
        **kwargs,
    ) -> ToolResult:
        """获取网页并按 ``mode`` 抽取。

        Args:
            url:        网页 URL
            mode:       ``text`` / ``links`` / ``tables`` / ``raw``
            max_length: 正文最大长度
            render:     ``auto``（默认，检出 JS 壳自动渲染）/ ``always`` / ``never``
            credential_domain: browser_cookies 档案 domain，附加登录态 cookie
            wait_for:   渲染分支等待出现的 CSS 选择器（R2）
            refresh:    跳过缓存强制抓取（C1，默认 false）
            escalate:   反爬拦截时自动升级到渲染通道（AB1，默认 true）
        """
        if mode not in self.VALID_MODES:
            return ToolResult(
                success=False,
                error=f"无效的 mode {mode!r}，可选：{', '.join(self.VALID_MODES)}",
            )
        if render not in self.VALID_RENDER_MODES:
            return ToolResult(
                success=False,
                error=f"无效的 render {render!r}，可选：{', '.join(self.VALID_RENDER_MODES)}",
            )
        if not url.startswith(("http://", "https://")):
            return ToolResult(success=False, error="无效的 URL，必须以 http:// 或 https:// 开头")

        # C1：TTL 缓存。credential_domain（登录态时效）与 raw（原始 HTML）
        # 不参与缓存；命中即返回，cached 标记明示。
        use_cache = not refresh and mode != "raw" and not credential_domain.strip()
        if use_cache:
            from .web_cache import get as _cache_get

            cached = _cache_get(url, mode)
            if cached is not None:
                content = dict(cached)
                content["content"] = str(content.get("content", ""))[:max_length]
                content["cached"] = True
                return ToolResult(success=True, content=content)

        credential_headers: Optional[Dict[str, str]] = None
        if credential_domain.strip():
            from .credential_vault import cookie_domain_matches, resolve_credential

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
            if not resolution.ok or not resolution.headers:
                return ToolResult(
                    success=False,
                    error=(
                        f"credential_not_found: 无 {credential_domain!r} 的凭据档案"
                        "（先 browser_cookies action=export 导出，或 credential_set 设置头部凭据）"
                    ),
                )
            target_host = urlparse(url).hostname or ""
            if not cookie_domain_matches(target_host, credential_domain):
                return ToolResult(
                    success=False,
                    error=(
                        f"credential_domain_mismatch: 目标 host {target_host!r} "
                        f"不在凭据域 {credential_domain!r} 内（档案域按 cookie 归属）"
                    ),
                )
            credential_headers = resolution.headers

        network_policy = self._effective_network_policy()
        url_error = self._validate_target_url(url)
        if url_error:
            return ToolResult(success=False, error=url_error)
        host_rejection = network_policy.check_host(url)
        if host_rejection:
            return ToolResult(success=False, error=host_rejection)

        # 非 online 模式下 host 已过白名单，跳过公网 IP 校验：内网地址解析出
        # 私有 IP 是预期的。online 模式 check_host 恒放行，走原有校验不变。
        gated_by_whitelist = network_policy.mode is not NetworkMode.ONLINE
        if self._policy.subagent_only and not gated_by_whitelist:
            validation_error = self._validate_subagent_url(url)
            if validation_error:
                return ToolResult(success=False, error=validation_error)

        can_escalate = bool(escalate) and render != "never" and mode != "raw"
        try:
            try:
                response, final_url, credential_note = self._get_with_redirects(
                    url,
                    network_policy,
                    gated_by_whitelist,
                    credential_headers,
                    credential_domain.strip(),
                )
                status = response.status_code
                if status in _ANTIBOT_STATUS_CODES:
                    raise _AntibotBlocked(f"http_{status}: 站点拒绝访问（状态码 {status}）", status)
                response.raise_for_status()
                # AU2：带凭据却被送到登录页 → login_required（不当普通正文返回）
                if credential_headers:
                    login_error = self._detect_login_wall(
                        url, final_url, response, credential_domain
                    )
                    if login_error:
                        return ToolResult(success=False, error=login_error)
                # C1：以 uncapped 抽取（缓存存全文，返回前统一裁剪）——
                # 不同 max_length 的请求可共享同一份缓存
                content = self._render(final_url, response, mode, self._UNCAPPED_LENGTH)
                if credential_note:
                    content["note"] = credential_note
                if content.get("kind") != "binary" and self._is_antibot_page(response, content):
                    raise _AntibotBlocked("antibot_page: 静态响应是反爬验证 / 拦截页", status)
                if self._should_render(render, response, content, max_length):
                    content = self._render_dynamic(
                        final_url, network_policy, mode, self._UNCAPPED_LENGTH, content, wait_for
                    )
            except _AntibotBlocked as blocked:
                if not can_escalate:
                    return ToolResult(success=False, error=f"{blocked.reason}{_ANTIBOT_GUIDANCE}")
                # AB1：静态通道被拦 → 经渲染池（真 Chrome 指纹 + 代理 + 可选持久
                # profile）重放一次；仍被拦才返回指引。
                content = self._escalate(url, network_policy, mode, wait_for, blocked)
            if mode == "files" and content.get("kind") != "binary":
                self._finalize_files(content, network_policy)
            if use_cache:
                # 剥离易变 note / cached 标记后存全文副本
                from .web_cache import put as _cache_put

                storable = {
                    key_: value for key_, value in content.items() if key_ not in ("note", "cached")
                }
                _cache_put(url, mode, storable)
            content["content"] = str(content.get("content", ""))[:max_length]
            return ToolResult(success=True, content=content)
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response is not None else 0
            if status in _ANTIBOT_STATUS_CODES:
                # G1：反爬拒绝 → 明示出路（browser 通道 / 代理 / 换源），不吞成通用失败
                return ToolResult(
                    success=False,
                    error=f"http_{status}: 站点拒绝访问（状态码 {status}）{_ANTIBOT_GUIDANCE}",
                )
            return ToolResult(success=False, error=f"HTTP 请求失败: {str(e)}")
        except httpx.HTTPError as e:
            return ToolResult(success=False, error=f"HTTP 请求失败: {str(e)}")
        except RenderError as e:
            # 渲染失败单独语义：明确指引手动路径，不吞成"获取网页失败"
            return ToolResult(success=False, error=str(e))
        except Exception as e:
            return ToolResult(success=False, error=f"获取网页失败: {str(e)}")

    @staticmethod
    def _validate_target_url(url: str) -> Optional[str]:
        try:
            parsed = urlparse(url)
        except ValueError:
            return "无效的 URL，必须包含 http:// 或 https:// 以及主机名"
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return "无效的 URL，必须包含 http:// 或 https:// 以及主机名"
        # hostname 里有空格/控制字符会让 urlparse 把整串当 host,
        # httpx 会把空格 encode 成 %20 后 DNS 解析报
        # ``[Errno -2] Name or service not known`` —— 这种错是上游(模型/调用方)
        # 把域名错误分词产生的,显式拦下比让底层 DNS 失败更易诊断。
        if any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in parsed.hostname):
            return "无效的 URL：hostname 含非法字符（空格或控制字符）"
        return None

    def _get_with_redirects(
        self,
        url: str,
        network_policy: NetworkPolicy,
        gated_by_whitelist: bool,
        credential_headers: Optional[Dict[str, str]] = None,
        credential_domain: str = "",
    ) -> tuple:
        current_url = url
        credential_stripped = False
        refreshed_names: list = []
        for redirect_count in range(self._MAX_REDIRECTS + 1):
            url_error = self._validate_target_url(current_url)
            if url_error:
                raise ValueError(url_error)
            host_rejection = network_policy.check_host(current_url)
            if host_rejection:
                raise ValueError(host_rejection)
            if self._policy.subagent_only and not gated_by_whitelist:
                validation_error = self._validate_subagent_url(current_url)
                if validation_error:
                    raise ValueError(validation_error)

            # 登录态 cookie 只附加到档案域命中的 hop；跨域重定向（如订阅源
            # 302 到第三方 SSO/广告域）静默剥离，防止凭据外带。
            hop_headers: Dict[str, str] = {"Accept-Encoding": "identity"}
            credential_applied = False
            if credential_headers:
                from .credential_vault import cookie_domain_matches

                hostname = urlparse(current_url).hostname or ""
                if cookie_domain_matches(hostname, credential_domain):
                    hop_headers.update(credential_headers)
                    credential_applied = True
                elif redirect_count > 0:
                    credential_stripped = True

            with build_client(
                timeout=30.0,
                follow_redirects=False,
                verify=not network_policy.allows_insecure_tls(current_url),
                trust_env=not self._policy.subagent_only,
                headers=default_headers(),
            ) as client:
                # 强制 ``Accept-Encoding: identity`` 禁用 httpx 自动解压。
                # 部分站点声明 ``Content-Encoding: gzip`` 但响应体实际不是合法
                # gzip 流(常见于上游 CDN/反代),httpx 解压会抛
                # ``zlib.error: Error -3 ... incorrect header check``。同款修复
                # 已在 ``backend/api/llm_proxy_routes.py`` 应用,这里保持一致。
                # 同时保留 UA 等默认头——重定向后站点只看 hop-by-hop,新 host
                # 仍按默认头身份访问。
                request = client.build_request(
                    "GET",
                    current_url,
                    headers=hop_headers,
                )
                # AB5：连接错 / 超时 / 5xx / 429 重试 + Retry-After + 同 host 限速
                response = retrying_send(client, request, stream=True)
                try:
                    # AU2：命中域的响应带 Set-Cookie → 合并回 cookie 档案（续期 token 不丢）
                    if credential_applied and "Cookie" in credential_headers:
                        refreshed_names.extend(
                            self._writeback_set_cookies(response, current_url, credential_domain)
                        )
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if redirect_count >= self._MAX_REDIRECTS:
                            raise ValueError(
                                f"redirect_limit_exceeded: 重定向次数超过 {self._MAX_REDIRECTS} 次"
                            )
                        if not location:
                            raise ValueError("invalid_redirect: 重定向缺少 Location")
                        current_url = urljoin(current_url, location)
                        continue

                    if response.status_code in _ANTIBOT_STATUS_CODES:
                        # 拒绝类状态：不缓冲正文，直接交给 execute 判定升级
                        response.close()
                        return response, current_url, None
                    response.raise_for_status()
                    declared = response.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > self._MAX_RESPONSE_BYTES:
                        raise ValueError(
                            f"response_exceeds_limit: 响应超过 {self._MAX_RESPONSE_BYTES} 字节"
                        )
                    content = bytearray()
                    for chunk in response.iter_bytes(64 * 1024):
                        content.extend(chunk)
                        if len(content) > self._MAX_RESPONSE_BYTES:
                            raise ValueError(
                                f"response_exceeds_limit: 响应超过 {self._MAX_RESPONSE_BYTES} 字节"
                            )
                    buffered_response = httpx.Response(
                        response.status_code,
                        headers=response.headers,
                        content=bytes(content),
                        request=response.request,
                    )
                finally:
                    response.close()
                response = buffered_response
            notes = []
            if credential_stripped and not credential_applied:
                notes.append("credential_stripped: 重定向跨出凭据域，登录态凭据已剥离")
            if refreshed_names:
                notes.append(
                    "credential_refreshed: 服务器续期了 cookie，档案已回写"
                    f"（{', '.join(sorted(set(refreshed_names))[:5])}）"
                )
            return response, current_url, ("；".join(notes) if notes else None)

        raise ValueError("redirect_limit_exceeded: 重定向次数超限")

    def _render(
        self, url: str, response: httpx.Response, mode: str, max_length: int
    ) -> Dict[str, Any]:
        """把响应渲染成工具结果的 ``content`` dict。"""
        content_type = response.headers.get("content-type", "")
        text, encoding = decode_html(response.content, content_type)
        result: Dict[str, Any] = {
            "url": url,
            "status_code": response.status_code,
            "content_type": content_type,
            "encoding": encoding,
            "mode": mode,
        }

        is_html = any(marker in content_type.lower() for marker in self._HTML_CONTENT_TYPES)
        if not is_html and content_sniff.is_binary_payload(
            response.content[: content_sniff.SNIFF_BYTES], content_type
        ):
            # SN1（Round 5）：二进制响应不以乱码正文返回，给结构化提示引导
            # 模型改用 http_download。raw 模式同样适用——原始字节对模型无意义。
            return self._binary_result(url, response, result)
        if mode == "raw" or not is_html:
            result["content"] = text[:max_length]
            return result

        page = extract(text, url)
        result["title"] = page.title
        result["content"] = page.text[:max_length]
        if mode == "links":
            result["links"] = page.links[: self._policy.max_result_items]
        elif mode == "tables":
            result["tables"] = page.tables[: self._policy.max_result_items]
        elif mode == "files":
            result["files"] = file_links.extract_file_links(text, url)
        return result

    def _finalize_files(self, content: Dict[str, Any], network_policy: NetworkPolicy) -> None:
        """SN2：对 top-N 候选做首块探测（真实 content-type / 魔数 / 大小），原地更新 ``files``。"""
        candidates = list(content.get("files") or [])
        limit = max(1, self._policy.max_result_items)
        candidates = candidates[:limit]
        probed = 0
        for item in candidates:
            if probed >= self.FILES_PROBE_TOP_N:
                break
            probe = self._probe_file_url(str(item.get("url", "")), network_policy)
            if probe is None:
                continue
            probed += 1
            item.update(probe)
            if probe.get("probe") == "html":
                item["score"] = int(item.get("score", 0)) - 50
            elif probe.get("probe") == "file":
                item["score"] = int(item.get("score", 0)) + 20
        candidates.sort(key=lambda c: (-int(c.get("score", 0)), str(c.get("url"))))
        content["files"] = candidates
        content["files_total"] = len(content.get("files") or [])
        content["hint"] = (
            "files[] 按可能性降序；probe=file 的条目已确认是文件（detected_type / content_length 可用），"
            "直接 http_download url=<url>；probe=html 说明该链接是网页（登录页 / 中转页），"
            "可对其再做一次 web_fetch mode=files 或改走 credential_domain / 浏览器通道。"
            if candidates
            else "页面未发现候选文件链接：若是 JS 渲染后才出现的按钮，试 render=always；"
            "或经 browser_launch + browser_navigate + browser_interact 点击后用 browser_downloads 取文件。"
        )

    def _probe_file_url(  # noqa: PLR0911 — 各探测结论独立 return
        self, url: str, network_policy: NetworkPolicy
    ) -> Optional[Dict[str, Any]]:
        """流式 GET 读首块即关：→ {probe: file|html|other, detected_type, content_type, content_length}。"""
        if not url.startswith(("http://", "https://")):
            return None
        if self._validate_target_url(url) or network_policy.check_host(url):
            return None
        if self._policy.subagent_only and self._validate_subagent_url(url):
            return None
        try:
            # 不自动跟随重定向：每一跳都必须过 check_host（与 _get_with_redirects 同口径），
            # 探测只是"看一眼"，302 直接回报 location 让模型决定。
            with build_client(
                timeout=15.0,
                follow_redirects=False,
                verify=not network_policy.allows_insecure_tls(url),
                trust_env=not self._policy.subagent_only,
                headers=default_headers(),
            ) as client:
                request = client.build_request("GET", url, headers={"Accept": "*/*"})
                response = client.send(request, stream=True)
                try:
                    if response.is_redirect:
                        location = urljoin(url, response.headers.get("location", ""))
                        return {
                            "probe": "redirect",
                            "status_code": response.status_code,
                            "final_url": location,
                        }
                    if response.status_code >= 400:
                        return {"probe": "error", "status_code": response.status_code}
                    head = b""
                    for chunk in response.iter_bytes(content_sniff.SNIFF_BYTES):
                        head = chunk
                        break
                    content_type = response.headers.get("content-type", "")
                    declared = response.headers.get("content-length", "")
                    detected = content_sniff.detect_kind(head)
                    is_html = content_sniff.looks_like_html(head) or (
                        detected == "text"
                        and any(m in content_type.lower() for m in self._HTML_CONTENT_TYPES)
                    )
                    probe = (
                        "html"
                        if is_html
                        else (
                            "file"
                            if content_sniff.is_binary_payload(head, content_type)
                            else "other"
                        )
                    )
                    result: Dict[str, Any] = {
                        "probe": probe,
                        "status_code": response.status_code,
                        "content_type": content_type or None,
                        "detected_type": detected,
                        "content_length": int(declared) if declared.isdigit() else None,
                    }
                    disposition = response.headers.get("content-disposition")
                    if disposition:
                        from .download_tool import derive_filename

                        result["suggested_filename"] = derive_filename(
                            str(response.url), disposition
                        )
                    return result
                finally:
                    response.close()
        except (httpx.HTTPError, ValueError, OSError) as exc:
            return {"probe": "error", "error": f"{type(exc).__name__}: {exc}"[:200]}

    @staticmethod
    def _binary_result(url: str, response: httpx.Response, base: Dict[str, Any]) -> Dict[str, Any]:
        """二进制响应的结构化结果（SN1）：不给正文，给类型 / 大小 / 建议文件名。"""
        from .download_tool import derive_filename

        head = response.content[: content_sniff.SNIFF_BYTES]
        detected = content_sniff.detect_kind(head)
        declared = response.headers.get("content-length", "")
        length: Optional[int] = None
        if declared.isdigit():
            length = int(declared)
        elif response.content:
            length = len(response.content)
        suggested = derive_filename(url, response.headers.get("content-disposition"))
        result = dict(base)
        result.update(
            {
                "kind": "binary",
                "detected_type": detected,
                "content_length": length,
                "suggested_filename": suggested,
                "content": "",
                "hint": (
                    f"该 URL 返回的是二进制文件（{detected}，Content-Type {result.get('content_type') or '未知'}），"
                    f"不是网页。请改用 http_download 下载到工作区（建议文件名 {suggested!r}），"
                    "再用对应工具读取内容。"
                ),
            }
        )
        return result

    @staticmethod
    def _writeback_set_cookies(response: httpx.Response, url: str, credential_domain: str) -> list:
        values = response.headers.get_list("set-cookie")
        if not values:
            return []
        from .credential_vault import merge_set_cookies

        try:
            return merge_set_cookies(credential_domain, values, url)
        except Exception:  # noqa: BLE001 — 回写失败不影响本次抓取
            return []

    def _detect_login_wall(
        self, url: str, final_url: str, response: httpx.Response, credential_domain: str
    ) -> Optional[str]:
        """AU2：带凭据请求被送到登录页 → ``login_required`` 文案；否则 ``None``。"""
        from .credential_vault import looks_like_login_html, looks_like_login_url

        reason = ""
        if final_url != url and looks_like_login_url(final_url) and not looks_like_login_url(url):
            reason = f"重定向到登录页 {final_url}"
        else:
            content_type = response.headers.get("content-type", "")
            if any(marker in content_type.lower() for marker in self._HTML_CONTENT_TYPES):
                html_text, _ = decode_html(response.content, content_type)
                # 密码框 + （登录类 URL 或 正文极短）才判定，避免误伤带登录小组件的正文页
                if looks_like_login_html(html_text) and (
                    looks_like_login_url(final_url)
                    or len(_TAG_RE.sub(" ", html_text[:300_000]).split()) < _LOGIN_PAGE_MAX_WORDS
                ):
                    reason = "页面含密码输入框且无正文"
        if not reason:
            return None
        return (
            f"login_required: 携带 {credential_domain!r} 凭据访问仍被要求登录（{reason}）。"
            "凭据可能已失效：请在浏览器重新登录后 browser_cookies action=export 再试；"
            "或经 browser_launch + browser_navigate 真浏览器通道访问"
        )

    def _is_antibot_page(self, response: httpx.Response, content: Dict[str, Any]) -> bool:
        """2xx 但正文是反爬盾页（Cloudflare 5 秒盾常以 200/503 + 验证页返回）。"""
        content_type = response.headers.get("content-type", "")
        if not any(marker in content_type.lower() for marker in self._HTML_CONTENT_TYPES):
            return False
        html_text, _ = decode_html(response.content, content_type)
        return looks_like_antibot_page(html_text, str(content.get("content", "")))

    def _escalate(
        self,
        url: str,
        network_policy: NetworkPolicy,
        mode: str,
        wait_for: str,
        blocked: _AntibotBlocked,
    ) -> Dict[str, Any]:
        """AB1 升级链：渲染池重放；渲染结果仍是盾页 / 拒绝状态 → 抛 RenderError 附指引。"""
        try:
            rendered = web_render.render_page(url, network_policy, wait_for=wait_for)
        except RenderError as exc:
            raise RenderError(
                f"{blocked.reason}；已尝试真浏览器通道仍失败：{exc}{_ANTIBOT_GUIDANCE}"
            ) from exc
        rendered_status = rendered.get("rendered_status")
        rendered_text = str(rendered.get("content", ""))
        if (isinstance(rendered_status, int) and rendered_status in _ANTIBOT_STATUS_CODES) or (
            looks_like_antibot_page(rendered_text, rendered_text)
        ):
            status_note = f"（渲染状态码 {rendered_status}）" if rendered_status else ""
            raise RenderError(
                f"{blocked.reason}；真浏览器通道同样被拦截{status_note}{_ANTIBOT_GUIDANCE}"
            )
        content: Dict[str, Any] = {
            "url": rendered.get("url", url),
            "status_code": rendered_status or 200,
            "content_type": "text/html",
            "encoding": "utf-8",
            "mode": mode,
            "title": rendered.get("title", ""),
            "content": rendered_text,
            "rendered": True,
            "escalated": "render",
            "escalated_from": blocked.reason,
        }
        if mode == "links":
            content["links"] = list(rendered.get("links") or [])[: self._policy.max_result_items]
        elif mode == "tables":
            content["tables"] = list(rendered.get("tables") or [])[: self._policy.max_result_items]
        elif mode == "files":
            content["files"] = file_links.extract_file_links(
                str(rendered.get("html") or ""), str(content.get("url") or url)
            )
        return content

    def _should_render(
        self, render: str, response: httpx.Response, content: Dict[str, Any], max_length: int
    ) -> bool:
        """判定静态结果是否需要 JS 渲染降级（W1）。

        raw / 非 HTML 恒不渲染；``never`` 关闭；``always`` 强制；``auto``
        交给 ``looks_like_js_shell``。max_length 低于壳判定阈值时跳过 auto
        —— 正文先被截断会使"正文过短"判定失真（长文的截断版像壳）。
        """
        if render == "never":
            return False
        if content.get("mode") == "raw" or content.get("kind") == "binary":
            return False
        content_type = response.headers.get("content-type", "")
        is_html = any(marker in content_type.lower() for marker in self._HTML_CONTENT_TYPES)
        if not is_html:
            return False
        if render == "always":
            return True
        if max_length < web_render.SHELL_TEXT_MIN_CHARS:
            return False
        html_text, _ = decode_html(response.content, content_type)
        return web_render.looks_like_js_shell(html_text, str(content.get("content", "")))

    def _render_dynamic(
        self,
        url: str,
        network_policy: NetworkPolicy,
        mode: str,
        max_length: int,
        static_content: Dict[str, Any],
        wait_for: str = "",
    ) -> Dict[str, Any]:
        """JS 壳命中后的渲染降级：headless 取渲染后正文（W1）。

        渲染失败抛 ``RenderError``（execute 单独捕获，不吞成通用失败）。
        渲染分支自 R1 起经 outerHTML 复用 html_extract，links/tables 与
        静态分支同构 —— 静态壳的残缺值被渲染值整体替换。
        """
        rendered = web_render.render_page(url, network_policy, wait_for=wait_for)
        content = dict(static_content)  # 保留 status_code / content_type / encoding / mode
        content.update({k: v for k, v in rendered.items() if k != "html"})
        content["content"] = str(rendered.get("content", ""))[:max_length]
        if mode == "links":
            content["links"] = list(rendered.get("links") or [])[: self._policy.max_result_items]
        elif mode == "tables":
            content["tables"] = list(rendered.get("tables") or [])[: self._policy.max_result_items]
        elif mode == "files":
            # 渲染后 DOM 里的候选（SPA 站的下载按钮常在 JS 之后才出现）与静态候选合并
            rendered_files = file_links.extract_file_links(
                str(rendered.get("html") or ""), str(content.get("url") or url)
            )
            content["files"] = file_links.merge_file_links(
                rendered_files, list(static_content.get("files") or [])
            )
        return content
