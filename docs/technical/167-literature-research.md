# 文献研究子系统

Sage 的文献研究能力由随包分发的 `literature-research` skill 驱动，实际逻辑集中在
`backend/literature/` 的纯 Python 领域层。它把「选站点 → 检索 → 建文献池 → 抽证据
→ 大纲 → 分节写作 → 引用门禁 → 核验 → 导出」串成一个可审计的运行目录：每个阶段
都落盘为 JSON/JSONL，用户和 LLM 都能中断、检查、重跑。

设计上有两条硬边界：

- **不新增 chat 工具**。浏览器动作继续走既有 `browser_*` 工具，由
  `SageToolDriver` 适配成 `BrowserDriver` 协议；文献层不 import 工具层，单测可用
  假驱动跑通。
- **站点差异只写在 YAML profile 里**。pipeline 不出现 `if site == ...`，新增站点
  不需要改代码。

## 1. 目录结构与运行目录

### 1.1 模块划分

| 文件 | 职责 |
|---|---|
| `backend/literature/models.py` | `SiteProfile` / `SearchSpec` / `PdfSpec` / `PaperRecord` 等领域模型；`profile_from_dict` 校验、`render_search_url`、`is_logged_in` |
| `backend/literature/profile_store.py` | 内置 / 用户 / 项目三级 profile 存储与缓存 |
| `backend/literature/academic_adapter.py` | `ProfileBackedAdapter`，把 profile 包装成 `academic_adapters` 要求的 duck-typed 适配器 |
| `backend/literature/guidance.py` | 把 profile 渲染成给 LLM 的检索指导文本，不执行浏览器 |
| `backend/literature/search.py` | `BrowserDriver` 协议、`search_with_profile`、`download_pdf`、`validate_pdf` |
| `backend/literature/sage_driver.py` | `SageToolDriver`，把驱动调用映射到 `sage.call("browser_*")` / `web_fetch` |
| `backend/literature/run_store.py` | 运行目录的创建、读取、原子写与状态摘要 |
| `backend/literature/gates.py` | 确定性门禁、引用抽取、参考文献生成（GB/T 7714 / IEEE）、claims Layer 1+2a |
| `backend/literature/export.py` | 通过门禁后的 Markdown / BibTeX / paper-writing 交接数据 |
| `backend/literature/pipeline_models.py` | `EvidenceRecord`、`Outline`、`GateReport`、`Claim`、`ClaimVerdict` |
| `backend/literature/verify.py` | 外部元数据 2-of-3 核验（Layer 2b）、证据级 flagged（Layer 3a） |
| `backend/literature/support.py` | 语义 claim support 的确定性校验与合并（Layer 3b） |
| `backend/literature/ledger.py` | `EvidenceLedger` 统一账本 |
| `backend/literature/report.py` | 核验报告 artifact |
| `backend/literature/rubric.py` | 四维确定性 rubric 评审 |
| `backend/literature/recording.py` | 从页面观测生成 profile 草稿 |
| `backend/literature/cli.py` | 本地调试 / skill 脚本调用的命令行入口 |
| `backend/literature/sites/xueshu789.yaml` | 随包站点 profile |
| `backend/skills/skill_md/shipped/literature-research/` | `SKILL.md` 与 `references/pipeline.md`（工作流与目录契约） |

### 1.2 运行目录

运行目录由调用方指定根目录，通常为 `<workspace>/.sage/literature_runs/<run_id>/`：

```
<run_id>/
  meta.json                  # run_id / topic / site_id / created_at / status
  query_log.jsonl            # query / site_id / result_count / note / at
  papers.jsonl               # PaperRecord，paper_key 唯一
  evidence.jsonl             # evidence_id / paper_key / kind / text / locator / quote / confidence
  claims.jsonl               # claim_id / section / text / citation_keys / verdict / notes / metadata_schema_ok
  outline.json               # title / sections[{id,title,summary,source_keys}]
  draft.md                   # 正文，引用写作 [cite:KEY] 或 [cite:KEY1, KEY2]
  verification.json          # 门禁报告
  metadata_verification.json # 外部元数据 2-of-3 核验
  ledger.json                # EvidenceLedger
  export/
    final.md
    references.json
    papers.bib
    verification_report.md
    verification_report.json
    rubric_review.md
    rubric_review.json
```

