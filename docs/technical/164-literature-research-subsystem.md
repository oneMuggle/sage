# 164 · 文献研究子系统

> 面向开发者。本文描述 Sage 的文献调研与综述流水线：站点画像、检索执行、证据与 claims 核验、账本、四态报告与四维 Rubric、引用样式与导出。
> 底层真实浏览器动作见 [159 — 受控浏览器使用](./159-controlled-browser-use.md)；更早的 `academic-search` skill 与 `academic_adapters` 注册表见 [53 — 学术检索 skill](./53-academic-search-skill.md)。

## 1. 背景与定位

文献调研有两个天然难点：

1. **站点差异大**：入口页、搜索框、翻页、PDF 下载入口各不相同，把站点逻辑写进代码会不断新增分支。
2. **引用容易失真**：LLM 写作时可能编造文献、作者、年份或 DOI，事后难以逐条核对。

本子系统把这两件事拆开：

- **站点差异只在 YAML**：每个站点一份声明式 `SiteProfile`，pipeline 里没有 `if site == ...`。
- **LLM 负责语义，Python 负责确定性校验**：检索词、筛选、证据抽取、分节写作由 LLM 在 `execute_code` 中完成；URL 渲染、schema 校验、引用门禁、元数据核验、账本、报告、Rubric 与导出由 Python 完成。

代码位于 `backend/literature/`，是纯领域层，不反向依赖 `backend.tools` / `backend.api`。它对外的使用方式是随包分发的 `literature-research` skill（`backend/skills/skill_md/shipped/literature-research/`）：skill 里用 `execute_code` 调 Python 函数，用 `browser_*` / `web_fetch` 做真实页面操作。**不新增 chat 工具**，避免工具清单与能力门禁（ratchet）随每个里程碑膨胀。

与既有 `academic-search` skill 的衔接：`backend/skills/builtin/academic_adapters.py` 的 `get_site_adapter(name)` 先查内置注册表（目前只有 `cnki`），未命中时回退到 `profile_store.get_default_store()`，命中则返回 `ProfileBackedAdapter`。因此原有 `AcademicSearchSkill` 不改代码即可使用新站点。

整体分三层：

| 层 | 职责 | 主要模块 |
|---|---|---|
| 站点画像层 | 声明、校验、加载站点配置；渲染检索指导；适配旧接口 | `models.py` / `profile_store.py` / `guidance.py` / `academic_adapter.py` / `recording.py` |
| 检索与执行层 | 运行目录、驱动协议、交互式检索、PDF 下载 | `run_store.py` / `pipeline_models.py` / `search.py` / `sage_driver.py` |
| 核验与报告层 | 门禁、claims、元数据核验、Ledger、报告、Rubric、导出 | `gates.py` / `verify.py` / `support.py` / `ledger.py` / `report.py` / `rubric.py` / `export.py` / `cli.py` |

## 2. 站点画像（SiteProfile）

### 2.1 三层存储与优先级

`profile_store.SiteProfileStore.default()` 按“内置 < 用户 < 项目”的顺序加载，同 `id` 后出现的层覆盖前面的层：

| 层 | 目录 | 说明 |
|---|---|---|
| builtin | `backend/literature/sites/` | 随包发布；保持中立，不携带具体站点（示例见 `docs/templates/literature-sites/`） |
| user | `$SAGE_LITERATURE_SITES_DIR`，未设置时为 `~/.sage/literature_sites` | 用户自建站点 |
| project | `<cwd>/.sage/literature_sites/` | 项目级覆盖 |

- `discover()` 返回 `{id: SiteProfile}`；无效 YAML 或校验失败的 profile 会被跳过，并把 `SiteProfileError` 记录在内部错误表里。
- `get(id)` 在缺失或无效时抛错，错误信息里列出可用 id；`list_ids()` 返回全部可加载 id。
- `get_default_store()` / `reset_default_store()` 提供进程内单例，测试用后者重置。
- 每个 profile 的 `source_path` / `source_layer` 会记录实际来源，便于排查“为什么加载的是旧配置”。

### 2.2 领域模型与校验

`models.py` 用 frozen dataclass 定义配置与文献记录：

