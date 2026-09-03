# 内网 Web 访问设计（2026-09-02）

> 状态: 已实施（2026-09-03）

## 背景与目标

`release/win7` 分支的目标用户在内网运行 Sage：无公网出口，但内网有知网 / 万方等
镜像站与若干资源站，部分站点有登录要求。当前有三个问题：

1. **`web_search` 必然失败，且 LLM 会反复尝试**。实现是抓取
   `https://html.duckduckgo.com/html/`（`backend/tools/web_tool.py:52`），内网下每次
   调用都走到超时。工具仍出现在 schema 里，模型看得见就会试。
2. **`web_fetch` 返回整页 HTML 的前 10000 字符**（`web_tool.py:230`），不做正文抽取。
   知网详情页大半是 `<script>` 与内联样式，等于用 token 换噪音。编码上直接取
   `response.text`，遇到 GBK / GB18030 的镜像站得到乱码。
3. **没有文件下载工具**。文献 PDF、资源站附件只能靠 `bash` + `curl`，走 EXEC 风险类
   审批，且不受工作区边界约束。

**目标**：内网可用的"读网页 + 下文件"能力，外加一个显式的网络模式门禁，让搜索类
出网工具在内网模式下对 LLM 不可见。

**非目标**（属于后续子系统，见 §9）：浏览器登录会话、LLM 驱动的点击与填表、
成功轨迹固化重放、批量抓取作业队列。

## 1. 网络策略领域模型

新增 `backend/domain/network_policy.py`。与 `domain/tool_policy.py`、`domain/risk.py`
同构：frozen dataclass + 纯查询方法，仅依赖标准库，不读文件 / 时钟 / 网络。
`backend/pyproject.toml` 的 import-linter 契约把 `backend.domain` 定为最内层，
domain 纯净性是硬约束。

```python
class NetworkMode(str, Enum):
    ONLINE   = "online"     # 现状：搜索可用，任意公网地址
    INTRANET = "intranet"   # 内网：搜索不注册，仅白名单 host
    OFFLINE  = "offline"    # 气隙：全部出网工具不注册

@dataclass(frozen=True)
class NetworkPolicy:
    mode: NetworkMode = NetworkMode.ONLINE
    allowed_hosts: Tuple[str, ...] = ()
    insecure_tls_hosts: Tuple[str, ...] = ()
```

公开方法：

| 方法 | 时机 | 语义 |
|---|---|---|
| `search_enabled() -> bool` | 注册期 | 仅 `ONLINE` 为 `True` |
| `fetch_enabled() -> bool` | 注册期 | `ONLINE` / `INTRANET` 为 `True`，`OFFLINE` 为 `False` |
| `check_host(url) -> Optional[str]` | 执行期 | 返回拒绝原因；`None` 表示放行。判定按模式分岔，见 §4 |
| `allows_insecure_tls(url) -> bool` | 执行期 | host 是否命中 `insecure_tls_hosts` |
| `from_config(dict) -> NetworkPolicy` | 加载期 | 缺字段回退默认 |

`web_search` 受 `search_enabled()` 门禁，`web_fetch` 与 `http_download` 受
`fetch_enabled()` 门禁 —— 所以 `OFFLINE` 是"三个出网工具全不注册"，`INTRANET` 是
"只有搜索不注册"。

### 1.1 三个设计决定

**通配只支持 `*.` 前缀，且要求至少两段。** `*.cnki.net` 匹配 `cnki.net` 自身及其
**任意层级**子域（`a.cnki.net`、`b.a.cnki.net` 都算命中）；`*` 与 `*.net` 在
`__post_init__` 中直接 `ValueError`。否则白名单形同虚设。匹配前 host 统一
`lower()` + 去尾点，避免 `A.CNKI.NET.` 绕过。

**`insecure_tls_hosts` 中每一项都必须被 `allowed_hosts` 覆盖**，同样在
`__post_init__` 校验。"覆盖"是按上述通配规则判定，不是字符串子集 —— 例如
`allowed_hosts=("*.example.internal",)` 覆盖 `insecure_tls_hosts=("docs.example.internal",)`。
这让"关闭 TLS 校验"在物理上无法作用于白名单外的 host。