`create_run(root, topic, site_id, run_id=None)` 要求 `topic` / `site_id` 非空；
`run_id` 缺省为 UTC `YYYYMMDD-HHMMSS`，只允许字母、数字、`.`、`_`、`-`，且目录已存在
时直接报错。`meta.json` 的 `created_at` 使用带时区的 ISO 8601。

写入策略分两类：

- **JSON 产物**（meta / outline / verification / metadata_verification / ledger /
  report / rubric）走 `atomic_write_text`：先写同目录临时文件，再
  `Path(tmp).replace(path)`，避免半截文件。
- **JSONL 产物**（query_log / papers / evidence / claims）追加写；`papers` 按
  `paper_key` 去重，`evidence` 的 `paper_key` 必须已在文献池中。`claims.jsonl`
  是整账本重建：`save_claims` 先删除旧文件再整体写入。

`run_status` 返回各阶段计数与存在标记：`queries` / `papers` / `evidence` / `claims`，
以及 `has_outline` / `has_draft` / `has_verification` / `has_claims` /
`has_metadata_verification` / `has_ledger` / `has_verification_report` /
`has_rubric_review`。

## 2. 确定性门禁

`gates.run_gates(run)` 只读运行目录，不调 LLM，结果写入 `verification.json`。
出现以下任一情况记为 error：

- `query_log.jsonl` 为空；
- `papers.jsonl` 为空；
- evidence 的 `paper_key` 不在文献池；
- 缺少 `outline.json`，或大纲章节的 `source_keys` 指向未知文献；
- `draft.md` 为空；
- 草稿中的 `[cite:KEY]` 指向未知文献。

文献存在但未被正文引用只记为 warning。`ok = not errors` 才允许导出；
`export_run` 在门禁失败时抛 `ValueError`。

引用统一写作 `[cite:KEY]` 或 `[cite:KEY1, KEY2]`，不手写 `[1]` 编号。
`extract_citations` 按首次出现顺序去重；`build_references(draft, papers, style)`
按该顺序生成编号：

- `gbt7714`（默认）：`[1] 作者. 题名[J]. 刊名, 年.`，超过 3 位作者用「等」；
- `ieee`：`[1] A. Author, "Title," Venue, Year.`，英文名缩写首字母，超过 3 位
  作者用 `et al.`，中文名保持原样。

`SUPPORTED_REFERENCE_STYLES = ("gbt7714", "ieee")`，APA/CSL 未实现。

## 3. CLI 与执行入口

CLI 入口为 `python -m backend.literature.cli <command>`，stdout 输出单行 JSON。
主要子命令：

| 分类 | 子命令 |
|---|---|
| 运行维护 | `init`、`status` |
| profile | `guidance`、`validate-profile`、`draft-profile` |
| 记录产物 | `record-query`、`record-papers`、`record-evidence`、`save-outline`、`save-draft` |
| 门禁与 claims | `gate`、`extract-claims`、`verify-claims`、`apply-claim-support` |
| 核验与报告 | `verify-metadata`、`build-ledger`、`report`、`rubric` |
| 导出 | `export [--style gbt7714\|ieee]` |

退出码约定：`gate` 门禁失败返回 1；`verify-claims` 存在 `unresolved` 或
`unsupported` 返回 1；`verify-metadata` 存在 `unverified` 返回 1；
`apply-claim-support` 合并后仍有 `unsupported` / `unresolved` 返回 1；
`ValueError` / `OSError` 统一输出 `{"ok": false, "error": ...}` 并返回 1；
argparse 参数错误返回 2。

