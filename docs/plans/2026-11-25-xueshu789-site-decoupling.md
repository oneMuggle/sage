# xueshu789 站点配置解耦 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把验证用站点 xueshu789 从"产品内置配置"降级为"用户可复制的示例模板"，使 `backend/literature/` 引擎层与 shipped skill 对具体站点保持中立。

**Architecture:** 引擎层 `backend/literature/` 已经是通用参数化的（SiteProfile 三级加载：builtin < 用户级 `~/.sage/literature_sites/` < 项目级 `.sage/literature_sites/`）。本计划**不改引擎逻辑**，只做"减耦合"：把 `sites/xueshu789.yaml` 迁到 `docs/templates/literature-sites/`（不参与运行时自动加载），把 shipped `literature-research/SKILL.md` 参数化为 `<site_id>` 占位 + 末尾示例附录，并把散落在 README/pipeline.md/cli docstring 的 xueshu789 实测笔记收敛到模板注释与记忆。

**Tech Stack:** Python 3.10（`sage-backend` conda 环境）/ pytest / ruff；YAML site profile；Markdown shipped skill。

**Spec:** 无独立 spec，本计划直接落地用户 2026-11-25 的口头约束（xueshu789 仅为跑通流程，不得耦合进代码；用 skill/记忆做可配置模板）。决策已通过 AskUserQuestion 确认：① yaml 放 `docs/templates` 示例 + 用户级启用；② SKILL.md 参数化 + 示例附录；③ 先出方案再动手。

## Global Constraints

- **不改引擎逻辑**：`backend/literature/` 下除 docstring/README 外无代码改动；搜索、下载、门禁、ledger 等行为不变。
- **builtin 不再携带 xueshu789**：迁移后 `backend/literature/sites/` 不含任何具体站点 yaml，只留说明文件。
- **运行时中立**：`docs/templates/literature-sites/` 不在 `SiteProfileStore.default()` 的三个加载根内，复制到用户级目录才生效。
- **实测事实不丢**：xueshu789 的 `ddata`/`/dbItem/3`/下载后新标签页等坑以 yaml 注释 + 模板 README + 记忆承载，不留在产品 skill 正文。
- **Python 环境**：所有 pytest/ruff 用 `/home/fz/anaconda3/envs/sage-backend/bin/python -m ...`。

---

## File Structure

**新建：**
- `docs/templates/literature-sites/xueshu789.yaml` — 可复制启用的完整 profile（含关键坑注释）
- `docs/templates/literature-sites/README.md` — 如何启用 + 实测事实摘要
- `backend/literature/sites/README.md` — 说明此目录放内建 profile，当前为空，示例见 docs/templates

**迁移/删除：**
- `backend/literature/sites/xueshu789.yaml` — 删除（内容搬到 docs/templates）

**修改：**
- `backend/skills/skill_md/shipped/literature-research/SKILL.md` — 参数化正文 + 示例附录
- `backend/skills/skill_md/shipped/literature-research/references/pipeline.md` — 通用化示例 + 删 xueshu789 专段
- `backend/literature/README.md` — xueshu789 专段收敛为指向 docs/templates
- `backend/literature/cli.py` — docstring 示例 `--site xueshu789` → `--site <site_id>`
- `backend/literature/search.py` — docstring `xueshu789 等站点` → `部分站点`
- `backend/tests/unit/test_literature_site_profiles.py` — `TestShippedXueshu789Profile` → `TestTemplateXueshu789Profile`（从 docs/templates 加载）

---

### Task 1: 迁移站点配置到示例模板

**Files:**
- Create: `docs/templates/literature-sites/xueshu789.yaml`
- Create: `docs/templates/literature-sites/README.md`
- Create: `backend/literature/sites/README.md`
- Delete: `backend/literature/sites/xueshu789.yaml`

**Interfaces:**
- Consumes: 现有 `backend/literature/sites/xueshu789.yaml`（version 0.3.0 / status ready）
- Produces: `docs/templates/literature-sites/xueshu789.yaml`（同一 profile，供 `SiteProfileStore([ProfileRoot(..., "template")])` 加载验证）

