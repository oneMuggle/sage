# M1b：xueshu789 交互式检索适配 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 SiteProfile 支持"入口页 → 输入关键词 → Enter 提交"的交互式检索，提供真实 `SageToolDriver`（基于 `execute_code` 的 `sage.call`），并把 xueshu789 实测事实写回 profile。

**Architecture:** 在 M1a 的 `SiteProfile` / `search_with_profile` 上扩展 `mode: interactive` 分支；`BrowserDriver` 增加 `type_text` / `press_key` / `sleep` / `click_text`；新增 `SageToolDriver` 把 driver 调用映射到 `sage.call("browser_*")`。站点差异仍只在 YAML。

**Spec:** `docs/plans/2026-11-21_literature-research-paper-pipeline.md`（M1b）

## 实测事实（2026-11-21）

- xueshu789 已登录状态：首页 → `/dbList/1`，列出 `/dbItem/N` 入口。
- `/dbItem/1` 代理报「出错啦」；`/dbItem/2` 触发知网滑块验证；**`/dbItem/3` 可用**，重定向到
  `http://82.157.23.222:5888/kns8s/defaultresult/index`（标题「检索-中国知网」）。
- 搜索框 placeholder：「若检索词含*、+、-等特殊符号，需加半角引号。如：'8-姜酚'」；
  输入关键词后 **Enter 提交**，约 5 秒后结果渲染（总库 1.25 万条）。
- 结果条目：题名/作者/来源链接均指向
  `https://www.xueshu789.cc/doDownload?url=<encoded kns.cnki.net kcms2 abstract>`；
  操作列有「下载 / 原版阅读 / CNKI AI阅读」。
- **下载已实测通过（2026-11-22）**：`a.downloadlink` 的真实 href 还带
  `&ddata=<文件名>|<库>|<题名>|<库>|<hash>`；点击该元素会经
  `oversea.cnki.net/docdown/fulltext/download` 落盘 PDF（实测 787KB / 26 页）。
  之前「参数错误」是因为用快照里截断的 `doDownload?url=...` 直连，缺少 `ddata`；
  修复后 profile `status: ready`。

## Global Constraints

- Python 3.8 兼容；不新增依赖；不新增 chat 工具。
- 站点差异只在 profile；pipeline 无 `if site == ...`。
- 验证码/滑块只报告，不破解；不代填密码、不导出 cookie。
- 运行目录写入沿用 M1a 的 `run_store`；不破坏 url 模式。

---

## Task 1: 模型支持交互式检索

**Files:** `backend/literature/models.py`、`backend/literature/guidance.py`、`backend/tests/unit/test_literature_site_profiles.py`

**Interfaces:**
- `SearchSpec` 新增：
  - `mode: str = "url"`（`url` | `interactive`）
  - `entry_url: Optional[str] = None`
  - `entry_click: Optional[str] = None`
  - `input_selectors: Tuple[str, ...] = ()`
  - `submit_key: str = "Enter"`
  - `wait_after_s: float = 0.0`
  - `result_hint: str = ""`
- `PdfSpec` 新增：`post_click_wait_s: float = 0.0`、`note: Optional[str] = None`
- 校验：
  - `mode` 仅允许两个值；
  - `url` 模式仍要求 `url_template` 含 `{query}`；
  - `interactive` 模式要求 `entry_url`（或 `url_template`）与 `input_selectors`。
- `render_search_guidance` 在 interactive 模式下输出入口、输入框选择器、提交键、等待秒数、结果提示。

**测试：** interactive profile 解析；缺 input_selectors 报错；guidance 含入口/选择器/Enter/结果提示；url 模式回归不变。

---

## Task 2: 驱动协议与交互式 search

**Files:** `backend/literature/search.py`、`backend/tests/unit/test_literature_pipeline.py`

**Interfaces:**
- `BrowserDriver` 新增：
  - `type_text(selector: str, text: str, clear: bool = True) -> bool`
  - `press_key(key: str) -> None`
  - `sleep(seconds: float) -> None`
  - `click_text(text: str) -> None`
- `search_with_profile` interactive 分支：
  1. navigate `entry_url`（或 url_template）
  2. 可选 `entry_click` → click_text + sleep(1)
  3. 依次尝试 `input_selectors` 直到 `type_text` 返回 True
  4. `press_key(submit_key)`；`sleep(wait_after_s)`；snapshot
  5. 返回 `SearchObservation`

**测试：** 假驱动记录调用序列；所有 selector 失败时报错；interactive guidance 含 result_hint。

---

## Task 3: SageToolDriver（真实浏览器）

**Files:** `backend/literature/sage_driver.py`、`backend/tests/unit/test_literature_pipeline.py`

**Interfaces:**
- `SageToolDriver(call)`，`call` 形如 `sage.call(name, **kwargs)`：
  - `navigate` → `browser_navigate`
  - `snapshot` → `browser_snapshot(mode="full", max_nodes=250)`
  - `type_text` → `browser_interact(action="type", selector=..., value=..., clear=True)`
  - `press_key` → `browser_interact(action="press", key=...)`
  - `click_text` → `browser_interact(action="click", text=...)`
  - `wait_download` → `browser_downloads(wait_for_complete=True, timeout=...)`
  - `sleep` → `time.sleep`
  - `current_url/title` 取自最近一次 navigate/snapshot 返回的 `browser_meta`
- 工具失败（`sage.call` 抛 RuntimeError）时，`type_text` 返回 False（供多 selector 回退），其余方法向上抛。

**测试：** 用 fake `call` 记录调用；验证 navigate/type/press/snapshot 参数；type 失败返回 False；download 解析最新文件。

---

## Task 4: xueshu789 profile 与文档

**Files:** `backend/literature/sites/xueshu789.yaml`、`backend/literature/README.md`、`backend/skills/skill_md/shipped/literature-research/SKILL.md`、`references/pipeline.md`

更新 profile：

```yaml
search:
  mode: interactive
  url_template: "https://www.xueshu789.cc/dbItem/3"
  entry_url: "https://www.xueshu789.cc/dbItem/3"
  input_selectors:
    - "input[placeholder*='检索词']"
    - "textarea[placeholder*='检索词']"
  submit_key: Enter
  wait_after_s: 5
  result_hint: "每条结果含题名/作者/来源链接（均指向 doDownload）+ 下载/原版阅读/CNKI AI阅读；结果总数在页面上方"
pdf:
  entry_text: 下载
  post_click_wait_s: 8
  note: "点击 a.downloadlink（href 含 &ddata=文件名|库|题名|库|hash）；不要用快照截断 URL 直连"
```

- `domains` 追加代理 IP `82.157.23.222`。
- `status: draft`；`last_verified_at: 2026-11-21`。
- README 增加 interactive 模式字段说明与 xueshu789 实测记录。
- SKILL.md 增加 `SageToolDriver` 用法示例；references 记录 `/dbItem/1`/`2`/`3` 的实测差异与验证码边界。

---

## Task 5: 全量验证与提交

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_literature_pipeline.py \
  backend/tests/unit/test_literature_site_profiles.py \
  backend/tests/unit/test_academic_adapters.py \
  backend/tests/unit/test_academic_search.py \
  backend/tests/unit/test_shipped_writing_skills.py \
  backend/tests/unit/test_skill_md_loader.py -q
/home/fz/anaconda3/envs/sage-backend/bin/ruff check backend/literature backend/tests/unit/test_literature_pipeline.py
/home/fz/anaconda3/envs/sage-backend/bin/python scripts/check_py38_compat.py backend/literature
```

然后提交并推送分支、开 PR。
