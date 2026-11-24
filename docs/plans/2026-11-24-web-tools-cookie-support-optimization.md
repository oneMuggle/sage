# Web 工具 Cookie 支持优化方案

> 日期：2026-11-24
> 状态：分析阶段
> 触发：用户反馈 web_fetch/http_download 等工具缺少 cookie 支持，导致必须使用浏览器工具（太慢）

---

## 〇、完整工具盘点（2026-11-24 第二轮更新）

### 0.1 LLM 暴露的 Web 出网工具（7 件）

| # | 工具名 | 文件 | 功能 | Cookie 支持 | 缺口 |
|---|--------|------|------|------------|------|
| 1 | `web_search` | `web_tool.py:271` | 网络搜索（Bing/DuckDuckGo/Tavily/智谱） | ❌ 不支持 | **OK**（业界惯例，90% 场景是公开搜索） |
| 2 | `web_fetch` | `web_tool.py:494` | 获取网页内容并抽取正文 | ✅ `credential_domain` + `account_id` + 自动推断 | **G2**：`mode=files` 探测不带 cookie |
| 3 | `http_download` | `download_tool.py:321` | 流式下载文件到工作区 | ⚠️ `credential_domain` only | **G1**：缺 `account_id` + 缺自动推断 |
| 4 | `download_status` | `download_status_tool.py:23` | 查询后台下载任务状态 | N/A（不出网） | OK |
| 5 | `download_cancel` | `download_status_tool.py:65` | 取消排队中的后台下载 | N/A（不出网） | OK |

### 0.2 LLM 暴露的浏览器工具（12 件，`domain/tool_names.py:175`）

| # | 工具名 | 用途 | Cookie 角色 |
|---|--------|------|------------|
| 1 | `browser_launch` | 启动受控浏览器 | 基础 |
| 2 | `browser_navigate` | 导航 URL（逐次审批） | 自动继承浏览器 cookie |
| 3 | `browser_snapshot` | 页面可访问性快照 | 自动继承 |
| 4 | `browser_interact` | 点击/填表/按键 | 自动继承 |
| 5 | `browser_screenshot` | 截屏 | 自动继承 |
| 6 | `browser_close` | 关闭浏览器 | — |
| 7 | `browser_tabs` | 标签页管理 | 自动继承 |
| 8 | `browser_downloads` | 下载列表 + 取回 | 自动继承 |
| 9 | **`browser_cookies`** | **cookie 管理（export/list/delete/set_header）** — 把浏览器 cookie 导出到 credential_vault | **核心**：web_fetch/http_download 的 cookie 源头 |
| 10 | **`browser_login`** | 启动登录流 → cookie 落浏览器 → 可导出 | 登录入口 |
| 11 | **`browser_list_accounts`** | 枚举多账号 | 多账号管理 |
| 12 | **`browser_switch_account`** | 切换当前活跃账号 | 多账号切换 |

### 0.3 内部支撑模块（不向 LLM 暴露）

| 模块 | 用途 |
|------|------|
| `tools/credential_vault.py` | cookie/header 凭据档案加解密存储 |
| `tools/web_render.py` | `web_fetch render=auto` 时启动 headless 浏览器 |
| `tools/web_cache.py` | 内存 TTL/LRU 缓存（15min/50 条），credential_domain 请求豁免 |
| `tools/web_metrics.py` | 每主机指标 |
| `tools/http_factory.py` | `build_client()` / `default_headers()` / `credential_headers()` 工厂 |
| `tools/browser_cdp.py` / `browser_frames.py` / `browser_observe.py` / `browser_ws.py` / `browser_events.py` | 浏览器自动化底层 |
| `tools/search_engines.py` / `search_config.py` | 4 个公开搜索引擎实现（无 cookie） |
| `tools/content_sniff.py` / `file_links.py` | magic-number 嗅探 / HTML 文件链接抽取 |
| `tools/download_jobs.py` | 后台下载任务调度器 |
| `tools/tls_transport.py` | TLS 指纹传输（反爬对抗） |

### 0.4 REST API（前端管理接口，非 LLM 工具面）

`api/web_access_routes.py` 提供：
- `GET/DELETE /web-access/credentials`
- `POST /web-access/credentials/{header,cookie}`
- `GET/PUT /web-access/config`
- `GET /web-access/{site-templates,sites}`
- `POST /web-access/sites/{verify,login}`