- [ ] **Step 1: 复制 yaml 到模板目录并补充坑注释**

`docs/templates/literature-sites/xueshu789.yaml` 内容（在现有 yaml 基础上，把实测坑写成注释）：

```yaml
# xueshu789 站点 profile —— 示例模板，不随产品自动加载。
# 启用方式（任选其一）：
#   cp docs/templates/literature-sites/xueshu789.yaml ~/.sage/literature_sites/
#   或复制到 <项目>/.sage/literature_sites/
# 加载顺序：builtin < ~/.sage/literature_sites < .sage/literature_sites
#
# 实测要点（2026-11-22，仅作启用参考，实际以真机为准）：
#   - 卡号+密码登录，成功后 URL 进 /dbList/，标题不含「登录」
#   - /dbItem/3 可用（重定向知网代理检索页）；/dbItem/1 代理报错；/dbItem/2 触发滑块验证
#   - 下载：必须点击 a.downloadlink 元素本身，完整 href 含 &ddata=文件名|库|题名|库|hash
#     不要用快照里截断的 doDownload?url=... 直连（缺 ddata 报「参数错误」）
#   - 下载完成后新标签可能显示 CNKI「页面不存在」，以浏览器下载目录为准
id: xueshu789
display_name: 学术资源站
home_url: https://www.xueshu789.cc/
domains:
  - xueshu789.cc
  - 82.157.23.222
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
  mode: interactive
  url_template: "https://www.xueshu789.cc/dbItem/3"
  entry_url: "https://www.xueshu789.cc/dbItem/3"
  input_selectors:
    - "input[placeholder*='检索词']"
    - "textarea[placeholder*='检索词']"
  submit_key: Enter
  wait_after_s: 5
  result_hint: 每条结果含题名/作者/来源链接（均指向 doDownload）+ 下载/原版阅读/CNKI AI阅读；结果总数在页面上方
  wait_for: []
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
    selector: "a.downloadlink"
    text: 下载
  post_click_wait_s: 8
  note: "必须点击 a.downloadlink 元素（完整 href 含 &ddata=文件名|库|题名|库|hash）；不要用快照中截断的 URL 直连，否则 doDownload 报参数错误"
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
version: "0.3.0"
status: ready
last_verified_at: "2026-11-22"
```

- [ ] **Step 2: 写模板启用说明**

`docs/templates/literature-sites/README.md` 内容：

```markdown
# 文献站点 profile 示例模板

此目录存放**示例**站点 profile，**不参与运行时自动加载**。要启用某个站点：

```bash
mkdir -p ~/.sage/literature_sites
cp docs/templates/literature-sites/xueshu789.yaml ~/.sage/literature_sites/
```

或复制到 `<项目>/.sage/literature_sites/`（仅该项目生效）。

加载优先级：`backend/literature/sites/`(builtin) < `~/.sage/literature_sites/`(用户) < `<项目>/.sage/literature_sites/`(项目)，后者覆盖前者。

验证：`python -m backend.literature.cli validate-profile --path ~/.sage/literature_sites/xueshu789.yaml`；
列出已加载站点：`python -c "from backend.literature.profile_store import get_default_store as g; print(g().list_ids())"`。

## xueshu789 实测要点（2026-11-22）

- 卡号+密码登录，成功后 URL 进 `/dbList/`，标题不含「登录」。
- `/dbItem/3` 可用（重定向 `http://82.157.23.222:5888/kns8s/defaultresult/index`）；`/dbItem/1` 代理报错；`/dbItem/2` 触发知网滑块验证。
- 搜索框 placeholder 含「检索词」，Enter 提交，约 5 秒出结果。
- 结果条目链接指向 `doDownload?url=...`，操作列「下载 / 原版阅读 / CNKI AI阅读」。
- 下载：`a.downloadlink` 真实 href 还带 `&ddata=<文件名>|<库>|<题名>|<库>|<hash>`；点击该元素经 `oversea.cnki.net/docdown/fulltext/download` 落盘 PDF（实测 787KB/26 页）。**不要**用快照里截断的 `doDownload?url=...` 直连（缺 `ddata` 报「参数错误」）。
- 下载完成后新标签可能显示 CNKI「页面不存在」，PDF 已落盘，以浏览器下载目录为准。
- 合规：仅本人账号/机构授权；不绕过付费墙；验证码/滑块交还用户。
```

- [ ] **Step 3: builtin sites 目录留说明文件**

`backend/literature/sites/README.md` 内容：

```markdown
# 内建站点 profile

