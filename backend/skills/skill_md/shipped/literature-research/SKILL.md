---
name: literature-research
description: 文献调研与综述最小闭环——选站点、检索、筛选、证据表、大纲、分节写作、引用门禁与导出，并交接给 paper-writing 生成 docx。当用户要做文献调研、写文献综述、literature review、或"找资料并整理成综述"时使用；单纯写论文正文请用 paper-writing。
license: Apache-2.0
compatibility: 需要 browser_* 与 web_fetch 工具、execute_code、write_file/read_file、office_parse_bibtex/office_create；站点 profile 由用户在 ~/.sage/literature_sites 或 <项目>/.sage/literature_sites 配置，示例模板见 docs/templates/literature-sites
when_to_use: 当用户要做文献调研、文献综述、literature review、systematic review，或说"找资料并整理成综述""帮我调研某主题的文献"时使用
allowed-tools: browser_launch browser_navigate browser_snapshot browser_interact browser_downloads browser_login web_fetch ask_user_question execute_code bash write_file read_file office_parse_bibtex office_create office_lint_word
triggers: []
---

# 文献调研与综述

> 你是研究者的副驾驶，不是自动投稿机。引用只允许来自本次运行的文献池
> （`papers.jsonl`）；不要编造文献、作者、年份或 DOI。所有阶段产物落盘到
> 运行目录，用户可随时检查、暂停、重跑。

## 运行目录契约

```
<workspace>/.sage/literature_runs/<run_id>/
  meta.json          # run_id / topic / site_id / created_at / status
  query_log.jsonl    # 每次检索：query / site_id / result_count / note / at
  papers.jsonl       # PaperRecord（paper_key 唯一）
  evidence.jsonl     # evidence_id / paper_key / kind / text / locator / quote
  claims.jsonl       # claim_id / section / text / citation_keys / verdict / notes
  outline.json       # title / sections[{id,title,summary,source_keys}]
  draft.md           # 正文，引用用 [cite:KEY] 或 [cite:KEY1, KEY2]
  verification.json  # 门禁报告
  metadata_verification.json  # 外部元数据 2-of-3 核验
  ledger.json        # EvidenceLedger（evidence / claim / 外部引用）
  export/            # final.md / references.json / papers.bib
                     # verification_report.{md,json} / rubric_review.{md,json}
```

## 工作流（按顺序，不要跳步）

### 0. 选择站点与确认合规

- 先用 `get_default_store().list_ids()` 列出已配置站点，从中选一个 `status: ready`
  的 `<site_id>`；用户级站点放在 `~/.sage/literature_sites/`，项目级放
  `<项目>/.sage/literature_sites/`。没有合适站点时，引导用户从
  `docs/templates/literature-sites/` 复制示例并填写选择器。
- 选定后读取该 profile 的 `search`/`pdf`/`rate_limit`/`compliance` 配置驱动流程，
  **不要**把某个站点的主机名或选择器写死在工作流里。
- 需要登录时调用 `browser_login`，让用户在自己的可见窗口完成登录；
  **不要代填密码、不要导出 cookie、不要绕过付费墙**；验证码/滑块交还用户。
- 第三方站点默认禁用，用户显式同意后再使用。

### 1. 范围确认（必须问）

用 `ask_user_question` 确认：研究问题、时间/语言范围、纳入/排除标准、
目标篇幅、站点选择。把答案写入运行目录的后续产物（大纲/证据）中。

### 2. 初始化运行

用 `execute_code`：

```python
from pathlib import Path
from backend.literature.run_store import create_run
run = create_run(Path("<workspace>/.sage/literature_runs"), "主题", "<site_id>")
print(run.run_dir)
```

### 3. 检索

1. 用 `execute_code` 取检索指导：

```python
from backend.literature.profile_store import get_default_store
from backend.literature.guidance import render_search_guidance
profile = get_default_store().get("<site_id>")
print(render_search_guidance(profile, "机器学习 综述", limit=20))
```