| 类型 | 关键字段 |
|---|---|
| `SiteProfile` | `id` / `display_name` / `home_url` / `domains` / `access` / `capabilities` / `search` / `detail` / `pdf` / `rate_limit` / `compliance` / `version` / `status` / `last_verified_at` / `source_path` / `source_layer` |
| `AccessSpec` / `LoginSpec` | `access.mode`（`browser`/`rest`/`hybrid`）；登录提示 `account_label` / `password_label` / `url_contains` / `title_not_contains` |
| `SearchSpec` | `url_template` / `wait_for` / `pagination` / `result_fields` / `mode`（`url`/`interactive`）/ `entry_url` / `entry_click` / `input_selectors` / `submit_key` / `wait_after_s` / `result_hint` |
| `DetailSpec` | `open_by` / `fields` |
| `PdfSpec` | `entry_selector` / `entry_text` / `forbid`（默认 `("CAJ",)`）/ `magic`（默认 `"%PDF-"`）/ `title_match` / `post_click_wait_s` / `interstitial` / `note` |
| `PdfInterstitialSpec` | `url_contains`（必填，识别中间页/跳转 URL）/ `host_fallbacks`（主机回退，按序替换、原域最后）/ `tab_timeout_s`（默认 6）/ `sleep_after_open_s`（默认 2.5）/ `attempt_timeout_s`（默认 15） |
| `RateLimitSpec` | `min_interval_s`（默认 5）/ `max_batch`（默认 20） |
| `ComplianceSpec` | `note` / `default_enabled`（默认 `False`） |
| `PaperRecord` | `paper_key` / `title` / `authors` / `year` / `venue` / `abstract` / `url` / `doi` / `source_site` / `source_query` / `retrieved_at` / `fulltext_path` / `language` / `extra` |

`profile_from_dict(raw, source_path, source_layer)` 负责校验：

- `id` 必须匹配 `^[a-z0-9][a-z0-9-]*$`；`home_url` 必须是 http(s)；`domains` 非空且只能写主机名（不带协议/路径）。
- `access.mode` ∈ `{browser, rest, hybrid}`；`search.mode` ∈ `{url, interactive}`。
- `capabilities.search` 为真时：
  - `url` 模式要求 `search.url_template` 非空且包含 `{query}`；
  - `interactive` 模式要求 `entry_url` 或 `url_template` 至少一个，且 `input_selectors` 非空，`wait_after_s` 不能为负。
- `status` ∈ `{ready, draft}`；`last_verified_at` 若存在必须为 `YYYY-MM-DD`。
- `access` / `capabilities` / `rate_limit` / `compliance` 缺省时按空对象处理；`pdf.entry` 支持字符串（selector）或 `{selector, text}` 两种写法。

`PaperRecord` 是跨站点统一结构，`paper_key` 是后续一切引用与证据的外键；序列化时 `authors` 由 tuple 转 list。

### 2.3 URL 渲染与主机白名单

`render_search_url(profile, query, limit=10)`：

1. `query` 去空白后不能为空；
2. 用 `str.format(query=quote(text, safe=""), limit=...)` 渲染模板；
3. 结果必须是 http(s) 且带主机名；
4. 主机名必须通过 `is_allowed_host(host, domains)` —— 等于 `domains` 中的某一项，或以 `.该项` 结尾，因此允许子域，但不允许跳出站点域名。

这层校验保证一个有问题的 profile 无法把检索请求指向任意主机。

`is_logged_in(profile, page_url, page_title)` 只做声明式判断：配置了 `url_contains` 时必须命中、配置了 `title_not_contains` 时不能出现，二者都满足返回 `True`，任一失败返回 `False`；没有配置任何检查项时返回 `None`（未知），交由 LLM 看页面判断。

### 2.4 检索指导（guidance）

`render_search_guidance(profile, query, limit, page_url, page_title)` 生成给 LLM 的纯文本指导，不执行浏览器。内容包括：

- 站点 `display_name (id)` 与 `profile 状态`（`draft` 时标注“选择器待录制”）；
- `url` 模式给出渲染后的检索 URL；`interactive` 模式给出入口 URL，并额外输出：入口点击、搜索输入框选择器、`press {submit_key}`、提交后等待秒数、结果提示；
- 登录态与登录检查项说明；结果等待选择器、翻页方式、结果字段、详情打开方式；
- PDF 下载入口、禁止格式、magic 与题名校验、点击后等待、备注；限速与合规说明；
- 最后要求 LLM 基于 `browser_snapshot` 解析页面，输出 JSON 数组（`paper_key, title, authors, year, venue, abstract, url, doi`），并明确禁止编造页面中不存在的文献或字段。

### 2.5 旧接口适配与站点录制

`ProfileBackedAdapter(profile)` 是 duck-typed 适配器，提供 `name` / `profile` / `build_search_url()` / `render_guidance()`，满足 `academic_adapters.AcademicSiteAdapter` 协议；`get_site_adapter` 的回退路径见 §1，`register_site_adapter` 可显式注册新适配器。

`recording.py` 支持从一次观测快速生成草稿 profile：

- `_with_defaults` 补齐 `status: draft`、`version: 0.1.0`、`last_verified_at` 为当天、`compliance` 默认 `{note: "仅本人账号/机构授权", default_enabled: False}`；
- `profile_draft_from_observation(raw)` / `write_profile_draft(raw, out_path)` 写出 YAML 草稿，随后用 `cli validate-profile` 校验。

### 2.6 示例 profile：浏览器登录 + 检索 + PDF 下载（xueshu789）