此目录存放**随产品分发**的文献站点 profile（YAML）。当前为空——不内置任何具体第三方站点，以保证产品中立。

- 需要某站点时，把 `docs/templates/literature-sites/` 下的示例复制到 `~/.sage/literature_sites/`（用户级）或 `<项目>/.sage/literature_sites/`（项目级）启用。
- profile 字段规范见 `backend/literature/README.md` 与 `backend/literature/models.py`。
- 加载优先级：builtin(本目录) < 用户级 < 项目级。
```

- [ ] **Step 4: 删除 builtin 上的 xueshu789.yaml**

```bash
git rm backend/literature/sites/xueshu789.yaml
```

- [ ] **Step 5: 验证模板可加载、builtin 已无站点**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -c "
from pathlib import Path
from backend.literature.profile_store import ProfileRoot, SiteProfileStore
store = SiteProfileStore([ProfileRoot(Path('docs/templates/literature-sites'), 'template')])
p = store.get('xueshu789')
print('template ok:', p.display_name, p.search.entry_url, p.status)
builtin = SiteProfileStore([ProfileRoot(Path('backend/literature/sites'), 'builtin')])
print('builtin ids:', builtin.list_ids())
"
```
Expected: 打印 `template ok: 学术资源站 https://www.xueshu789.cc/dbItem/3 ready`，且 `builtin ids: []`。

- [ ] **Step 6: Commit**

```bash
git add docs/templates/literature-sites/ backend/literature/sites/
git commit -m "refactor(literature): 迁移 xueshu789 配置到 docs/templates 示例，builtin 站点目录保持中立"
```

---

### Task 2: 调整 profile 测试从模板加载

**Files:**
- Modify: `backend/tests/unit/test_literature_site_profiles.py:291-312`

**Interfaces:**
- Consumes: `docs/templates/literature-sites/xueshu789.yaml`（Task 1 产出）
- Produces: 测试不再断言 builtin 携带 xueshu789

- [ ] **Step 1: 先跑旧测试确认迁移后失败**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_site_profiles.py::TestShippedXueshu789Profile -v
```
Expected: FAIL（`SiteProfileError: 未找到站点 profile: 'xueshu789'`，因为 builtin 已删）。

- [ ] **Step 2: 改测试类为从模板目录加载**

把 `backend/tests/unit/test_literature_site_profiles.py` 的 `TestShippedXueshu789Profile` 整段替换为：

```python
class TestTemplateXueshu789Profile:
    """xueshu789 是示例模板（docs/templates），不是 builtin 产品配置。"""

    def test_template_profile_loads_and_matches_observed_facts(self):
        from backend.literature.profile_store import ProfileRoot, SiteProfileStore

        template_dir = (
            Path(__file__).resolve().parents[3]
            / "docs"
            / "templates"
            / "literature-sites"
        )
        store = SiteProfileStore([ProfileRoot(template_dir, "template")])
        profile = store.get("xueshu789")
        assert profile.display_name == "学术资源站"
        assert "xueshu789.cc" in profile.domains
        assert "82.157.23.222" in profile.domains
        assert profile.access.login.method == "form"
        assert profile.access.login.url_contains == "/dbList/"
        assert profile.search.mode == "interactive"
        assert profile.search.entry_url == "https://www.xueshu789.cc/dbItem/3"
        assert "input[placeholder*='检索词']" in profile.search.input_selectors
        assert profile.pdf is not None
        assert profile.pdf.entry_selector == "a.downloadlink"
        assert profile.pdf.entry_text == "下载"
        assert profile.pdf.post_click_wait_s == 8.0
        assert profile.status == "ready"
        assert profile.last_verified_at == "2026-11-22"
        assert profile.compliance.default_enabled is False
        assert profile.source_layer == "template"

    def test_builtin_sites_dir_ships_no_concrete_sites(self):
        from backend.literature.profile_store import ProfileRoot, SiteProfileStore

        builtin = Path(__file__).resolve().parents[2] / "literature" / "sites"
        store = SiteProfileStore([ProfileRoot(builtin, "builtin")])
        assert store.list_ids() == []