**`intranet` / `offline` 下 `web_search` 不注册，而非返回错误。** LLM 看到工具就会
试，返回"该模式不可用"只是多烧一轮迭代，还可能反复重试。`ToolRegistry.get_schemas_for_llm`
已有先例：`requires_tool_context` 的工具在无上下文时直接不进 schema 列表
（`backend/tools/registry.py:144`）。走同一条路子。

### 1.2 风险分级不因内网而降级

`intranet` 模式下访问内网 host 仍归 `RiskClass.EXTERNAL` —— 副作用确实发生在本机
之外，这是事实。`read_only` 权限模式照样拒绝。不因"是内网"就降级，避免在
`backend/domain/risk.py` 的分级语义上开特例。

### 1.3 配置存储：preferences KV，不进 app_settings

存 `preferences` 表，key `network_policy`，value 为 JSON 字符串，category `network`。
需在 `SettingsRepository.KEYS`（`backend/data/settings_repo.py:18`）加这一个 key。

不走 `app_settings` blob 的理由：`permission_mode` 已经这么做了，
`src/pages/settings/GeneralTab.tsx:24-29` 有注释说明原因 —— `app_settings` 有
`LEGAL_TOP_KEYS` 白名单校验（`backend/data/settings_canonicalizer.py:47`），加新顶层
字段要同步改前端 `AppSettings`、后端白名单、契约测试三处；KV 只需加一个 key。

value 的合成示例（非真实内网地址）：

```json
{
  "mode": "intranet",
  "allowed_hosts": ["*.example-mirror.internal", "docs.example.internal"],
  "insecure_tls_hosts": ["docs.example.internal"]
}
```

`preferences` 表自带的 `updated_at`（epoch 秒）由 `SettingsRepository.set()` 现有逻辑
写入，本设计不改。

### 1.4 加载器

新增 `backend/tools/network_config.py`：`load_network_policy(repo=None) -> NetworkPolicy`。
惰性 import `SettingsRepository`，与 `backend/tools/permissions.py:388` 相同手法，避免
`tools` ↔ `data` 循环依赖。

**失败一律 fail-safe 到 `ONLINE`**（即现状行为）：JSON 解析失败、mode 值非法、
字段类型不对，全部回退默认并 `logger.warning`。理由是配置读不出来时不应该把用户
的既有能力锁死；这与 `load_tool_policy_from_config`
（`backend/application/services/tool_config.py:33`）的降级口径一致。

## 2. HTML 抽取层

新增 `backend/wiki/html_extract.py` —— 纯函数模块，无 IO。

`extract(html: str, base_url: str) -> ExtractedPage`，返回四段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | `str` | `<title>` 文本 |
| `text` | `str` | 正文，剥标签后规整空白 |
| `links` | `List[Dict[str, str]]` | `{text, url}`，相对链接对 `base_url` 做 `urljoin` 绝对化 |
| `tables` | `List[List[List[str]]]` | 二维数组的列表，文献列表页的核心 |

丢弃 `script` / `style` / `noscript` / `svg` / `template` 的**内容**（不只是标签）。

**只用 stdlib，不做 lxml 双实现。** 原型对比发现 lxml 的 `text_content()`
在嵌套表格上会把内层表格的文字并进外层单元格（`<td>外<table>...<td>内` →
lxml 得 `["外内", "右"]`，栈式实现得 `["外", "右"]` 加独立内层表），这是 DOM
语义的必然结果而非可修的 bug。加上 `requirements.txt` 并不声明 lxml，保留双
路径等于让抽取结果取决于环境里碰巧装了什么。实测 79 KB 页面 stdlib 44.8 ms、
lxml 22.5 ms，省下的时间相对一次网络请求可忽略。

`web_fetch` 新增 `mode` 参数控制返回哪些段：`text`（默认）/ `links` / `tables` /
`raw`。`raw` 保留现有整页行为作为逃生舱。

### 2.1 编码嗅探

优先级（任一步得到可解码结果即停）：

1. HTTP `Content-Type` 头的 `charset` —— 用 stdlib `email.message.Message.get_param('charset')`
   解析（已验证能正确处理 `text/html; charset=GBK`）