`docs/templates/literature-sites/xueshu789.yaml`（示例模板，不自动加载；复制到 `~/.sage/literature_sites/` 后启用）当前是 `status: ready`、`version: 0.4.0`、`last_verified_at: "2026-11-26"`：

| 项 | 值 |
|---|---|
| `display_name` | 学术资源站 |
| `domains` | `xueshu789.cc`、`82.157.23.222`（代理检索页主机） |
| `access` | `browser` + 表单登录；输入框提示“您的卡号 / 您的密码”；登录成功 `url_contains: /dbList/`；登录后标题不含“登录” |
| `search.mode` | `interactive` |
| 入口 | `https://www.xueshu789.cc/dbItem/3`（`entry_url` 与 `url_template` 相同） |
| 输入框 | `input[placeholder*='检索词']`、`textarea[placeholder*='检索词']` |
| 提交 | `Enter`；等待 5 秒；翻页 `click_text: 下一页` |
| PDF | 入口 selector `a.downloadlink`、文案“下载”、点击后等待 8 秒；禁止 `CAJ`；magic `%PDF-`；题名匹配开启 |
| 限速 | 每篇间隔 ≥ 5 秒，单批 ≤ 20 篇 |
| 合规 | `default_enabled: false`，需用户显式同意 |

实测结论（profile 的 `pdf.note`、`references/pipeline.md` 与 skill 文档一致）：

- `/dbItem/1` 代理返回“出错啦”；`/dbItem/2` 触发知网滑块验证（需人工完成）；`/dbItem/3` 可用，重定向到 `http://82.157.23.222:5888/kns8s/defaultresult/index`（标题“检索-中国知网”）。
- 搜索框 placeholder 含“检索词”；输入关键词后 Enter，约 5 秒出结果。
- 结果条目的题名/作者/来源链接指向 `https://www.xueshu789.cc/doDownload?url=...`，操作列有“下载 / 原版阅读 / CNKI AI阅读”。
- `a.downloadlink` 的真实 href 还带 `&ddata=<文件名>|<库>|<题名>|<库>|<hash>`；用快照里截断的 `doDownload?url=...` 直连会因缺少 `ddata` 报“参数错误”。
- **2026-11-26 起站点改为两段式下载**：`doDownload` → `301` → `/doDownload/`「文献下载中」中间页，约 `2s` 后 JS 跳 `downurl`；该站把 `downurl` 主机写死为 `oversea.cnki.net/docdown/fulltext/download?q=...`，国内库（CJFQ 等）内容在海外网关返回 CNKI 404「页面不存在」（与登录态/Referer/UA/cookie 无关，curl 复放排除）。同一 q/invoice token 换 `kns.cnki.net` 返回 `application/pdf`（实测 1,070,254B；浏览器内重写主机后 1,688,310B 落盘、`%PDF-1.6`、题名匹配）。
- 因此 profile 声明 `pdf.interstitial`（`url_contains: cnki.net/docdown`、`host_fallbacks: [kns.cnki.net]`），由 `download_pdf` 的中间页路径完成「入口 href → 新标签 → 等跳转 → 主机回退 → 校验」；发现中间页标签的识别基于 URL 子串，不依赖固定时序。
- 下载完成后新标签可能显示“页面不存在”，以 `DownloadResult.path` / 下载目录中的文件为准。

#### 2026-11-27 真机端到端实测（`main`）

在独立 worktree（`origin/main` 代码 + Electron 内嵌浏览器桥）上跑通完整链路，检索词 `人工智能 医学影像`：

| 环节 | 实测结果 |
|---|---|
| 站点画像 | 用户级 `~/.sage/literature_sites/xueshu789.yaml` v0.4.0，`pdf.interstitial` 生效 |
| 登录态 | `navigate(home_url)` 落到 `https://www.xueshu789.cc/dbList/1`（标题「文献下载_学术资源站」），快照含 `dbList` → 已登录 |
| 检索 | `search_with_profile(..., limit=20)` → `http://82.157.23.222:5888/kns8s/defaultresult/index`（标题「检索-中国知网」），结果表 `table.result-table-list` 命中 |
| 入口 href | `browser_interact(action="attr", attr_name="href")` 取到完整 `a.downloadlink` href（含 `&ddata=`） |
| 下载 | `download_pdf(..., entry_selector="table.result-table-list tbody tr:nth-child(1) a.downloadlink")` → `ok=True`、`errors=[]` |
| 产物 | `data/browser-downloads/8d6cbddae4c6/新兴医学影像技术在原发性骨肿瘤诊疗过程中的应用与发展_孙童.pdf`，907,103 B，文件头 `%PDF-1.6` |
| 题名核对 | pymupdf 解析 5 页 —— 《中国骨与关节杂志》2026 年 11 月第 15 卷第 11 期 1039–1043 页，与文件名题名一致 |
| 标签页 | 中间页标签由 `download_pdf` 关闭；结束后只剩 1 个工具标签（已被导航到候选下载 URL，遗留「页面不存在」属预期） |