```

- [ ] **Step 3: 跑测试确认通过**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_site_profiles.py -v
```
Expected: PASS（含新的 `TestTemplateXueshu789Profile` 2 例）。

- [ ] **Step 4: Commit**

```bash
git add backend/tests/unit/test_literature_site_profiles.py
git commit -m "test(literature): xueshu789 断言改为从 docs/templates 示例加载，并校验 builtin 无具体站点"
```

---

### Task 3: 参数化 literature-research SKILL.md

**Files:**
- Modify: `backend/skills/skill_md/shipped/literature-research/SKILL.md`

**Interfaces:**
- Consumes: 无（纯文档）
- Produces: 正文对任意 `<site_id>` 中立 + 末尾示例附录指向 docs/templates

- [ ] **Step 1: 改 compatibility 行（line 5）**

把：
```
compatibility: 需要 browser_* 与 web_fetch 工具、execute_code、write_file/read_file、office_parse_bibtex/office_create；站点 profile 见 backend/literature/sites 与 ~/.sage/literature_sites
```
改为：
```
compatibility: 需要 browser_* 与 web_fetch 工具、execute_code、write_file/read_file、office_parse_bibtex/office_create；站点 profile 由用户在 ~/.sage/literature_sites 或 <项目>/.sage/literature_sites 配置，示例模板见 docs/templates/literature-sites
```

- [ ] **Step 2: 替换第 0 步站点选择（line 39-46）**

把 line 39-46 整段：
```
- 从 profile 注册表选择站点：`xueshu789`（学术资源站，`status: draft`）、
  `cnki`，或用户在 `~/.sage/literature_sites/` 自建的站点。
- xueshu789 实测：`/dbItem/3` 可用（重定向到知网代理检索页）；`/dbItem/1`
  代理报错、`/dbItem/2` 触发滑块验证；下载已实测通过（点击 `a.downloadlink`，
  完整 href 含 `&ddata=`）。
- 需要登录时调用 `browser_login`，让用户在自己的可见窗口完成登录；
  **不要代填密码、不要导出 cookie、不要绕过付费墙**；验证码/滑块交还用户。
- 第三方站点默认禁用，用户显式同意后再使用。
```
改为：
```
- 先用 `get_default_store().list_ids()` 列出已配置站点，从中选一个 `status: ready`
  的 `<site_id>`；用户级站点放在 `~/.sage/literature_sites/`，项目级放
  `<项目>/.sage/literature_sites/`。没有合适站点时，引导用户从
  `docs/templates/literature-sites/` 复制示例并填写选择器。
- 选定后读取该 profile 的 `search`/`pdf`/`rate_limit`/`compliance` 配置驱动流程，
  **不要**把某个站点的主机名或选择器写死在工作流里。
- 需要登录时调用 `browser_login`，让用户在自己的可见窗口完成登录；
  **不要代填密码、不要导出 cookie、不要绕过付费墙**；验证码/滑块交还用户。
- 第三方站点默认禁用，用户显式同意后再使用。
```

- [ ] **Step 3: 代码示例里的站点 id 改占位符**

把这三处字符串实参改为占位符（保留示例 query 不变）：