skill 侧不依赖 CLI 的字符串解析，而是在 `execute_code` 中直接调用同一批 Python
函数，因此 CLI 与 skill 共享完全一致的行为。

## 4. SiteProfile 与适配器回退

### 4.1 三级存储

| 层 | 目录 | 优先级 |
|---|---|---|
| 内置 | `backend/literature/sites/*.yaml` | 最低 |
| 用户 | `~/.sage/literature_sites/*.yaml`（可用 `SAGE_LITERATURE_SITES_DIR` 覆盖） | 中 |
| 项目 | `<cwd>/.sage/literature_sites/*.yaml` | 最高 |

同 `id` 的 profile 以后加载的层为准。`SiteProfileStore.discover()` 会跳过无效
YAML 并记录 warning，`get(site_id)` 命中无效 profile 时抛 `SiteProfileError`；
`get_default_store()` 提供进程级缓存，`reload()` / `reset_default_store()` 用于测试
或热更新。注意项目层以进程当前工作目录为基准，因此后端进程的 cwd 决定项目层位置。

### 4.2 模型与校验

`profile_from_dict` 的关键约束：

- `id` 只允许小写字母、数字、连字符，且以字母或数字开头；
- `home_url` 必须是 http(s)；`domains` 非空且只能写主机名（不带协议、路径、空格）；
- `access.mode` 只能是 `browser` / `rest` / `hybrid`；
- `search.mode` 只能是 `url` / `interactive`；
  - `url` 模式要求 `search.url_template` 含 `{query}`；
  - `interactive` 模式要求 `entry_url` 或 `url_template`，且 `input_selectors` 非空，
    `wait_after_s` 不能为负；
- `status` 只能是 `ready` / `draft`；`last_verified_at` 必须是 `YYYY-MM-DD`；
- PDF 入口既支持字符串（视作 selector），也支持 `{selector, text}` 对象。

`render_search_url` 渲染后会校验 scheme 与 hostname 必须落在 `domains` 内（含
子域名），防止 profile 把请求指向任意主机。`is_logged_in` 只在配置了
`url_contains` / `title_not_contains` 时返回布尔值，否则返回 `None`（登录态未知）；
它不做真实网络探测。

### 4.3 适配器回退

`backend/skills/builtin/academic_adapters.py` 的 `get_site_adapter(name)`：

1. 先查代码注册表 `_DEFAULT_ADAPTERS`（当前为 `cnki`）；
2. 未命中时延迟 import `backend.literature`，从 profile store 取同名 profile，
   包装成 `ProfileBackedAdapter`；
3. profile 不存在或无效时抛 `ValueError`。

`ProfileBackedAdapter` 只依赖 duck typing，提供 `name`、`profile`、
`build_search_url`、`render_guidance`，不 import skills 层，避免循环依赖。
新增纯 YAML 站点因此无需改动 `academic_adapters.py`。

`draft-profile` 从页面观测生成 profile 草稿，`recording.write_profile_draft` 会补
`status: draft`、`version`、`last_verified_at`、compliance 默认值，供人工复核后再
升级为 `ready`。

## 5. 检索执行器与工具驱动

### 5.1 BrowserDriver

`search.BrowserDriver` 是协议而非具体实现，方法包括：`navigate`、`snapshot`、
`click`、`click_text`、`type_text`、`press_key`、`sleep`、`current_url`、
`current_title`、`wait_download`。单测用假驱动即可覆盖完整检索流程。

### 5.2 url 模式

1. `render_search_url` 生成带 `{query}` 的检索 URL；
2. 若驱动提供 `fetch_text`，先走快路径（`web_fetch` 通道，自动带该域登录态），
   成功则直接返回正文；
3. 快路径抛异常、登录墙、反爬或空正文时，回落 `navigate` + `snapshot`。

快路径失败不会中断检索，只是退回浏览器通道。

### 5.3 interactive 模式