两个实操细节：

- 结果行的 `td.name a` **没有 `title` 属性**，`browser_interact` 读 `title` 会报 `attribute-not-found`。此时 `expected_title` 传空串，`validate_pdf` 跳过题名比对，文件名依赖站点 `ddata` 参数自带（站点已给出题名，产物名与题名一致）。
- 受控浏览器的站点访问确认（`needs_confirmation`）在真机上由用户在右栏浏览器面板点确认；脚本化跑链路时需在工具进程内 resolve 该确认项并 `grant_site(..., "session")` 后重试，否则首个域名就会中断链路。

## 3. 检索与交互执行（M1a / M1b）

### 3.1 运行目录与写入契约

`run_store.py` 把一次调研变成一个可审计的运行目录。根目录由调用方传入，skill 使用 `<workspace>/.sage/literature_runs`；`create_run(root, topic, site_id, run_id=None)` 默认以 UTC 的 `%Y%m%d-%H%M%S` 作为 `run_id`，创建目录并写 `meta.json`。`load_run(run_dir)` 读取并校验既有运行。

写入 API：

| 函数 | 行为 |
|---|---|
| `record_query(run, query, site_id, result_count, note=None)` | 追加 `query_log.jsonl` |
| `record_papers(run, rows)` | 以 `paper_key` 去重后追加 `papers.jsonl`，返回新增条数 |
| `record_evidence(run, rows)` | 追加 `evidence.jsonl`；`paper_key` 必须已存在于文献池，否则抛错 |
| `save_claims(run, claims)` | 覆盖写 `claims.jsonl` |
| `save_outline(run, raw)` | 校验后写 `outline.json` |
| `save_draft(run, text)` | 原子写 `draft.md` |
| `list_papers` / `list_evidence` / `load_outline` / `read_draft` / `load_claims` | 读侧辅助 |

所有点写入使用“临时文件 + `os.replace`”的原子写；JSONL 追加也走统一的 helper。`run_status(run)` 汇总 `queries` / `papers` / `evidence` / `claims` 计数，以及 `has_outline` / `has_draft` / `has_verification` / `has_claims` / `has_metadata_verification` / `has_ledger` / `has_verification_report` / `has_rubric_review` 等标志。

### 3.2 BrowserDriver 协议与 search_with_profile

`search.py` 定义 `BrowserDriver` Protocol（结构化类型，不要求继承）：

```python
navigate(url, wait_for="") -> str          # 返回最终 page_url
snapshot() -> str
click(selector) -> None
click_text(text) -> None
type_text(selector, text, clear=True) -> bool
press_key(key) -> None
sleep(seconds) -> None
current_url() -> str
current_title() -> str
wait_download(timeout_s=60) -> Optional[str]
```

另有一个可选能力 `fetch_text(url) -> Optional[str]`：驱动若实现它，`url` 模式会先走快路径（`web_fetch` 正文），不实现则直接走浏览器。

`search_with_profile(profile, query, driver, limit=10)` 返回 `SearchObservation(url, page_url, page_title, guidance, snapshot)`：

- **`url` 模式**：先 `render_search_url`，再 `_fast_fetch_text`。若快路径返回非空正文，直接把正文当作 `snapshot` 返回；否则 `navigate(url, wait_for)` + `snapshot()` 回落浏览器。
- **`interactive` 模式**：绝不走快路径。依次执行：`navigate(entry_url 或 url_template)` → 若配置 `entry_click` 则 `click_text` + `sleep(1)` → 逐个尝试 `input_selectors`，直到某个 `type_text(selector, query, clear=True)` 返回 `True` → `press_key(submit_key)` → `sleep(wait_after_s)` → `snapshot()`。所有选择器都失败时抛 `RuntimeError("未找到可用的搜索输入框（检查 search.input_selectors）")`。

两种模式都会带上 `render_search_guidance`，并把 `current_url()` / `current_title()` 传给 guidance 做登录态判断。

### 3.3 SageToolDriver：把驱动映射到现有工具

`sage_driver.SageToolDriver(call)` 接收 `sage.call(name, **kwargs)` 形式的回调，是 skill 侧接入真实浏览器的薄适配层：

| Driver 方法 | 实际调用 |
|---|---|
| `navigate` | `browser_navigate`（可选 `wait_for`），返回并记录 `browser_meta.url` |
| `fetch_text` | `web_fetch(url=..., mode="text")`，取 `content`；异常/空正文返回 `None` |
| `snapshot` | `browser_snapshot(mode="full", max_nodes=250)`，结果 JSON 序列化为字符串 |
| `click` / `click_text` / `press_key` | `browser_interact(action="click"/"click"/"press", ...)` |
| `type_text` | `browser_interact(action="type", selector=..., value=..., clear=True)` |
| `sleep` | `time.sleep`，上限 30 秒（`_MAX_SLEEP_S`） |
| `wait_download` | `browser_downloads(wait_for_complete=True, timeout=...)`，按 `modified_at` 取最新一个已完成文件 |
| `current_url` / `current_title` | 最近一次 `browser_meta` |