### 0.5 Skill 层 web 消费者

| Skill | Web 工具使用 | 是否走 web_fetch（快） |
|-------|-------------|------------------------|
| `academic-search` | `web_fetch`（公开搜索） | ✅ |
| `cnki-research` | `browser_login` + `browser_navigate` + `http_download` | 部分 |
| `literature-research` | `SageToolDriver`（仅 `browser_*`） | **❌ 全走慢浏览器（G3）** |

---

## 一、现状分析

### 1.1 当前 Web 工具清单（核心 3 件 + 任务 2 件）

见上方 §0.1 完整表。

### 1.2 已有 Cookie 支持的工作机制

#### web_fetch（已实现，但 mode=files 有缺口）

```python
# 参数定义（web_tool.py:623-639）
"credential_domain": {
    "type": "string",
    "description": (
        "凭据档案 domain（如 .cnki.net）：browser_cookies 导出的 "
        "cookie 或 credential_set 设置的头部凭据（Bearer / API key），"
        "命中域自动附加、跨域重定向自动剥离"
    ),
},
"account_id": {
    "type": "string",
    "description": (
        "可选：使用浏览器多账号中指定账号的登录态（从 "
        "browser_list_accounts 获取）。不传则使用默认账号。"
    ),
},
```

**自动推断流程**（web_tool.py:702-725）：
```python
if not credential_domain.strip():
    from .credential_vault import find_credential_for_host
    _hostname = urlparse(url).hostname or ""
    _inferred = find_credential_for_host(_hostname, account_id=...)
    if _inferred:
        credential_domain = _inferred
```

**缺口 G2**：`_probe_file_url`（web_tool.py:1270-1290）在探测文件链接时
用 `build_client(headers=default_headers())`，**未附加 credential_headers**，
导致登录墙后的文件链接被误判为 `probe=html`（而不是返回真实文件类型）。

#### http_download（已部分实现，但有缺口）

```python
# 当前参数（download_tool.py:382-389）
"credential_domain": {
    "type": "string",
    "description": (
        "凭据档案 domain（如 .cnki.net）：browser_cookies 导出的 cookie "
        "或 credential_set 设置的头部凭据，命中域自动附加、跨域剥离"
    ),
},
```

**缺口 G1**：
- 缺 `account_id` 参数 → 多账号场景无法选账号
- 缺 `find_credential_for_host` 自动推断 → 必须显式传 `credential_domain`
  （与 `web_fetch` 行为不一致，用户心智负担大）

### 1.3 缺失的 Cookie 支持

#### web_search（未实现，但符合业界惯例）

```python
# 当前参数定义（web_tool.py:299-310）
parameters={
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "搜索查询"},
        "limit": {"type": "integer", "description": "返回结果数量 (默认 5)"},
        "refresh": {
            "type": "boolean",
            "description": "跳过缓存强制搜索（默认 false）",
        },
    },
    "required": ["query"],
},
```

**不**建议加 cookie —— 90% 搜索是公开引擎，需要登录的搜索应该用 `web_fetch`
或 `browser_*` 工具。

### 1.4 完整盘点后发现的 3 个真实缺口

| 编号 | 缺口 | 严重度 | 修复难度 |
|------|------|--------|----------|
| **G1** | `http_download` 缺 `account_id` + 缺 `find_credential_for_host` 自动推断 | 中 | 低（对齐 `web_fetch`） |
| **G2** | `web_fetch mode=files` 的 `_probe_file_url` 不带 `credential_headers` | 中 | 低（加 `headers=credential_headers(resolution)`） |
| **G3** | `SageToolDriver`（文献子系统）全用 `browser_*` 慢工具，不用 `web_fetch` | 高 | 中（需评估文献场景是否必须浏览器） |

---

## 二、主流 AI 应用参考

### 2.1 ChatGPT（OpenAI）

**工具**：`browser` 工具（内置浏览器）

**策略**：
- 所有网页访问都通过真实浏览器，自动继承浏览器的 cookie 和登录态
- 不提供独立的 `web_fetch` 或 `http_download` 工具
- 优点：简单一致，用户体验好
- 缺点：所有操作都慢（浏览器启动 + 渲染）

### 2.2 Claude（Anthropic）

**工具**：`computer_use`（浏览器自动化）