1. `navigate` 到 `entry_url`（或 `url_template`）；
2. 若配置 `entry_click`，`click_text` 后等待 1 秒；
3. 依次尝试 `input_selectors`，第一个 `type_text` 返回 `True` 的即命中；
4. `press_key(submit_key)`，按需 `sleep(wait_after_s)`；
5. `snapshot` 并生成 guidance。

所有输入框都失败时抛 `RuntimeError`，提示检查 `search.input_selectors`。

### 5.4 SageToolDriver

`SageToolDriver(call)` 的 `call` 形如 `sage.call(name, **kwargs)`，映射如下：

| 驱动方法 | 工具调用 |
|---|---|
| `navigate` | `browser_navigate` |
| `snapshot` | `browser_snapshot(mode="full", max_nodes=250)` |
| `click` / `click_text` | `browser_interact(action="click", selector=... / text=...)` |
| `type_text` | `browser_interact(action="type", selector=..., value=..., clear=...)` |
| `press_key` | `browser_interact(action="press", key=...)` |
| `wait_download` | `browser_downloads(wait_for_complete=True, timeout=...)` |
| `fetch_text` | `web_fetch(url=..., mode="text")` |
| `sleep` | `time.sleep`，上限 30 秒 |

细节：`type_text` 捕获 `RuntimeError` 并返回 `False`，供多 selector 回退，其余方法
向上抛；`fetch_text` 只走 HTTP，不打开浏览器，因此后续若要点 DOM（如下载入口），
`_ensure_browser` 会用最近 URL 补一次导航；`wait_download` 取最近修改的已完成
下载项。

### 5.5 PDF 下载与校验

`download_pdf` 要求 profile 配置 `pdf` 且至少有一个入口：

- 有 `entry_selector` 时 `driver.click(selector)`，否则 `driver.click_text(entry_text)`；
- 可配置 `post_click_wait_s`，点击后等待新标签/下载触发；
- `wait_download` 超时返回失败；
- `validate_pdf` 校验文件头 magic（默认 `%PDF-`）与文件名是否包含题名；
- `forbid`（默认 `CAJ`）命中后缀时记错误。

xueshu789 的下载链接真实 href 还带 `&ddata=文件名|库|题名|库|hash`，必须点击 DOM
元素本身，不能用快照里截断的 URL 直连，否则服务端报「参数错误」。

合规边界固定在 skill 与 profile 中：仅使用本人账号或机构授权；不代填密码、不导出
cookie、不绕过付费墙；验证码/滑块交还用户在可见窗口完成；第三方站点默认禁用，
需用户显式同意。

## 6. Claims 账本与分层核验

### 6.1 claims.jsonl

`extract_claims(draft)` 按空行分段，只保留含 `[cite:KEY]` 的段落，每段一条 claim，
`claim_id` 形如 `c0001`，`section` 统一为 `body`，正文截断到 2000 字符。
`ClaimVerdict` 可取 `unverified` / `supported` / `flagged` / `unsupported` /
`unresolved` / `unclear`，默认 `unverified`。

### 6.2 分层核验

| 层 | 实现 | 判据与结果 |
|---|---|---|
| Layer 1 | `gates.verify_claims` | 引用 key 不在文献池 → `unresolved`；claim 无引用 → `unsupported` |
| Layer 2a | `gates.verify_claims` | 引用 key 都在文献池 → `supported`，并置 `metadata_schema_ok=True` |
| Layer 3a | `verify.apply_evidence_support` | 引用论文没有任何 evidence 记录 → `flagged`，备注提示语义支持待核验 |
| Layer 2b | `verify.verify_paper_metadata` | 外部元数据 2-of-3 共识 |
| Layer 3b | `support.apply_claim_support` | LLM 判定语义支持，本模块只做确定性校验与合并 |

Layer 2a 目前是粗粒度实现：只要引用 key 存在就置 `metadata_schema_ok=True`，并未
逐项校验 DOI / 标题 / 作者 / 年份字段是否齐全；需要更严格的字段级校验时应扩展此处。

`apply_evidence_support` 不改变 `unresolved` / `unsupported`，存在性问题优先。

