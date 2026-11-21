---
name: literature-research
description: 文献调研与综述最小闭环——选站点、检索、筛选、证据表、大纲、分节写作、引用门禁与导出，并交接给 paper-writing 生成 docx。当用户要做文献调研、写文献综述、literature review、或"找资料并整理成综述"时使用；单纯写论文正文请用 paper-writing。
license: Apache-2.0
compatibility: 需要 browser_* 工具、execute_code、write_file/read_file、office_parse_bibtex/office_create；站点 profile 见 backend/literature/sites 与 ~/.sage/literature_sites
when_to_use: 当用户要做文献调研、文献综述、literature review、systematic review，或说"找资料并整理成综述""帮我调研某主题的文献"时使用
allowed-tools: browser_launch browser_navigate browser_snapshot browser_interact browser_downloads browser_login ask_user_question execute_code bash write_file read_file office_parse_bibtex office_create office_lint_word
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
  outline.json       # title / sections[{id,title,summary,source_keys}]
  draft.md           # 正文，引用用 [cite:KEY] 或 [cite:KEY1, KEY2]
  verification.json  # 门禁报告
  export/            # final.md / references.json / papers.bib
```

## 工作流（按顺序，不要跳步）

### 0. 选择站点与确认合规

- 从 profile 注册表选择站点：`xueshu789`（学术资源站，`status: draft`）、
  `cnki`，或用户在 `~/.sage/literature_sites/` 自建的站点。
- xueshu789 实测：`/dbItem/3` 可用（重定向到知网代理检索页）；`/dbItem/1`
  代理报错、`/dbItem/2` 触发滑块验证；下载链路仍待验证。
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
run = create_run(Path("<workspace>/.sage/literature_runs"), "主题", "xueshu789")
print(run.run_dir)
```

### 3. 检索

1. 用 `execute_code` 取检索指导：

```python
from backend.literature.profile_store import get_default_store
from backend.literature.guidance import render_search_guidance
profile = get_default_store().get("xueshu789")
print(render_search_guidance(profile, "机器学习 综述", limit=20))
```

2. 按指导用 `browser_navigate`（带 `wait_for`）→ `browser_snapshot`。
   若 profile 是 `search.mode: interactive`，可直接在 `execute_code` 里用真实驱动：

```python
from backend.literature.profile_store import get_default_store
from backend.literature.search import search_with_profile
from backend.literature.sage_driver import SageToolDriver

profile = get_default_store().get("xueshu789")
obs = search_with_profile(profile, "机器学习 综述", SageToolDriver(sage.call), limit=20)
print(obs.guidance)
print(obs.snapshot[:3000])
```

驱动会自动：打开入口页 → 尝试 `search.input_selectors` → `press Enter` →
等待 `wait_after_s` → 抓取快照。下载仍需单独点击结果条目的「下载」并
`browser_downloads` 校验；xueshu789 的 `doDownload` 目前可能返回「参数错误」，
遇到时如实报告。
3. 从 snapshot 解析文献列表为 JSON；每条必须有 `paper_key`（DOI / arXiv ID /
   站点导出 ID / 规范化标题+作者+年份）与 `title`。
4. 用 `execute_code` 记录：

```python
from pathlib import Path
from backend.literature.run_store import load_run, record_papers, record_query
run = load_run(Path("<run_dir>"))
record_query(run, "机器学习 综述", "xueshu789", 20)
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

### 7. 门禁

用 `execute_code` 运行：

```python
from pathlib import Path
from backend.literature.gates import run_gates
from backend.literature.run_store import load_run
print(run_gates(load_run(Path("<run_dir>"))).to_dict())
```

- `errors` 必须清零：未知引用、缺失检索日志/大纲/草稿、证据指向未知文献。
- `warnings`（未被引用文献）可以保留，但要向用户说明。

### 8. 导出

```python
from pathlib import Path
from backend.literature.export import build_handoff, export_run
from backend.literature.run_store import load_run
run = load_run(Path("<run_dir>"))
print(export_run(run))
print(build_handoff(run))
```

产物：`export/final.md`、`export/references.json`、`export/papers.bib`。

### 9. 交接 paper-writing

把 `build_handoff` 的 `references` 与分章 Markdown 交给 `paper-writing`：
`office_create` 用 `references` + `paragraphs[].citations` 生成 GB/T 7714 引用的
docx；生成后跑 `office_lint_word` 自检。不要在本技能里重复实现 docx 排版。

## 边界

- 不编造引用；引用 key 不在文献池 → 停下来补文献或删句子。
- 不把全文塞进上下文；用证据表与 PaperDB 摘要。
- 不自动点击下载未知/危险文件；只点 profile 声明的 PDF 入口。
- xueshu789 的搜索 URL 模板与结果选择器仍是 `status: draft`；首次使用先用
  `draft-profile` 记录观测，或让用户确认选择器。
- 站点改版时用 `validate-profile` 与一次 dry-run 检索定位问题，不要改
  pipeline 代码。

## 快速命令（本地调试）

```bash
python -m backend.literature.cli init --root runs --topic 主题 --site xueshu789
python -m backend.literature.cli guidance --site xueshu789 --query 机器学习
python -m backend.literature.cli gate --run runs/<id>
python -m backend.literature.cli export --run runs/<id>
```