两个细节：

- `type_text` 捕获工具抛出的 `RuntimeError` 并返回 `False`，让 `search_with_profile` 能继续尝试下一个选择器；其他方法失败时向上抛。
- `_ensure_browser()`：快路径 `fetch_text` 不启动浏览器；后续若要 `click` / `type_text` / `press_key`，会先懒导航回 `_url`，保证交互发生在真实页面上。

### 3.4 PDF 下载与文件校验

`download_pdf(profile, driver, expected_title, dest_dir, timeout_s=60, *, entry_url="", entry_selector="")`：

0. 若 profile 声明了 `pdf.interstitial`（两段式下载），优先走中间页路径：
   1. 取入口 href：`entry_url` 参数优先，否则用 `entry_selector`（缺省 `pdf.entry_selector`）经 `driver.element_attr(selector, "href")` 读取（完整 href 含站点签名参数）；
   2. `driver.open_tab(href)` 新开工具可见标签页，等待 `sleep_after_open_s` 让中间页跳转；
   3. `driver.tabs()` 轮询至 URL 命中 `url_contains`（上限 `tab_timeout_s`）；
   4. 按 `host_fallbacks` 生成候选 URL（回退主机在前、原域最后），逐个 `focus_tab` + `navigate` + `wait_download`（非最后一次尝试限 `attempt_timeout_s`）；导航报错（附件下载的 `ERR_ABORTED`）不阻断，继续等下载；
   5. 校验通过即关闭标签并返回；驱动缺 `element_attr`/`open_tab`/`tabs` 能力或拿不到 href 时回退到下面的原路径。
1. 若站点未配置 `pdf` 或没有入口，返回 `DownloadResult(None, False, [错误])`；
2. 优先用 `pdf.entry_selector`（`driver.click`），否则用 `pdf.entry_text`（`driver.click_text`）——**必须点 DOM 元素**，不能用截断 URL 直连；
3. 若配置 `post_click_wait_s` 则 `driver.sleep`；
4. `driver.wait_download()` 超时则失败；
5. `validate_pdf(path, expected_title, magic)` 检查：文件存在、文件头等于 magic（默认 `%PDF-`）、归一化后的文件名与题名互相包含；
6. 若 `pdf.forbid` 中的词出现在文件后缀里（如 `CAJ`）则记错误。

返回 `DownloadResult(path, ok, errors)`。部分站点的 `&ddata=` 附加参数坑与「中间页写错下载主机」坑（2026-11-26，xueshu789 oversea→kns）都是这一层设计的直接原因，见 §2.6。

### 3.5 交互式检索的边界

- 验证码/滑块只报告不破解；若入口页触发滑块，改用该站点 profile 中已验证可用的入口 URL。
- 限速由 `profile.rate_limit` 声明，guidance 会把它传给 LLM；执行层不做强制节流，由使用方遵守。
- 站点改版导致选择器失效时，先 `validate-profile` 与一次 dry-run 检索定位问题，必要时用 `draft-profile` 重新录制，不改 pipeline 代码。

## 4. 语义核验与报告（M2a–M2c）

### 4.1 引用语法与门禁

草稿中的引用只允许 `[cite:KEY]` 或 `[cite:KEY1, KEY2]`，`KEY` 必须是文献池中的 `paper_key`。`extract_citations` 按首次出现顺序返回去重后的 key 列表。

`run_gates(run)` 写 `verification.json`，`errors` 包含：

- 检索日志为空；文献池为空；
- 证据指向未知文献；
- 缺少 `outline.json`；大纲章节的 `source_keys` 指向未知文献；
- 缺少 `draft.md`；草稿引用未知文献。

`warnings` 记录“文献未被正文引用”（不阻断）。`GateReport(ok, errors, warnings, citations)` 中只有 `errors` 为空才允许导出。

`build_references(draft, papers, style)` 按首次引用顺序编号，只输出实际被引用的文献：

- **GB/T 7714**（默认）：`[n] 作者. 题名[J]. 刊名, 年.`；作者 ≤3 位用 `, ` 连接，>3 位取前 3 位 + `, 等`；缺失作者/刊名/年份时用“佚名 / [出版者不详] / [年份不详]”。
- **IEEE**：`[n] A. Author, "Title," Venue, Year.`；英文名缩写首字母（`John Smith` → `J. Smith`，单 token 原样），中文名保持原样；1 位、2 位、3 位分别用 `A`、`A and B`、`A, B, and C`，超过 3 位用第一作者 + `et al.`。
- `SUPPORTED_REFERENCE_STYLES = ("gbt7714", "ieee")`，其他样式抛 `ValueError`。