### 6.3 外部元数据 2-of-3（Layer 2b）

`verify-metadata` 对每篇文献查询 Crossref / OpenAlex / Semantic Scholar：

- 有 DOI（含 `paper_key` 前缀 `doi:` 或 `paper.doi`）或 arXiv ID（`arxiv:` 前缀或
  arXiv URL）才发起查询，否则该篇 `skipped`；
- `metadata_matches` 要求标题归一化后完全相等，年份（双方都有时）一致，且作者集合
  有交集（任一方作者为空时跳过作者检查）；
- 命中数 ≥ `min_consensus`（默认 2）→ `verified`；1 家 → `partial`；0 家 →
  `unverified`；
- 结果写入 `metadata_verification.json`，含 `min_consensus`、逐篇 `checks` 与四个
  状态计数。

网络超时 8 秒，单家失败记为 `no_data` 并继续，不影响其他来源。

### 6.4 语义 claim support（Layer 3b）

LLM 阅读 `claims.jsonl` 与 `evidence.jsonl` 后输出 judgments：

```json
[
  {
    "claim_id": "c0001",
    "support": "supported",
    "rationale": "证据 e1 的发现直接支持该句",
    "evidence_refs": ["e1"]
  }
]
```

`support` 只能是 `supported` / `flagged` / `unsupported` / `unclear`。
`apply_claim_support` 的确定性校验：

- judgment 必须是对象，`claim_id` 必填且不能重复；
- `claim_id` 必须存在于当前账本，否则报错；
- 非法 `support` 报错；
- `unresolved` / `unsupported` 的 claim 保持原状，其余 claim 用 judgment 覆盖
  verdict，并把 `rationale` 与证据引用追加到 `notes`。

语义判断本身由 LLM 完成，本模块不调用模型，保证合并在单测中可完全复现。

## 7. EvidenceLedger、核验报告、Rubric 与导出

### 7.1 EvidenceLedger

`build_ledger(run, external_entries=None)` 把运行目录收敛为 `ledger.json`：

- evidence 记录 → `source_type="evidence"`；
- claim 的每个引用 key → `source_type="claim"`，带 `claim_id`；
- 只保留引用存在于文献池的记录；
- `--external` 可接入附件 / Wiki / 专家知识 / Word / Zotero 等来源，统一字段为
  `paper_key`、`source_type`、`source_id`、`claim_id`、`locator`、`quote`、`text`；
- 去重键为 `(paper_key, source_type, source_id, claim_id, locator)`。

`ledger_stats` 按 `source_type` 计数，供报告使用。

### 7.2 核验报告

`report.build_verification_report(run)` 读取 claims、metadata 与 ledger，写出
`export/verification_report.md` / `.json`。文档习惯称「四态报告」，但实现按
`_VERDICT_ORDER` 输出 **6 个分组**：`supported` / `flagged` / `unsupported` /
`unclear` / `unresolved` / `unverified`。报告含：

- `summary`：各 verdict 计数；
- `groups`：逐条 claim 明细（含 notes）；
- `metadata`：元数据核验摘要；
- `ledger`：条目总数与按来源统计。

Markdown 与 JSON 同时生成，可直接作为 artifact 预览。

### 7.3 Rubric 评审

`rubric.review_run(run)` 完全确定性，只读现有产物，输出
`export/rubric_review.md` / `.json`。四维各 0–5 分，总分 20：

| 维度 | 评分要点 |
|---|---|
| 方法 | 检索次数（0 / 1–2 / ≥3）；被引文献证据覆盖率（<50% / ≥50% / ≥80%）；元数据核验通过率（≥60%） |
| 覆盖 | 文献量（<8 / ≥8 / ≥15）；被引比例（<50% / ≥50% / ≥80%）；来源站点数（≥3） |
| 逻辑 | 大纲存在；草稿包含全部大纲章节；无 `unsupported` / `unresolved` claim；claims 非空 |
| 写作 | 去空白正文体量（≥1200 / ≥3000 字）；引用密度（每千字 ≥1.5 / ≥4 条且至少 3 条）；门禁通过 |