2. 取页面内容——**优先快路径**：
   - profile 是 `search.mode: url`（有 `search.url_template`）→ 先用 `web_fetch`
     直接取该 URL 的正文（自动带该域登录态，比开浏览器快一个数量级）。
     返回登录墙 / 反爬 / 空正文 → 立刻升级到 `browser_navigate`（带 `wait_for`）
     → `browser_snapshot`，不要反复重试 `web_fetch`。
   - profile 是 `search.mode: interactive` → 必须走浏览器（要在真实页面里输入检索词）。
   - `web_fetch` 报 `login_wall` / `login_required` 时，先 `browser_login` 登录该域，
     登录态入库后 `web_fetch` 会自动带上，不要手动传 cookie。

   若 profile 是 `search.mode: interactive`，也可直接在 `execute_code` 里用真实驱动
   （`search_with_profile` 内部对 `url` 模式会先试 `web_fetch` 快路径，失败自动回落浏览器）：

```python
from backend.literature.profile_store import get_default_store
from backend.literature.search import search_with_profile
from backend.literature.sage_driver import SageToolDriver

profile = get_default_store().get("<site_id>")
obs = search_with_profile(profile, "机器学习 综述", SageToolDriver(sage.call), limit=20)
print(obs.guidance)
print(obs.snapshot[:3000])
```

驱动会自动：打开入口页 → 尝试 `search.input_selectors` → `press Enter` →
等待 `wait_after_s` → 抓取快照。下载时点击结果条目里 profile 声明的 PDF 入口
元素本身（selector 优先），**不要**用快照里可能截断的 URL 直连——部分站点的
真实链接还带额外参数（如 `&ddata=`），截断直连会报错；点击后
`browser_downloads` 等待并校验 `%PDF-` 与题名。部分站点下载完成后新标签
可能显示错误页，以浏览器下载目录为准。

**下载单篇（推荐用 helper，不要手点站点弹窗——`window.open` 弹窗对工具不可见）：**

```python
from pathlib import Path
from backend.literature.profile_store import get_default_store
from backend.literature.search import download_pdf
from backend.literature.sage_driver import SageToolDriver

profile = get_default_store().get("<site_id>")
res = download_pdf(
    profile, SageToolDriver(sage.call), expected_title="论文题名",
    dest_dir=Path("<run_dir>/pdf"),
    entry_selector="table.result-table-list tbody tr:nth-child(1) a.downloadlink",
)
print(res.ok, res.path, res.errors)
```

- profile 声明 `pdf.interstitial` 时，helper 会：读取该行元素完整 href（含
  `&ddata=`）→ 新标签打开下载入口 → 等中间页跳转 → 按 `host_fallbacks` 逐个
  重写主机（原域最后兜底）→ 等下载并校验 `%PDF-` 与题名；成功后关闭标签。
- 无 `interstitial` 配置的站点仍走原「点击入口」路径（`download_pdf` 自动选择）。
- 失败时把 `res.errors` 反馈给用户，不要反复重试。
3. 从 snapshot 解析文献列表为 JSON；每条必须有 `paper_key`（DOI / arXiv ID /
   站点导出 ID / 规范化标题+作者+年份）与 `title`。
4. 用 `execute_code` 记录：

```python
from pathlib import Path
from backend.literature.run_store import load_run, record_papers, record_query
run = load_run(Path("<run_dir>"))
record_query(run, "机器学习 综述", "<site_id>", 20)
print(record_papers(run, papers))  # papers 是上一步的 JSON 数组
```

### 4. 筛选与证据表

按纳入/排除标准筛选；对每篇入选文献抽取证据（任务/方法/数据/指标/发现/局限），
用 `execute_code` 写入 `record_evidence`。证据必须带 `paper_key`，可选 `locator`
（页码/段落/图号）与原文 `quote`。

### 5. 大纲

生成 `outline.json`，每个 section 有 `id/title/summary/source_keys`；
`source_keys` 只能引用文献池中的 key。用 `save_outline` 落盘。
用户确认大纲后再进入写作。

### 6. 分节写作

逐节用 `write_file` 落盘，再合并为 `draft.md`。正文引用只写
`[cite:KEY]` 或 `[cite:KEY1, KEY2]`；不要手写 `[1]` 编号。先综合、后比较，
不要逐篇复述。用 `save_draft` 保存。

### 7. 门禁与 claims 核验

用 `execute_code` 运行：