### 4.2 claims 账本与判定

`extract_claims(draft)`：按空行切段，每个含 `[cite:...]` 的非空段落生成一条 `Claim`，`claim_id` 依次为 `c0001`、`c0002`…，`section` 固定为 `"body"`，`text` 截断到 2000 字符。

`verify_claims(claims, paper_keys)` 做存在性与引用完整性判定：

| 情况 | verdict | notes |
|---|---|---|
| 无任何引用 key | `unsupported` | “claim 无引用 key” |
| 有 key 不在文献池 | `unresolved` | 列出缺失 key |
| 全部 key 在文献池 | `supported` | 置 `metadata_schema_ok=True` |

`verify.apply_evidence_support(claims, evidence)` 做证据级支持（Layer 3a）：`supported` 的 claim 若其被引论文没有任何 evidence 记录，改为 `flagged`，并在 notes 里指出缺证据的 key；原本 `unresolved` 的 claim 保持不变。

`support.apply_claim_support(claims, judgments)` 摄入 LLM 的语义判断（Layer 3b）：`support` 只能是 `supported` / `flagged` / `unsupported` / `unclear`，逐条校验后合并，追加 `rationale` / `evidence_refs`。**`unresolved` / `unsupported` 这类存在性问题优先级更高，不会被语义判定覆盖。**

`ClaimVerdict` 全集：`unverified` / `supported` / `flagged` / `unsupported` / `unresolved` / `unclear`；`pipeline_models.VALID_VERDICTS` 是校验用的集合。

### 4.3 外部元数据 2-of-3 核验

`verify.py`：

- `MetadataLookup` 协议 + 三个实现：`CrossrefLookup`（`api.crossref.org/works/{doi}`）、`OpenAlexLookup`（`api.openalex.org/works/{id}`）、`SemanticScholarLookup`（`api.semanticscholar.org/graph/v1/paper/...`）；`default_lookups()` 返回三者。
- `metadata_matches(paper, candidate)`：归一化题名相等、年份相等、作者有交集，三者都满足才算匹配。
- `verify_paper_metadata(paper, lookups, min_consensus=2)`：只有带 DOI / arXiv ID 的文献才查询（没有外部 ID → `skipped`）；匹配家数 ≥ `min_consensus` → `verified`，等于 1 → `partial`，0 → `unverified`。
- `verify_run_metadata(run, lookups, min_consensus=2)` 写 `metadata_verification.json`：`min_consensus`、`items[]`（含逐家 `checks`）、以及 `verified` / `partial` / `unverified` / `skipped` 计数。

### 4.4 EvidenceLedger

`ledger.py` 把证据、claim 与外部来源统一成 `LedgerEntry(entry_id, paper_key, source_type, source_id, claim_id, locator, quote, text)`：

- `source_type` 可为 `evidence` / `claim` / `attachment` / `wiki` / `specialist` / `word` / `zotero` / `external`；
- `EvidenceLedger.add` / `merge` / `ingest_external`（外部来源以 dict 接入）/ `dedupe`；
- `build_ledger(run, external_entries=None)` 汇总当前运行的 evidence 与 claim 条目，写 `ledger.json`（`count` + `entries`）；`load_ledger` / `ledger_stats` 读侧。

### 4.5 四态核验报告

`report.build_verification_report(run)` 读取 `claims.jsonl`，按 `_VERDICT_ORDER` 分组：

```
supported → flagged → unsupported → unclear → unresolved → unverified
```

报告以四态（`supported` / `flagged` / `unsupported` / `unclear`）为主，同时保留 `unresolved` / `unverified` 两个存在性状态，共 6 个分组；Markdown 渲染时只输出非空分组。报告结构包含 `generated_at`、`summary`（各状态计数）、`groups`（逐条 claim）、`metadata`（元数据核验原文）、`ledger`（`count` + `by_source`）。产物为 `export/verification_report.md` 与 `.json`，可直接作为 artifact 预览。

### 4.6 四维 Rubric

`rubric.review_run(run)` 完全确定性、只读运行目录，不调 LLM。四个维度各 0–5 分，总分 20：

| 维度 | 评分点 |
|---|---|
| 方法 | 检索次数（0 / 1–2 / ≥3 → 0 / 1 / 2）；被引文献证据覆盖率（<50% / ≥50% / ≥80% → 0 / 1 / 2）；外部元数据 `verified` 占比 ≥60% → +1 |
| 覆盖 | 文献量（<8 / ≥8 / ≥15 → 0 / 1 / 2）；被引比例（<50% / ≥50% / ≥80% → 0 / 1 / 2）；来源站点 ≥3 → +1 |
| 逻辑 | 存在大纲 +1；草稿包含所有大纲章节标题 +1；无 `unsupported` / `unresolved` claim +2；claims 非空 +1 |
| 写作 | 去空白正文字数（≥1200 / ≥3000 → 1 / 2）；引用 ≥3 条且密度 ≥4 条/千字 → 2，否则有引用且密度 ≥1.5 → 1；门禁通过 +1 |