- line 60：`create_run(Path("<workspace>/.sage/literature_runs"), "主题", "xueshu789")` → `create_run(Path("<workspace>/.sage/literature_runs"), "主题", "<site_id>")`
- line 71：`profile = get_default_store().get("xueshu789")` → `profile = get_default_store().get("<site_id>")`
- line 92：`profile = get_default_store().get("xueshu789")` → `profile = get_default_store().get("<site_id>")`
- line 112：`record_query(run, "机器学习 综述", "xueshu789", 20)` → `record_query(run, "机器学习 综述", "<site_id>", 20)`

- [ ] **Step 4: 通用化下载说明（line 98-103）**

把：
```
驱动会自动：打开入口页 → 尝试 `search.input_selectors` → `press Enter` →
等待 `wait_after_s` → 抓取快照。下载时点击结果条目里的 `a.downloadlink`
（真实 href 含 `&ddata=文件名|库|题名|库|hash`），**不要**用快照里截断的
`doDownload?url=...` 直连（缺少 `ddata` 会报「参数错误」）；点击后
`browser_downloads` 等待并校验 `%PDF-` 与题名。xueshu789 下载完成后新标签
可能显示「页面不存在」，以浏览器下载目录为准。
```
改为：
```
驱动会自动：打开入口页 → 尝试 `search.input_selectors` → `press Enter` →
等待 `wait_after_s` → 抓取快照。下载时点击结果条目里 profile 声明的 PDF 入口
元素本身（selector 优先），**不要**用快照里可能截断的 URL 直连——部分站点的
真实链接还带额外参数（如 `&ddata=`），截断直连会报错；点击后
`browser_downloads` 等待并校验 `%PDF-` 与题名。部分站点下载完成后新标签
可能显示错误页，以浏览器下载目录为准。
```

- [ ] **Step 5: 通用化边界说明（line 214-215）**

把：
```
- xueshu789 的搜索 URL 模板与结果选择器仍是 `status: draft`；首次使用先用
  `draft-profile` 记录观测，或让用户确认选择器。
```
改为：
```
- 新站点的搜索 URL 模板与结果选择器若未验证（`status: draft`），首次使用先用
  `draft-profile` 记录观测，或让用户确认选择器。
```

- [ ] **Step 6: 快速命令改占位符（line 222-223）**

- `... init --root runs --topic 主题 --site xueshu789` → `--site <site_id>`
- `... guidance --site xueshu789 --query 机器学习` → `--site <site_id> --query 机器学习`

- [ ] **Step 7: 末尾追加示例附录**

在「快速命令」代码块之后追加：

```markdown

## 附录：站点 profile 示例

`docs/templates/literature-sites/` 提供可复制的示例 profile（如浏览器登录+检索+PDF
下载的 `xueshu789.yaml`）。这些模板**不参与运行时自动加载**，仅供理解 profile 字段
形态和快速创建新站点：

```bash
mkdir -p ~/.sage/literature_sites
cp docs/templates/literature-sites/xueshu789.yaml ~/.sage/literature_sites/
```

字段完整清单见 `backend/literature/README.md` 与 `backend/literature/models.py`。
```

- [ ] **Step 8: 验证 SKILL.md 不再含站点硬编码**

Run:
```bash
grep -n "xueshu789\|dbItem\|ddata" backend/skills/skill_md/shipped/literature-research/SKILL.md
```
Expected: 仅可能命中 Step 7 附录中的 `xueshu789.yaml` 示例文件名；正文无 `get("xueshu789")`、`/dbItem/3`、`ddata` 实测段。人工确认正文（附录除外）无站点硬编码。

- [ ] **Step 9: Commit**

```bash
git add backend/skills/skill_md/shipped/literature-research/SKILL.md
git commit -m "docs(literature-research): 工作流参数化为 <site_id>，xueshu789 降级为示例附录"
```

---

### Task 4: 收敛 references/pipeline.md 与 backend README