`band`：≥16 优 / ≥12 良 / ≥8 及格 / 否则待改进。`DISCLAIMER` 固定声明「模拟评审，
非同行评审，分数只反映流程完整度」，不能作为投稿依据。每个维度附带可读的
`issues` 清单，阈值集中在 `rubric.py` 便于按评测集调整。

### 7.4 导出与交接

`export_run(run, style="gbt7714")` 先重跑门禁，失败即抛错；通过后写出：

- `export/final.md`：正文 + `## 参考文献`，只列实际引用；
- `export/references.json`：`{"style": ..., "entries": [{"key","number","paper"}]}`；
- `export/papers.bib`：只含实际引用的 BibTeX 条目（`@article`）。

`build_handoff(run)` 返回 `references`（key / ref_type / title / authors / year /
source / doi）与 `draft_path`，交给 `paper-writing` 的 `office_create` 生成
GB/T 7714 引用的 docx，再用 `office_lint_word` 自检；文献子系统不重复实现 docx 排版。

## 8. 测试与已知限制

### 8.1 测试覆盖

| 测试文件 | 覆盖重点 |
|---|---|
| `backend/tests/unit/test_literature_site_profiles.py` | profile 解析与校验、三级存储覆盖、guidance、URL 域名约束 |
| `backend/tests/unit/test_literature_pipeline.py` | run store、门禁、检索/下载假驱动、`SageToolDriver`、CLI 主流程 |
| `backend/tests/unit/test_literature_claims.py` | claims 抽取 / 核验 / 合并、元数据 2-of-3、证据级 flagged、CLI |
| `backend/tests/unit/test_literature_m2c.py` | 语义 claim support 合并、ledger、核验报告、M2c CLI |
| `backend/tests/unit/test_literature_review.py` | rubric 评分、IEEE 格式、`export --style` |

`backend/tests/unit/test_literature_aggregator.py` 测的是 `backend.wiki.literature_aggregator`，
属于 Wiki 子系统，不在本模块范围内。测试全部可离线运行：外部元数据查询在单测中注入
假 lookup，浏览器交互使用假驱动。

### 8.2 已知限制

- **Layer 2a 粒度粗**：`supported` 只代表引用 key 存在，`metadata_schema_ok` 未做
  逐字段校验。
- **Layer 3b 依赖 LLM**：语义支持由 skill 中的 LLM 判定，代码只保证合并规则确定；
  `flagged` 仍可能需要在真机上人工复核。
- **报告分组命名**：实现输出 6 个 verdict 分组，与「四态报告」的历史叫法不完全一致。
- **引用样式**：仅 GB/T 7714 与 IEEE；APA/CSL 未实现，中文作者在 IEEE 下保持原样。
- **站点可用性**：xueshu789 仅 `/dbItem/3` 实测可用；`/dbItem/1` 代理报「出错啦」，
  `/dbItem/2` 会触发知网滑块验证，需要用户在可见窗口人工完成。下载完成后新标签
  可能显示「页面不存在」，但 PDF 已落盘，应以浏览器下载目录为准。
- **登录态**：`is_logged_in` 只按配置的 URL/标题规则判断，未配置时返回 `None`；
  登录本身必须由用户通过 `browser_login` 完成。
- **项目层 profile 位置**：以进程 cwd 为基准；后端 cwd 不是工作区时，项目层
  `.sage/literature_sites` 可能取不到。
- **未落地的 M2c 收尾项**：跨子系统引用自动适配器与专用核验报告前端面板不在当前
  实现范围；外部来源目前通过 `build-ledger --external` 手动接入。
- **skill 参考文档存在历史描述**：`references/pipeline.md` 与 `SKILL.md` 仍保留
  「Layer 3b 尚未实现」「xueshu789 status: draft」等旧表述，与当前代码不符；以代码
  与本技术文档为准。