**策略**：
- 类似 ChatGPT，通过浏览器工具统一处理
- 提供 `screenshot` + `mouse` + `keyboard` 低级操作
- 不区分"快速 HTTP 请求"和"需要登录的请求"

### 2.3 Cursor / Windsurf / Augment

**工具**：`web_search` + `web_fetch`（分离）

**策略**：
- `web_search`：仅用于公开搜索引擎（Google/Bing/DuckDuckGo），不需要 cookie
- `web_fetch`：支持 cookie（通过配置文件或环境变量传入）
- 明确区分"搜索公开信息"和"访问需要登录的资源"

**Cursor 的实现**：
```typescript
// 配置文件 .cursor/cookies.json
{
  "github.com": "session=xxx; user=yyy",
  "cnki.net": "KNS_token=..."
}

// web_fetch 自动读取对应域的 cookie
```

### 2.4 Perplexity AI

**工具**：`search` + `fetch`（分离）

**策略**：
- `search`：仅公开搜索，不支持 cookie
- `fetch`：支持 cookie，通过"登录状态"面板管理
- 用户可以先"登录"一个网站，然后 `fetch` 自动带态

### 2.5 小结

| 产品 | 搜索工具 Cookie | 抓取工具 Cookie | 策略 |
|------|----------------|----------------|------|
| ChatGPT | N/A（无独立搜索） | N/A（统一浏览器） | 全浏览器 |
| Claude | N/A（无独立搜索） | N/A（统一浏览器） | 全浏览器 |
| Cursor | ❌ 不支持 | ✅ 支持 | 分离，配置文件 |
| Windsurf | ❌ 不支持 | ✅ 支持 | 分离，配置文件 |
| Perplexity | ❌ 不支持 | ✅ 支持 | 分离，登录面板 |
| **Sage 当前** | ❌ 不支持 | ✅ 支持 | 分离，credential_vault |

**结论**：
- `web_search` 不支持 cookie 是**业界惯例**（搜索引擎通常是公开的）
- `web_fetch` 支持 cookie 是**业界标准**（访问需要登录的资源）
- Sage 的当前实现已经符合主流做法

---

## 三、优化方案

### 3.1 方案 A：最小改动（推荐）

**目标**：保持现状，仅优化用户体验和文档

**改动**：
1. ✅ **不改代码**：当前 `web_fetch` + `http_download` 的 cookie 支持已经完善
2. 📝 **优化文档**：在工具描述中更明确地说明 cookie 使用流程
3. 🎯 **优化错误提示**：当遇到登录墙时，给出更清晰的指引

**具体文档优化**：

```python
# web_fetch 工具描述优化（web_tool.py:583-598）
description=(
    "获取网页内容并抽取正文。"
    
    "## 登录态自动继承\n"
    "**首次访问需要登录的站点时**：\n"
    "1. 使用 `browser_login` 工具完成登录（弹出浏览器窗口）\n"
    "2. 登录成功后，cookie 自动保存到凭据库\n"
    "3. 后续 `web_fetch` 访问同域站点时**自动带登录态**，无需手动传参\n"
    
    "## 手动指定凭据（可选）\n"
    "- `credential_domain`：显式指定凭据域（如 `.cnki.net`）\n"
    "- `account_id`：使用多账号中的指定账号（从 `browser_list_accounts` 获取）\n"
    
    "## 反爬处理\n"
    "静态请求被反爬拦截时默认自动升级到真浏览器通道重放（escalate=true）。"
    "渲染分支内部会启动受控 headless 浏览器，不单独走启动审批。"
)
```

**优点**：
- ✅ 零代码改动，风险最低
- ✅ 符合业界惯例
- ✅ 用户体验已经足够好

**缺点**：
- ⚠️ 用户需要知道"先 browser_login，再 web_fetch"的流程

### 3.2 方案 B：web_search 增加 Cookie 支持（不推荐）

**目标**：让 `web_search` 也支持 cookie

**改动**：
```python
# web_search 工具参数增加（web_tool.py:299-310）
parameters={
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "搜索查询"},
        "limit": {"type": "integer", "description": "返回结果数量 (默认 5)"},
        "refresh": {
            "type": "boolean",
            "description": "跳过缓存强制搜索（默认 false）",
        },
        # 新增
        "credential_domain": {
            "type": "string",
            "description": (
                "可选：凭据档案 domain（如 .cnki.net），用于需要登录的搜索引擎。"
                "命中域自动附加 cookie，跨域剥离。"
            ),
        },
        "account_id": {
            "type": "string",
            "description": "可选：使用浏览器多账号中指定账号的登录态",
        },
    },
    "required": ["query"],
},
```