2. HTML 内的 `<meta charset=...>` / `<meta http-equiv="Content-Type">`
3. UTF-8 试解 —— 内网/公网场景下 UTF-8 仍占多数，先试命中率高
4. GB18030 兜底 —— 它是 GBK 的超集，能解 GBK 也能解 GB2312，覆盖内网镜像站
   的情形

全程 `errors="replace"`，绝不因编码问题抛异常。思路与 `backend/tools/file_tool.py:45`
的 `detect_bom_encoding` 一致 —— 先按显式声明，再按启发式，最后兜底。

## 3. 下载工具

新增 `backend/tools/download_tool.py`，工具名 `http_download`，
`risk = RiskClass.EXTERNAL`（出网 + 写盘，取更严的语义）。

- `httpx.stream()` 边下边写，不进内存
- 落盘路径必须过 `BaseTool._enforce_workspace()`（`backend/tools/base.py:115` 现成）。
  参数只接受工作区**相对**文件名，绝对路径直接拒
- 文件名净化：从 URL path 或 `Content-Disposition` 取名后，剥掉路径分隔符与 `..`，
  只保留 basename
- 双重大小上限：先看 `Content-Length`，超限立即拒；**同时**在流式写入时累计实际
  字节数，超限则中断并删除半成品 —— `Content-Length` 是服务器说的，不可信
- 成功后调 `_record_artifact_safely`（`file_tool.py:107`）挂进 Artifacts 面板，
  用户在 UI 里能直接看到下载结果

### 3.1 未绑定工作区时拒绝下载

`BaseTool._enforce_workspace` 在 `policy.workspace_root` 为 `None` 时**返回 `None`
（放行）**（`backend/tools/base.py:125-127`）。legacy 聊天链路在会话没有绑定
workspace 时确实是 `None`（`backend/api/legacy_routes.py:2001` 只在有 binding 时
才填值），照抄 `office_create_tool.py:340` 的用法会让 `http_download` 在无绑定时
可以往任意路径写文件。

因此 `http_download` **不能只依赖 `_enforce_workspace`**：`workspace_root` 未绑定时
直接返回失败，提示用户先绑定工作区。这与 `office_create_tool` 的"未绑定时零行为
变化"取向不同，理由是下载的字节来自网络而非本地已有内容，写入位置不确定的风险
更高。

## 4. SSRF 防护扩面

现状：`WebFetchTool` 的字面量公网 IP 校验只在 `policy.subagent_only` 时生效
（`backend/tools/web_tool.py:217`），主 agent 路径没有 DNS 重绑定防护。

`intranet` 模式下不能照搬这套规则 —— 内网 host 解析出的就是私有 IP，按公网规则会
全部拒绝。执行期新规则，按模式分岔：

```
online   → check_host 恒返回 None（allowed_hosts 在此模式下完全不参与判定）
            继续走现状：subagent_only 时做字面量公网 IP 校验
intranet → check_host 判定 host 是否命中 allowed_hosts
            命中 → 放行，且跳过公网 IP 校验（内网私有 IP 是预期的）
            未命中 → 拒，返回原因
offline  → 不适用：web_fetch / http_download 在此模式下根本不注册（§1.1）
```

`online` 分支是刻意的：该路径行为完全不变，避免回归。`allowed_hosts` 只在
`intranet` 下生效 —— 用户在 `online` 模式填的白名单不会意外收紧访问范围。

重定向：`online` 沿用现有 `follow_redirects=False` + 显式校验；`intranet` 下重定向
目标同样要过 `check_host`。不额外做重定向次数以外的防护 —— 白名单已经覆盖了重定向
到内网元数据端点这类攻击面。

### 4.1 白名单为空时的 intranet 语义

`intranet` + `allowed_hosts=()` 时，`check_host` 拒绝**一切** URL。这是刻意的
fail-closed：用户切到内网模式却没填白名单，结果应该是"什么都访问不了"而不是
"什么都能访问"。UI 上此时在 NetworkTab 显示提示，引导用户添加 host。