```python
from pathlib import Path
from backend.literature.gates import extract_claims, run_gates, verify_claims
from backend.literature.run_store import list_evidence, list_papers, load_run, read_draft, save_claims
from backend.literature.verify import apply_evidence_support, default_lookups, verify_run_metadata

run = load_run(Path("<run_dir>"))
print(run_gates(run).to_dict())
claims = verify_claims(
    extract_claims(read_draft(run)),
    {p.paper_key for p in list_papers(run)},
)
claims = apply_evidence_support(claims, list_evidence(run))
save_claims(run, claims)
print({"claims": len(claims), "verdicts": [c.verdict for c in claims]})
print(verify_run_metadata(run, default_lookups(), min_consensus=2))
```

- `errors` 必须清零：未知引用、缺失检索日志/大纲/草稿、证据指向未知文献。
- `claims` 的 `unresolved` / `unsupported` 必须清零；`flagged`（引用存在但没有 evidence 记录）要向用户说明并复核。
- `metadata_verification.json`：`verified` / `partial` / `unverified` / `skipped`；`unverified` 需要补元数据或向用户披露。
- 语义 claim support（Layer 3b）：逐条 claim 对照 evidence，生成 `claim_support.json`：

```json
[{"claim_id": "c0001", "support": "supported",
  "rationale": "证据 e1 的发现直接支持该句", "evidence_refs": ["e1"]}]
```

`support` 只能是 `supported` / `flagged` / `unsupported` / `unclear`；
`unresolved` / `unsupported` 的存在性问题优先，不要用语义判定掩盖。合并：

```python
from backend.literature.support import apply_claim_support
from backend.literature.run_store import load_claims, save_claims
save_claims(run, apply_claim_support(load_claims(run), judgments))
```

- 最后 `build-ledger` + `report` 生成 `ledger.json` 与
  `export/verification_report.{md,json}`（四态报告 artifact）。
- 生成四维 rubric 评审（方法/覆盖/逻辑/写作，确定性规则）：

```python
from backend.literature.rubric import review_run
review = review_run(run)  # 写 export/rubric_review.{md,json}
print({"total": review["total_score"], "band": review["band"]})
```

  把 `rubric_review.md` 的 issues 清单反馈给用户；评分为"模拟评审/写作自检"，
  不是同行评审，不能当作投稿依据。

### 8. 导出

```python
from pathlib import Path
from backend.literature.export import build_handoff, export_run
from backend.literature.run_store import load_run
run = load_run(Path("<run_dir>"))
print(export_run(run))                       # GB/T 7714（默认）
print(export_run(run, style="ieee"))         # 需要 IEEE 时
print(build_handoff(run))
```

产物：`export/final.md`、`export/references.json`、`export/papers.bib`；
`references.json.style` 记录实际引用样式（`gbt7714` / `ieee`）。

### 9. 交接 paper-writing

把 `build_handoff` 的 `references` 与分章 Markdown 交给 `paper-writing`：
`office_create` 用 `references` + `paragraphs[].citations` 生成 GB/T 7714 引用的
docx；生成后跑 `office_lint_word` 自检。不要在本技能里重复实现 docx 排版。

## 边界

- 不编造引用；引用 key 不在文献池 → 停下来补文献或删句子。
- 不把全文塞进上下文；用证据表与 PaperDB 摘要。
- 不自动点击下载未知/危险文件；只点 profile 声明的 PDF 入口。
- 新站点的搜索 URL 模板与结果选择器若未验证（`status: draft`），首次使用先用
  `draft-profile` 记录观测，或让用户确认选择器。
- 站点改版时用 `validate-profile` 与一次 dry-run 检索定位问题，不要改
  pipeline 代码。

## 快速命令（本地调试）

```bash
python -m backend.literature.cli init --root runs --topic 主题 --site <site_id>
python -m backend.literature.cli guidance --site <site_id> --query 机器学习
python -m backend.literature.cli gate --run runs/<id>
python -m backend.literature.cli report --run runs/<id>
python -m backend.literature.cli rubric --run runs/<id>
python -m backend.literature.cli export --run runs/<id> [--style ieee]
```

## 附录：站点 profile 示例

`docs/templates/literature-sites/` 提供可复制的示例 profile（如浏览器登录+检索+PDF
下载的 `xueshu789.yaml`）。这些模板**不参与运行时自动加载**，仅供理解 profile 字段
形态和快速创建新站点：

```bash
mkdir -p ~/.sage/literature_sites
cp docs/templates/literature-sites/xueshu789.yaml ~/.sage/literature_sites/
```

字段完整清单见 `backend/literature/README.md` 与 `backend/literature/models.py`。