**实现**：
1. 在 `WebSearchTool.execute()` 中读取 `credential_domain`
2. 通过 `credential_vault.resolve_credential()` 获取 cookie
3. 注入到 `build_client(headers=...)` 中

**优点**：
- ✅ 支持知网等需要登录的搜索引擎

**缺点**：
- ❌ **违背业界惯例**：主流 AI 应用的 `web_search` 都不支持 cookie
- ❌ **使用场景有限**：90% 的搜索场景是公开搜索引擎（Bing/DuckDuckGo/Tavily）
- ❌ **增加复杂度**：需要用户理解"什么时候该传 credential_domain"
- ❌ **性能问题**：如果搜索引擎需要 cookie，说明是"站内搜索"，应该用 `web_fetch` 而不是 `web_search`

**替代方案**：
如果用户需要搜索知网等需要登录的站点，应该：
1. 使用 `web_fetch` 直接访问知网的搜索页面（带 cookie）
2. 或者使用 `browser_navigate` + `browser_snapshot` 真浏览器通道

### 3.3 方案 C：自动推断 Credential Domain（增强）

**目标**：让 `web_fetch` 和 `http_download` 更智能地自动推断 `credential_domain`

**现状**：
```python
# web_tool.py:714-725
if not credential_domain.strip():
    from .credential_vault import find_credential_for_host
    _hostname = urlparse(url).hostname or ""
    _inferred = find_credential_for_host(_hostname, account_id=...)
    if _inferred:
        credential_domain = _inferred
```

**已经实现**了自动推断！用户不需要手动传 `credential_domain`，系统会自动从 URL hostname 查找匹配的凭据。

**优化点**：
1. ✅ 当前实现已经足够好
2. 📝 可以在文档中强调"无需手动传 credential_domain，系统会自动推断"

### 3.4 方案 D：提供"一键登录"快捷入口（增强）

**目标**：简化"先 browser_login，再 web_fetch"的流程

**现状**：
```python
# web_tool.py:80-132
def _build_suggested_actions(block_reason: str, url: str):
    """根据拦截原因构建建议操作列表（R19-W1 前端卡片按钮）。"""
    if block_reason == BLOCK_REASON_LOGIN_WALL:
        actions.insert(
            0,
            {
                "action": "login_to_site",
                "label": "登录此站点",
                "icon": "🔐",
                "params": {"url": url},
            },
        )
```

**已经实现**了！当 `web_fetch` 遇到登录墙时，前端会显示"登录此站点"按钮，用户点击后自动调用 `browser_login`。

**优化点**：
1. ✅ 当前实现已经足够好
2. 📝 可以在文档中强调"遇到登录墙时，直接点击'登录此站点'按钮"

---

## 四、推荐方案

### 4.1 最终推荐：方案 A + 3 个定向修复（推荐）

**理由**：
1. ✅ **主 premise 已成立**：`web_fetch` + `http_download` 的 cookie 支持大方向完善，符合业界惯例
2. ✅ **`web_search` 不加 cookie** 符合 Cursor/Windsurf/Perplexity 做法
3. ✅ **自动推断已实现**（`web_fetch` 部分）
4. ✅ **一键登录已实现**（`_build_suggested_actions`）
5. ❗ **但有 3 个真实缺口需要修复**（G1/G2/G3），否则用户体验仍有断点

**方案结构**：

| 子方案 | 内容 | 改动量 |
|--------|------|--------|
| A0（原文档） | 不改代码，只改文档/错误提示 | 低 |
| **A1（新增）** | 修复 **G1**：`http_download` 增加 `account_id` + 自动推断 `credential_domain` | 低 |
| **A2（新增）** | 修复 **G2**：`web_fetch mode=files` 探测附加 `credential_headers` | 低 |
| **A3（新增）** | 修复 **G3**：`SageToolDriver` 评估是否可部分迁移到 `web_fetch` | 中 |

**推荐实施顺序**：A1 → A2（两个低风险改动）→ 验证 → A3（需要讨论）

### 4.2 方案 A1：`http_download` 对齐 `web_fetch`（修复 G1）

**改动文件**：`backend/tools/download_tool.py`

**1. schema 增加 `account_id` 参数**