注意这与 §1.4 加载器的 fail-safe 方向相反 —— 那里是"配置**读不出来**回退 ONLINE"
（不锁死用户既有能力），这里是"配置**读出来了且明确是 intranet**，就严格执行"。
两者不矛盾：前者处理故障，后者执行意图。

## 5. 接线点

有**四条**工具注册路径，都要过门禁 —— 这是最容易漏的地方：

| 路径 | 位置 | 用途 |
|---|---|---|
| `register_all_tools` | `backend/tools/__init__.py:49` | 主路径 |
| `build_readonly_tool_registry` | `backend/tools/agent_tool.py:189` | 子代理 |
| `InprocToolAdapter` | `backend/adapters/out/tool/inproc_adapter.py:73` | hex API（转调 ①） |
| `SageAgent.__init__` | `backend/core/legacy/agent.py:277` | legacy（转调 ①） |

③ ④ 都转调 ①，因此真正需要改的是 ① 与 ②。

### 5.1 两种时机，不是一种

**注册决策**（`web_search` 要不要出现在 schema 里）在**注册时**读策略。这是"LLM 根本
看不见"的唯一实现方式。

**host 校验**在**执行时**读策略。这样用户在设置页改完白名单立即生效，不必重开会话。

执行期读一次 sqlite KV 的开销，项目已经接受过：`inproc_adapter.py:66` 的
`load_enforcer_from_settings` 就是每次 execute 现读现建，注释写明理由是"逐调用读取
换取用户规则 / 模式变更即时生效，不做缓存"。沿用同一口径。

### 5.2 为什么不把 NetworkPolicy 塞进 ToolPolicy

`_subagent_policy`（`backend/tools/agent_tool.py:165-181`）是**逐字段重建**
`ToolPolicy` 的。给 `ToolPolicy` 加字段会被这里静默丢弃 —— 子代理拿到默认策略，
门禁在子代理路径上失效，而且没有测试能自然抓到这种遗漏。

所以 `NetworkPolicy` 走独立参数传递，不寄生在 `ToolPolicy` 上。

### 5.3 agent profile：web_search 无需改，http_download 需要加

`backend/agents/profiles.py:98` 的 researcher 白名单含 `web_search`，**这一项不用动**：
`get_schemas_for_llm` 是遍历**已注册**工具再按白名单过滤
（`backend/tools/registry.py:140-148`）—— 未注册的工具自然不出现。白名单提到一个
不存在的工具是无害的。

`http_download` 是新工具，**必须**加进 profile 白名单才能被使用：researcher 加，
primary 不加（下载是明确的研究动作，不该是主助手的默认能力）。这是 §6 文件清单里
`profiles.py` 出现的唯一原因。

## 6. 文件清单

新增：

```
backend/domain/network_policy.py           # NetworkMode + NetworkPolicy（纯）
backend/tools/network_config.py            # 从 settings KV 加载
backend/wiki/html_extract.py               # HTML→text/links/tables（纯函数）
backend/tools/download_tool.py             # http_download
src/pages/settings/NetworkTab.tsx          # 模式选择 + 两个 host 列表编辑
```

修改：

```
backend/tools/web_tool.py                  # 抽取层重写 + 编码嗅探 + host 校验
backend/tools/__init__.py                  # 条件注册 + 注册 http_download
backend/tools/agent_tool.py                # 子代理路径同样门禁
backend/domain/risk.py                     # EXTERNAL_TOOLS 加 http_download
backend/data/settings_repo.py              # KEYS 加 network_policy
backend/agents/profiles.py                 # researcher 加 http_download
src/pages/settings/Settings.tsx            # tabs 加"网络"
src/shared/api/settingsClient.ts           # PreferenceKey 加 network_policy
src/shared/lib/i18n/{zh,en}.ts             # 文案
docs/superpowers/specs/README.md           # 章节目录追加本 spec
```

`GeneralTab.tsx` 已 287 行，host 列表的增删 UI 塞进去会臃肿，故独立成 tab。

## 7. 测试策略

CI 对 backend 是 coverage ≥ 80% 硬门禁（`.github/workflows/ci.yml:127` 主分支 py3.11、
`:56` win7 py3.8 两处均 `--cov-fail-under=80`）。`respx==0.21.1` 已在
`backend/requirements-dev.txt`，httpx mock 直接可用。