`band`：≥16 优，≥12 良，≥8 及格，其余待改进。每维附带 `issues` 文案（含具体数值），指向可改进项。固定 `DISCLAIMER`：“本评审由确定性规则自动生成，是写作自检而非同行评审；分数只反映流程完整度，不评价学术价值。”

产物 `export/rubric_review.md`（总分表 + 每维问题清单）与 `.json`（`generated_at` / `total_score` / `max_score` / `band` / `disclaimer` / `dimensions[]`），并让 `run_status.has_rubric_review` 变为 `True`。

### 4.7 导出与论文写作交接

`export_run(run, style="gbt7714")`：先跑 `run_gates`，门禁失败抛 `ValueError`；通过后写：

- `export/final.md`：草稿正文 + `## 参考文献`（只列实际引用）；
- `export/references.json`：`{"style": ..., "entries": [{"key", "number", "paper"}]}`，`style` 记录实际样式；
- `export/papers.bib`：只包含实际引用文献的 BibTeX。

`build_handoff(run)` 返回 `{"references": [...], "draft_path": "<run_dir>/draft.md"}`，交给 `paper-writing` 的 `office_create` 生成 docx，再用 `office_lint_word` 自检；本子系统不重复实现 docx 排版。

### 4.8 命令行入口

`python -m backend.literature.cli` 是本地调试入口（生产中由 skill 的 `execute_code` 直接调函数）。子命令：`init` / `guidance` / `record-query` / `record-papers` / `record-evidence` / `save-outline` / `save-draft` / `gate` / `extract-claims` / `verify-claims` / `verify-metadata`（`--min-consensus`，默认 2）/ `apply-claim-support` / `build-ledger`（`--external`）/ `report` / `rubric` / `export`（`--style {gbt7714,ieee}`，默认 `gbt7714`）/ `status` / `validate-profile` / `draft-profile`。

输出为 JSON。以下情况返回退出码 1：门禁失败、`verify-claims` 存在 `unresolved` / `unsupported`、`verify-metadata` 存在 `unverified`、`apply-claim-support` 校验失败。`ValueError` / `OSError` 被 `main()` 捕获后输出 `{"ok": false, "error": ...}` 并返回 1；argparse 参数错误返回 2。

## 5. 数据存储与产物

### 5.1 运行目录契约

`<workspace>/.sage/literature_runs/<run_id>/`：

| 文件 | 写入方 | 内容 |
|---|---|---|
| `meta.json` | `create_run` | `run_id` / `topic` / `site_id` / `created_at` / `status` |
| `query_log.jsonl` | `record_query` | 每次检索：`query` / `site_id` / `result_count` / `note` / `at` |
| `papers.jsonl` | `record_papers` | `PaperRecord`，`paper_key` 唯一 |
| `evidence.jsonl` | `record_evidence` | `evidence_id` / `paper_key` / `kind` / `text` / `locator` / `quote` / `confidence` |
| `claims.jsonl` | `save_claims` | `claim_id` / `section` / `text` / `citation_keys` / `verdict` / `notes` / `metadata_schema_ok` |
| `outline.json` | `save_outline` | `title` / `sections[{id,title,summary,source_keys}]` |
| `draft.md` | `save_draft` | 正文，引用用 `[cite:KEY]` |
| `verification.json` | `run_gates` | 门禁 `ok` / `errors` / `warnings` / `citations` |
| `metadata_verification.json` | `verify_run_metadata` | 2-of-3 核验明细与计数 |
| `ledger.json` | `build_ledger` | `count` / `entries[]` |
| `export/final.md` | `export_run` | 正文 + 参考文献 |
| `export/references.json` | `export_run` | 样式与编号条目 |
| `export/papers.bib` | `export_run` | 仅被引文献的 BibTeX |
| `export/verification_report.{md,json}` | `build_verification_report` | 四态/六分组核验报告 |
| `export/rubric_review.{md,json}` | `review_run` | 四维 Rubric 与问题清单 |

`references/pipeline.md`（skill 参考文档）维护这些结构的字段级 schema 示例。

### 5.2 站点画像目录

见 §2.1。内置 profile 随包发布，用户/项目 profile 放对应目录；同 id 按层覆盖。

### 5.3 关键不变量

- `papers.jsonl` 中 `paper_key` 唯一，`record_papers` 负责去重；
- `evidence.jsonl` 的 `paper_key` 必须已存在于文献池；
- `outline.json` 的 `source_keys` 必须是文献池中的 key；
- 草稿中的 `[cite:KEY]` 必须是文献池中的 key，否则门禁失败；
- 导出前门禁 `errors` 必须为空；
- 所有产物可重复生成：核验、报告、Rubric、导出都只读既有产物，不修改上游数据。