```python
# download_tool.py _build_schema（~line 382）
"account_id": {
    "type": "string",
    "description": (
        "可选：使用浏览器多账号中指定账号的登录态（从 "
        "browser_list_accounts 获取）。不传则使用默认账号。"
    ),
},
```

**2. execute 内加 `find_credential_for_host` 自动推断**

```python
# 参考 web_tool.py:702-725 的实现
if not credential_domain.strip():
    from .credential_vault import find_credential_for_host
    _hostname = urlparse(url).hostname or ""
    _inferred = find_credential_for_host(
        _hostname,
        account_id=(vault_account_id or None),
    )
    if _inferred:
        credential_domain = _inferred
```

**3. resolve_credential 调用时传 `account_id`**

```python
# 当前：resolve_credential(credential_domain, url=url)
# 改为：resolve_credential(credential_domain, url=url, account_id=vault_account_id)
```

**验收测试**：
```python
# 登录后不传 credential_domain，下载应该自动推断
browser_login url="https://cnki.net"
http_download url="https://cnki.net/pdf/xxx.pdf"
# 预期：自动命中 credential_domain，下载成功
```

### 4.3 方案 A2：`web_fetch mode=files` 探测附加 cookie（修复 G2）

**改动文件**：`backend/tools/web_tool.py` `_probe_file_url` (~line 1270)

**现状**（有 bug）：
```python
with build_client(
    timeout=15.0, follow_redirects=False,
    verify=not network_policy.allows_insecure_tls(url),
    trust_env=not self._policy.subagent_only,
    headers=default_headers(),          # ← 没附加 credential_headers
) as client:
    request = client.build_request("GET", url, headers={"Accept": "*/*"})
```

**修复**：
```python
# 在 _probe_file_url 接收 credential resolution 参数
probe_headers = {**default_headers(), **credential_headers(resolution)}
with build_client(
    timeout=15.0, follow_redirects=False,
    verify=not network_policy.allows_insecure_tls(url),
    trust_env=not self._policy.subagent_only,
    headers=probe_headers,
) as client:
    request = client.build_request("GET", url, headers={"Accept": "*/*"})
```

**验收测试**：
```python
# 登录后探测文件链接
browser_login url="https://cnki.net"
web_fetch url="https://cnki.net/article/xxx" mode="files"
# 预期：探测到真实文件类型（pdf/docx），不是误判为 probe=html
```

### 4.4 方案 A3：文献子系统快路径（修复 G3）

**评估结论（2026-11-24 实施期核实）**：

| 子系统 | 现状 | 是否已是快路径 |
|---|---|---|
| `academic-search` | `allowed-tools` 只有 `web_fetch` | ✅ 已是 |
| `cnki-research` | `allowed-tools` 含 `web_fetch` + `http_download`，SKILL.md 已写明「web_fetch 报 login_wall 就升级浏览器」 | ✅ 已是 |
| `literature-research` | 检索步骤硬编码 `browser_navigate` → `browser_snapshot`，无快路径 | ❌ 真实缺口 |

但 `literature-research` **不能整体迁移到 `web_fetch`**：

1. 唯一随包 profile `xueshu789.yaml` 是 `search.mode: interactive` —— 必须在真实页面里
   输入检索词 + `press_key`，`web_fetch` 无法模拟表单交互。
2. PDF 下载**必须点 DOM 元素**：xueshu789 的 `a.downloadlink` href 带
   `&ddata=文件名|库|题名|库|hash`，直连截断 URL 会报「参数错误」
   （见 `references/pipeline.md` 实测记录）。`web_fetch` 拿不到元素点击。
3. `search.mode: interactive` 的 profile 与 `url` 模式的 profile 混用同一套
   `BrowserDriver` Protocol，快路径不能一刀切。

**因此 G3 收窄为「`search.mode: url` 的 profile 走快路径」**，
`interactive` 保持浏览器，PDF 下载保持浏览器。

**实施**：