| 测试文件 | 覆盖点 |
|---|---|
| `test_network_policy.py`（新） | 通配匹配；`*` 与 `*.net` 必须被拒；`insecure_tls_hosts` 子集校验；三种模式的 `search_enabled` / `check_host`；host 大小写与尾点归一 |
| `test_html_extract.py`（新） | script/style 内容剥离；相对链接绝对化；表格抽取；嵌套表格保持内外分离；编码嗅探各路径；畸形/残缺标签不崩 |
| `test_http_download.py`（新） | 流式落盘；`Content-Length` 撒谎时按实际字节中断并清理半成品；绝对路径拒绝；`../` 文件名净化；**`workspace_root=None` 时拒绝下载**（§3.1） |
| `test_web_tool.py`（扩充） | GBK 页面解码；三种模式门禁；白名单 host 跳过公网 IP 检查；`online` 模式无回归 |
| `test_network_config.py`（新） | JSON 损坏 / mode 非法 / 类型错误 → fail-safe 到 ONLINE |
| `test_network_policy.py`（新，续） | `intranet` + 空白名单 → 拒绝一切（§4.1 fail-closed） |

两处**现有测试必须同步更新**，否则会红：

- `backend/tests/unit/test_tools_registry.py:175` 硬编码期望内置工具集合含 `web_search`
- `backend/tests/unit/test_risk.py:240` 的验收表需加 `http_download → EXTERNAL`。
  `backend/tools/base.py:106` 的 fail-open 警示明确要求新工具同步扩这张表 ——
  漏写 `risk` 的副作用工具会被静默判为 READ

## 8. 双分支落地

按已确认的顺序：**先在 main 实现并跑通，再 cherry-pick 到 release/win7**。

cherry-pick 时的 py3.8 适配预案（照 `backend/tools/base.py:1` 的成例）：

- 新模块一律 `from __future__ import annotations`
- 注解用 `typing.Tuple` / `Dict` / `Optional`，不用 PEP 585 / 604 的运行时形式
- 文件顶部 `# ruff: noqa: UP006, UP007, UP035, UP045`

本子系统的工具都是同步的，不涉及 `asyncio.TimeoutError` 在 3.8 与 3.11 的差异
（该差异已在 `backend/services/question_gate.py:138` 处理过）。

已知的 py3.8 风险点：`web_tool.py` 在 win7 分支有一处分歧 —— IPv4-mapped IPv6 的
解包（`ipaddress` 在 3.8 不解包 `::ffff:x.x.x.x`）。重写抽取层时**不要动**
`_literal_ip`，避免与该分支修改冲突。

## 9. 后续子系统（不在本 spec 范围）

已确认的整体拆分与顺序：

| # | 子系统 | 状态 |
|---|---|---|
| 1 | 网络模式门禁 | **本 spec** |
| 2 | HTTP 取页与下载 | **本 spec** |
| 3 | 浏览器会话桥（持久 partition + 手动登录 + cookie 导出 + NDJSON 指令通道） | 待设计 |
| 4 | LLM 驱动的浏览器工具（snapshot/click/type/download + 逐 host 授权） | 待设计 |
| 5 | 轨迹固化与重放 | 待设计 |

子系统 3 的形态已定：Electron 内置浏览器只负责持有登录态（`persist:sage-web`
partition），批量抓取走 Python httpx + 导出的 cookie，硬骨头页面才走浏览器。
Electron 21.4.4 的 API 可用性已核实：`Session.fromPartition`、`will-download` +
`DownloadItem.setSavePath`、`session.cookies`、`webRequest.onBeforeRequest`、
`setCertificateVerifyProc`、`webContents.debugger.sendCommand`（CDP）全部具备。

子系统 4 的三个安全决定（待实施时确认）：点击 / 填表按 host 授权一次而非每次审批；
`browser_evaluate` 归 `EXEC` 风险类，只读模式拒；cookie 值永不出现在工具结果与日志
中，仅在服务端注入。

轨迹记录会在子系统 4 中就埋好（近乎零成本），子系统 5 只是加存取与重放。