**Files:**
- Modify: `backend/skills/skill_md/shipped/literature-research/references/pipeline.md`
- Modify: `backend/literature/README.md`

- [ ] **Step 1: pipeline.md 示例 id 改占位符（line 12、32）**

- line 12：`"site_id": "xueshu789",` → `"site_id": "<site_id>",`
- line 32：`"source_site": "xueshu789",` → `"source_site": "<site_id>",`

- [ ] **Step 2: 替换 pipeline.md「xueshu789 现状」整段（line 265-282）**

把从 `## xueshu789 现状` 到该节末尾的整段替换为：

```markdown
## 站点 profile 示例

可复制的示例 profile 在 `docs/templates/literature-sites/`（不参与运行时加载）。
启用：`cp docs/templates/literature-sites/<site>.yaml ~/.sage/literature_sites/`。
`interactive` 模式字段（`entry_url` / `input_selectors` / `submit_key` / `wait_after_s`）
的规范见 `backend/literature/README.md`；具体站点的选择器与实测要点写在该站点
profile 的注释与模板 README 中，不要写进本数据契约文档。
```

- [ ] **Step 3: backend README 收敛 xueshu789 专段（line 145-159）**

把 `## xueshu789 已实测事实` 整节替换为：

```markdown
## 站点 profile 示例

内建站点目录 `backend/literature/sites/` 保持中立（不携带具体站点）。示例 profile
见 `docs/templates/literature-sites/`，复制到 `~/.sage/literature_sites/` 或
`<项目>/.sage/literature_sites/` 后生效；加载优先级 builtin < 用户级 < 项目级。
具体站点的选择器与实测要点写在该站点 profile 注释与模板 README 中。
```

- [ ] **Step 4: 验证两份文档正文无 xueshu789 残留（示例路径除外）**

Run:
```bash
grep -n "xueshu789\|dbItem\|ddata\|学术资源站" backend/skills/skill_md/shipped/literature-research/references/pipeline.md backend/literature/README.md
```
Expected: 无命中（模板路径指向 `docs/templates/literature-sites/`，不含具体站点名）。

- [ ] **Step 5: Commit**

```bash
git add backend/skills/skill_md/shipped/literature-research/references/pipeline.md backend/literature/README.md
git commit -m "docs(literature): 站点示例从数据契约/README 收敛到 docs/templates"
```

---

### Task 5: 清理代码 docstring 中的 xueshu789

**Files:**
- Modify: `backend/literature/cli.py:5-6`
- Modify: `backend/literature/search.py:145`

- [ ] **Step 1: cli.py docstring 示例改占位符**

把：
```
    python -m backend.literature.cli init --root runs --topic 主题 --site xueshu789
    python -m backend.literature.cli guidance --site xueshu789 --query 机器学习
```
改为：
```
    python -m backend.literature.cli init --root runs --topic 主题 --site <site_id>
    python -m backend.literature.cli guidance --site <site_id> --query 机器学习
```

- [ ] **Step 2: search.py docstring 通用化**

把 `download_pdf` 的 docstring 中：
```
    xueshu789 等站点的 href 除 url 外还带站点需要的附加参数（如
    ``&ddata=文件名|库|题名|库|hash``）；必须点击 DOM 元素本身，
    不要用快照里可能截断的 URL 直连，否则服务端会报「参数错误」。
```
改为：
```
    部分站点的 href 除 url 外还带站点需要的附加参数（如 ``&ddata=...``）；
    必须点击 DOM 元素本身，不要用快照里可能截断的 URL 直连，
    否则服务端会报「参数错误」。
```

- [ ] **Step 3: 验证源码无 xueshu789 残留**

Run:
```bash
grep -rn "xueshu789" backend/ --include="*.py" | grep -v "/tests/"
```
Expected: 无命中（docstring 已通用化）。