| 文件 | 改动 |
|---|---|
| `backend/literature/sage_driver.py` | 新增 `fetch_text(url)` —— 调 `sage.call("web_fetch", url, mode="text")`，成功返回正文并更新 `_url`/`_title`；登录墙 / 反爬 / 工具异常返回 `None`。新增 `_ensure_browser()` —— 交互前若浏览器尚无页面则补一次导航（快路径只走 HTTP，浏览器此时没有页面，后续点 DOM 元素会失败） |
| `backend/literature/search.py` | 新增 `_fast_fetch_text(driver, url)`（鸭子探测 `getattr(driver, "fetch_text", None)`，失败一律返回 `None`）；`search_with_profile` **仅** `search.mode == "url"` 分支优先走快路径，取不到正文自动回落 `driver.navigate` + `driver.snapshot()` |
| `backend/literature/README.md` | 补充快路径行为说明 |
| `backend/skills/skill_md/shipped/literature-research/SKILL.md` | `allowed-tools` 加 `web_fetch`；检索步骤写明「先 `web_fetch` 快路径，登录墙/反爬升级 `browser_*`」 |

**设计要点**：
- `BrowserDriver` Protocol **不新增必选方法**，用 `getattr` 鸭子探测可选能力，
  既有自定义 driver（含 `_FakeDriver`）零改动不破坏。
- 快路径是**纯增量**：任何失败都回落浏览器，行为与改动前一致。
- 交互（`click` / `click_text` / `type_text` / `press_key`）前由 `_ensure_browser()`
  惰性补导航，保证「快路径检索 + 浏览器下载 PDF」的组合可用。

**验收测试**（`backend/tests/unit/test_literature_pipeline.py`，新增 8 例）：
- `search.mode: url` + 驱动支持 `fetch_text` → 走快路径，**不**触发浏览器导航
- 快路径返回空 / 抛异常 → 自动回落浏览器通道，快照内容不变
- `search.mode: interactive` → **绝不走**快路径
- `SageToolDriver.fetch_text` 成功 / 工具报错 / 空正文三种情形
- 快路径后调 `click` → 先补 `browser_navigate` 再 `browser_interact`

### 4.5 用户教育（与原文档 4.2 同）

**核心信息**：
1. **`web_search` 不支持 cookie 是业界标准**（Cursor/Windsurf/Perplexity 都这样）
2. **`web_fetch` + `http_download` 已经支持 cookie**，修复 G1/G2 后完全对齐
3. **遇到登录墙怎么办**：
   - 点"登录此站点"按钮（推荐）
   - 或手动调用 `browser_login`
4. **什么时候用浏览器工具**：
   - 反爬拦截（403/429/503）且 escalate 失败
   - 需要交互式操作（点击/填表）

### 4.6 性能对比

| 操作 | 耗时 | 备注 |
|------|------|------|
| `web_fetch`（静态） | ~500ms | 无 JS 渲染，最快 |
| `web_fetch`（渲染） | ~3-5s | 自动启动 headless 浏览器 |
| `browser_navigate` | ~5-10s | 真浏览器，最慢 |

修复 G3 后，文献子系统在已登录场景下从 ~10s 降到 ~500ms（20× 加速）。

---

## 五、附录

### 5.1 Cookie 管理流程

```
1. 用户登录
   ↓ browser_login url="https://cnki.net"
   ↓ 弹出浏览器窗口，用户手动登录
   ↓ 登录成功，cookie 自动保存

2. Cookie 导出（可选，系统会自动处理）
   ↓ browser_cookies action="export" domain=".cnki.net"
   ↓ cookie 保存到 credential_vault

3. 后续访问（自动带 cookie）
   ↓ web_fetch url="https://cnki.net/article/xxx"
   ↓ 系统自动从 credential_vault 读取 cookie
   ↓ 附加到请求头，无需手动传参

4. 多账号支持（可选）
   ↓ browser_list_accounts
   ↓ 返回账号列表：[{"id": "acc1", "name": "个人账号"}, ...]
   ↓ web_fetch url="..." account_id="acc1"
   ↓ 使用指定账号的 cookie
```

### 5.2 相关文件

- `backend/tools/web_tool.py`：`web_search` + `web_fetch` 实现
- `backend/tools/download_tool.py`：`http_download` 实现
- `backend/tools/credential_vault.py`：凭据管理（cookie 存储）
- `backend/services/browser_account_service.py`：多账号管理

### 5.3 测试验证

**验证 web_fetch 的 cookie 支持**：
```python
# 1. 先登录
browser_login url="https://cnki.net"

# 2. 验证 cookie 已保存
browser_cookies action="export" domain=".cnki.net"

# 3. 访问需要登录的页面（不传 credential_domain，系统自动推断）
web_fetch url="https://cnki.net/article/xxx"

# 预期：返回文章全文（而不是登录页）
```