## 6. 关键设计决策

1. **站点差异只在 YAML**：新增站点只需写 profile，不改 pipeline；失败时用 `validate-profile` / `draft-profile` 修配置而不是改代码。
2. **确定性 Python 守门，LLM 不写编号**：LLM 只写 `[cite:KEY]`，`[1] [2]…` 编号、参考文献行与 BibTeX 全部由 `build_references` 按首次引用顺序生成。
3. **不新增 chat 工具**：通过 shipped skill + `execute_code` 调用领域函数，避免每加一个能力就扩工具清单与能力门禁。
4. **运行目录即真相源**：每一步落盘、可暂停、可重跑、可审计；报告与 Rubric 只是派生视图。
5. **存在性问题优先于语义判断**：`unresolved`（引用不存在）与 `unsupported`（无引用）由确定性规则产生，语义 `apply_claim_support` 不能把它们改成 `supported`。
6. **快路径优先、失败回落**：`url` 模式的 `web_fetch` 比开浏览器快一个数量级；返回登录墙/空正文/异常时自动回落 `browser_navigate` + `browser_snapshot`；`interactive` 模式必须在真实页面输入，永不使用快路径。
7. **下载必须点 DOM 元素**：带签名参数（如 `&ddata=`）的下载链接不能靠快照 URL 直连，否则服务端拒绝。
8. **合规默认关闭**：第三方站点 `compliance.default_enabled: false`；不代填密码、不导出 cookie、不绕过付费墙，验证码/滑块交还用户。
9. **Rubric 是写作自检**：固定 `DISCLAIMER`，分数只反映流程完整度，不能当作投稿或同行评审依据。
10. **Py3.8 兼容**：使用 `typing.Optional/List/Dict/Tuple`，不用 PEP 604/585；`isinstance` 的 tuple 写法带 `# noqa: UP038`；时间戳用 `timezone.utc` 并带 `# noqa: UP017`。
11. **不做专用前端面板**：目前 `src/` 中没有文献研究的专属页面；报告与 Rubric 以 `export/` 下的 Markdown/JSON 产物呈现，走通用 artifact 预览。

## 7. 相关文件

| 路径 | 作用 |
|---|---|
| `backend/literature/models.py` | `SiteProfile` 等领域模型、`profile_from_dict` 校验、URL 渲染与登录态判断 |
| `backend/literature/profile_store.py` | 三层 profile 加载、单例、错误收集 |
| `backend/literature/guidance.py` | 生成检索指导文本 |
| `backend/literature/academic_adapter.py` | `ProfileBackedAdapter` |
| `backend/literature/recording.py` | 草稿 profile 录制 |
| `backend/skills/builtin/academic_adapters.py` | `get_site_adapter` 内置注册表与 profile 回退 |
| `backend/literature/search.py` | `BrowserDriver` 协议、`search_with_profile`、PDF 下载与校验 |
| `backend/literature/sage_driver.py` | `SageToolDriver` 工具映射 |
| `backend/literature/run_store.py` | 运行目录与原子写入 |
| `backend/literature/pipeline_models.py` | `EvidenceRecord` / `Outline` / `GateReport` / `Claim` 等 |
| `backend/literature/gates.py` | 引用提取、参考文献生成、门禁、claims 初判 |
| `backend/literature/verify.py` | 外部元数据 2-of-3、证据级支持 |
| `backend/literature/support.py` | 语义 claim support 合并 |
| `backend/literature/ledger.py` | EvidenceLedger |
| `backend/literature/report.py` | 四态核验报告 |
| `backend/literature/rubric.py` | 四维 Rubric |
| `backend/literature/export.py` | 导出与 paper-writing 交接 |
| `backend/literature/cli.py` | 命令行入口 |
| `docs/templates/literature-sites/xueshu789.yaml` | 示例站点 profile（不自动加载） |
| `backend/literature/README.md` | 模块说明与运行示例 |
| `backend/skills/skill_md/shipped/literature-research/SKILL.md` | 对 LLM 的工作流定义 |
| `backend/skills/skill_md/shipped/literature-research/references/pipeline.md` | 运行目录字段级 schema |
| `backend/tests/unit/test_literature_site_profiles.py` | 画像模型、存储、适配器、guidance 测试 |
| `backend/tests/unit/test_literature_pipeline.py` | 运行目录、检索、驱动、导出测试 |
| `backend/tests/unit/test_literature_claims.py` | claims、元数据核验、证据支持测试 |
| `backend/tests/unit/test_literature_review.py` | Rubric 与 IEEE 样式测试 |
| `docs/technical/159-controlled-browser-use.md` | 底层受控浏览器能力 |
| `docs/technical/53-academic-search-skill.md` | 旧 `academic-search` skill 与 adapter 注册表 |