- [ ] **Step 4: 跑相关测试 + ruff**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_pipeline.py backend/tests/unit/test_literature_site_profiles.py -q
/home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/literature/ backend/tests/unit/test_literature_site_profiles.py
```
Expected: 测试全绿；ruff 无错误（docstring 仅改文字，不影响 lint；如触发 Q000/ERA001 按既有规范处理）。

- [ ] **Step 5: Commit**

```bash
git add backend/literature/cli.py backend/literature/search.py
git commit -m "docs(literature): docstring 去除 xueshu789 具名，改为通用站点措辞"
```

---

### Task 6: 全仓残留审计与收尾

**Files:** 无改动（仅验证）

- [ ] **Step 1: 全仓 xueshu789 残留审计**

Run:
```bash
grep -rln "xueshu789" . 2>/dev/null | grep -v "__pycache__" | grep -v "\.git/" | grep -v "node_modules" | sort
```
Expected: 只剩允许的引用位置：
- `docs/templates/literature-sites/xueshu789.yaml`（示例文件本体）
- `docs/templates/literature-sites/README.md`（示例说明）
- `backend/tests/unit/test_literature_site_profiles.py`（模板测试，允许）
- `docs/plans/2026-11-25-xueshu789-site-decoupling.md`（本计划）
- 可能残留：`backend/tests/unit/test_literature_pipeline.py`（若用 xueshu789 作 site_id 字面量，属测试数据，可保留或改 `demo`，见 Step 2）
- `backend/logs/*.log`（历史日志，不管）

不允许出现在：`backend/literature/`(除 sites/README)、`backend/skills/skill_md/shipped/literature-research/`（除附录示例文件名）。

- [ ] **Step 2: 如 test_literature_pipeline.py 用 xueshu789 仅作 site_id 字面量，可保留或改为 demo**

检查 line 127：`create_run(tmp_path, topic="大模型综述", site_id="xueshu789", run_id="r1")` 与 line 437-465（自写 yaml）。这些不依赖 builtin profile，属测试数据。**可选**改为 `demo` 以彻底去名，但非必须（不影响产品中立）。若改，跑 `pytest backend/tests/unit/test_literature_pipeline.py -q` 确认绿。

- [ ] **Step 3: 跑文献相关全量测试**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_literature_pipeline.py backend/tests/unit/test_literature_site_profiles.py -q
```
Expected: 全绿（记录 pass 数）。

- [ ] **Step 4: 验证 runtime 仍能发现内置 cnki adapter**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -c "
from backend.skills.builtin.academic_adapters import get_site_adapter
print(get_site_adapter('cnki').name)
"
```
Expected: 打印 `cnki`（内置 adapter 不受影响）。

- [ ] **Step 5: Commit（若 Step 2 改了测试数据）**

```bash
git add backend/tests/unit/test_literature_pipeline.py
git commit -m "test(literature): 测试数据站点名去具名化"
```

---

## 风险与回滚

- **风险**：用户当前机器若已依赖 builtin 的 xueshu789（直接 `get("xueshu789")` 而无用户级配置），迁移后会 `SiteProfileError`。**缓解**：Task 1 的模板 README 与 SKILL.md 引导用户复制模板；本机可先执行 `mkdir -p ~/.sage/literature_sites && cp docs/templates/literature-sites/xueshu789.yaml ~/.sage/literature_sites/` 保持可用。本计划不改引擎回退行为（`get_site_adapter` 找不到即报错，符合"站点须显式配置"）。
- **风险**：`backend/literature/sites/` 删空后若无 README 会被 git 丢弃目录。**缓解**：Task 1 Step 3 显式建 README。
- **回滚**：全部为配置/文档迁移，`git revert` 对应 commit 即恢复 builtin 行为。

## 验收总标准

1. `backend/literature/sites/` 不含任何具体站点 yaml，仅 README。
2. `docs/templates/literature-sites/xueshu789.yaml` 可被 `SiteProfileStore([ProfileRoot(...,"template")])` 加载。
3. shipped `literature-research/SKILL.md` 正文无站点硬编码，仅附录示例路径。
4. 文献相关单测全绿，ruff 无新错误。
5. `get_site_adapter("cnki")` 仍可用。