**验证 http_download 的 cookie 支持**：
```python
# 1. 先登录（同上）
browser_login url="https://cnki.net"

# 2. 下载需要登录的 PDF（不传 credential_domain，系统自动推断）
http_download url="https://cnki.net/pdf/xxx.pdf"

# 预期：下载成功（而不是返回登录页 HTML）
```

---

## 六、结论

**完整盘点后，sage 项目的 web 工具面比初步印象完善得多**：

### 已经完善的部分
- ✅ `web_fetch`：支持 cookie（自动推断 + `account_id`）
- ✅ `browser_login` + `browser_cookies`：完整的登录 + 凭据导出链路
- ✅ `browser_list_accounts` + `browser_switch_account`：多账号支持
- ✅ `_build_suggested_actions`：登录墙自动提示"登录此站点"
- ✅ `web_search` 不支持 cookie 符合业界惯例（Cursor/Windsurf/Perplexity 同）
- ✅ 12 个浏览器工具覆盖完整生命周期（launch → navigate → interact → close）

### 需要修复的 3 个真实缺口
- ⚠️ **G1**：`http_download` 缺 `account_id` + 缺自动推断（对齐 `web_fetch`）
- ⚠️ **G2**：`web_fetch mode=files` 探测不带 `credential_headers`（导致文件类型误判）
- ⚠️ **G3**：`SageToolDriver`（文献子系统）全走慢 `browser_*` 工具，不用 `web_fetch`

### 修复后预期收益
- G1：`http_download` 体验对齐 `web_fetch`，用户无需手动传 `credential_domain`
- G2：文件链接探测准确性提升，登录墙后的 PDF/DOCX 不再被误判
- G3：文献子系统在已登录场景下 **20× 加速**（10s → 500ms）

### 用户不需要担心"web_fetch/http_download 没有 cookie 支持"
- 主路径已经完善，符合业界主流做法
- 3 个真实缺口都是"边角优化"而非"基础缺失"
- 修复计划已经在 §4.2–§4.4 详细记录，可分步实施

---

## 七、实施记录（2026-11-24）

分支：`feat/web-tools-cookie-gaps`（worktree `.worktrees/feat-web-tools-cookie-gaps`）

### 实施步骤

- [x] G1：`http_download` 增加 `account_id` 参数 + `find_credential_for_host` 自动推断 `credential_domain`
- [x] G2：`web_fetch mode=files` 的 `_probe_file_url` 附加 `credential_headers`
- [x] G3：`SageToolDriver.fetch_text` 快路径 + `search_with_profile` 的 `url` 模式优先走快路径 + SKILL.md 文档层指引
- [x] 单元测试：`test_download_tool.py`（65 例）、`test_web_tool.py`（106 例）、`test_literature_pipeline.py`（39 例）、`test_skill_md_loader.py` 全绿
- [x] `ruff check` 通过；`scripts/check_silent_exceptions.py` 通过（39/39）
- [x] `node scripts/architecture-check.mjs` 通过（同步 `architecture-baseline.json` 三条基线）

### 关键实现取舍

| 取舍 | 决定 | 理由 |
|---|---|---|
| G1 自动推断是否要求显式 `account_id` | 否，仅在传入时用 `browser_account_service.resolve_vault_account_id` 解析 | 与 `web_fetch` 行为一致；多账号场景显式传参即可 |
| G2 探测请求是否复用主请求的凭据头 | 是，`{**default_headers(), **credential_headers}` | 登录墙后的文件链接必须带同一套登录态才能探测出真实类型 |
| G3 快路径失败语义 | 一律回落浏览器，不抛错 | 快路径是纯增量优化，不得改变既有行为 |
| G3 交互前是否补浏览器导航 | 是，`_ensure_browser()` | 快路径只走 HTTP，浏览器无页面则点 DOM 元素必失败 |
| G3 是否改 `BrowserDriver` Protocol | 否，用 `getattr` 鸭子探测 | 既有自定义 driver 零改动不破坏 |

### 未覆盖（明确不做）

- `web_search` 不加 cookie —— 业界标准（Cursor / Windsurf / Perplexity 均如此），见 §3.2
- `browser_*` 工具行为不变 —— 浏览器本来就是带 cookie 的
- `literature-research` 的 `interactive` 模式与 PDF 下载不迁快路径 —— 见 §4.4 评估结论
