# KNS 5.5 / 跨 frame 检索结果支持 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让受控浏览器的快照与交互能读取任意子 frame（同源/跨域 iframe、frameset/<frame>、多层嵌套），解决老版知网 KNS 5.5 等站点「能登录、能搜索、拿不到搜索结果」的问题。

**Architecture:** 页面内 JS 仍负责主文档采集；新增 CDP 全帧巡检（`Page.getFrameTree` + `Page.createIsolatedWorld` + `Runtime.evaluate(contextId)`）作为子 frame 的权威采集通道，聚合到同一份快照 payload。快照把 `ref → frame` 映射记到进程侧，交互时按 ref 在目标 frame 的隔离世界执行（元素用 `data-sage-ref` 属性跨世界定位），点击后按全帧就绪等待。CDP 帧 API 不可用时回退到现有「页面内遍历同源 iframe」路径。

**Tech Stack:** Python 3.10（main，代码保持 py38 兼容写法）、Chrome DevTools Protocol、现有 `backend/tools/browser_*.py` 工具层、pytest。

**Spec:** 本计划的背景分析见 `docs/technical/159-controlled-browser-use.md`（观察层 v2.1 与已知限制表）；老版知网结果位于 `<iframe id="iframeResult">` 为社区共识结构（Zotero 翻译器 / 集搜客论坛）。

## Global Constraints

- 运行/测试一律使用 `/home/fz/anaconda3/envs/sage-backend/bin/python`，不得污染 base。
- 新代码保持 Python 3.8 兼容写法（`typing.Dict/List/Optional`，不用 `X | Y`、不用内置泛型语法）；模块首行沿用 `# ruff: noqa: UP006, UP007, UP035`。
- 交互工具（tools）本就允许依赖 services；新增逻辑不得引入新的分层违规。
- **安全硬约束**：跨 frame 读取（CDP）绕过同源策略，因此每个子 frame 在读取/交互前必须过站点策略：`browser_safety.check_site` 仅 `allow` 可读；`confirm` 走 `_site_access_gate` 触发用户确认；`block` 直接拒绝。
- 不允许 `except Exception: pass` 形态；CDP 失败要么向上抛 `BrowserCDPError`，要么记录 `logger.debug` 后降级。
- 单文件 ≤ 800 行（新模块必须低于红线）；已有文件增长需在 `architecture-baseline.json` 按实测更新（`split('\n').length` = `wc -l` + 1）。
- 提交信息走 conventional commits；每个 Task 独立可测、独立提交。

---

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/tools/browser_frames.py` | 新建 | CDP 帧枚举、隔离世界创建/求值、全帧就绪等待 |
| `backend/tools/browser_observe.py` | 修改 | 快照 JS 支持 `ref_offset` / `frame_url` / `include_iframes`；`next_ref`、`frameset_count`；跨 frame ref 表达式；payload 合并 |
| `backend/tools/browser_tool.py` | 修改 | snapshot 集成帧巡检 + `frames` 元数据；interact 跨 frame ref 定位/门禁/执行；点击后全帧等待 |
| `backend/tests/unit/test_browser_frames.py` | 新建 | 帧树展平、CDP 调用、隔离世界执行、就绪等待 |
| `backend/tests/unit/test_browser_observe.py` | 修改 | 新表达式参数、合并逻辑、跨 frame ref 守卫 |
| `backend/tests/unit/test_browser_tool.py` | 修改 | stub 适配 Page.*；snapshot 合并；frame ref 点击；站点策略 |
| `backend/skills/skill_md/shipped/cnki-research/SKILL.md` | 修改 | KNS 5.5 旧站/内网镜像操作指引 |
| `backend/skills/skill_md/shipped/academic-search/SKILL.md` | 修改 | 旧站/登录场景明确指向 `cnki-research` |
| `docs/technical/159-controlled-browser-use.md` | 修改 | 观察层 v2.2、已知限制表更新 |
| `architecture-baseline.json` | 修改 | 按实测更新 browser_tool / test_browser_tool 行数 |

---

### Task 1: CDP 帧基础设施（`browser_frames.py`）

**Files:**
- Create: `backend/tools/browser_frames.py`
- Test: `backend/tests/unit/test_browser_frames.py`

**Interfaces:**
- Produces:
  - `FrameInfo(frame_id: str, parent_id: str, url: str, name: str, is_main: bool)`
  - `flatten_frame_tree(tree: Dict[str, Any]) -> List[FrameInfo]`
  - `list_frames(session, target_id: Optional[str] = None) -> List[FrameInfo]`（失败抛 `BrowserCDPError`）
  - `create_world(session, frame_id: str, target_id: Optional[str] = None) -> int`
  - `evaluate_in_context(session, expression: str, context_id: int, target_id: Optional[str] = None) -> Any`
  - `wait_frames_settled(session, target_id: Optional[str] = None, timeout: float = 8.0) -> bool`
  - 常量 `MAX_FRAMES = 20`、`ISOLATED_WORLD_NAME = "sage_snapshot"`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/unit/test_browser_frames.py
from backend.tools import browser_frames


def _tree(url="https://kns.test/result.aspx"):
    return {
        "frameTree": {
            "frame": {"id": "main", "url": url, "name": "", "parentId": None},
            "childFrames": [
                {
                    "frame": {
                        "id": "f-result",
                        "url": "https://kns.test/brief.aspx?pagename=ASP.brief_result_aspx",
                        "name": "iframeResult",
                        "parentId": "main",
                    }
                },
                {
                    "frame": {"id": "f-nested", "url": "about:blank", "name": "", "parentId": "f-result"},
                },
            ],
        }
    }


def test_flatten_frame_tree_marks_main_and_children():
    frames = browser_frames.flatten_frame_tree(_tree())
    assert [f.frame_id for f in frames] == ["main", "f-result", "f-nested"]
    assert frames[0].is_main is True
    assert frames[1].name == "iframeResult"
    assert frames[2].parent_id == "f-result"


def test_list_frames_issues_page_enable_and_get_frame_tree(monkeypatch):
    calls = []

    def fake_cdp(session, method, params=None, target_id=None):
        calls.append(method)
        if method == "Page.getFrameTree":
            return _tree()
        return {}

    monkeypatch.setattr(browser_frames, "cdp_command", fake_cdp)
    frames = browser_frames.list_frames(object())
    assert [c for c in calls if c.startswith("Page.")] == ["Page.enable", "Page.getFrameTree"]
    assert len(frames) == 3


def test_create_world_rejects_missing_context(monkeypatch):
    monkeypatch.setattr(
        browser_frames, "cdp_command", lambda *a, **k: {"executionContextId": 0}
    )
    try:
        browser_frames.create_world(object(), "f-result")
    except browser_frames.BrowserCDPError:
        pass
    else:
        raise AssertionError("expected BrowserCDPError")


def test_evaluate_in_context_passes_context_id(monkeypatch):
    captured = {}

    def fake_cdp(session, method, params=None, target_id=None):
        captured.update(params or {})
        return {"result": {"value": "ok"}}

    monkeypatch.setattr(browser_frames, "cdp_command", fake_cdp)
    assert browser_frames.evaluate_in_context(object(), "1+1", 7) == "ok"
    assert captured["contextId"] == 7
    assert captured["returnByValue"] is True
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /home/fz/project/sage/.worktrees/feat-browser-cross-frame-snapshot && /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_browser_frames.py -v`
Expected: FAIL（ModuleNotFoundError）。

- [ ] **Step 3: 实现最小代码**

关键点：`flatten_frame_tree` 递归展平（主 frame 置首）；`list_frames` 先 `Page.enable` 再 `Page.getFrameTree`（均为页面级调用，传 `target_id`）；`create_world` 用 `Page.createIsolatedWorld({"frameId", "worldName"})`；`evaluate_in_context` 的 `Runtime.evaluate` 带 `contextId` 与 `returnByValue`，`exceptionDetails` 非空时抛 `BrowserCDPError`；`wait_frames_settled` 每 0.3s 轮询每个 frame 的 `document.readyState` 与 `innerText` 长度，连续 2 轮 readyState∈{interactive, complete} 且长度不变 → True，超时 False；frame 上下文销毁（求值抛错）时下一轮重建世界。

- [ ] **Step 4: 运行通过**

Run: `... -m pytest backend/tests/unit/test_browser_frames.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/tools/browser_frames.py backend/tests/unit/test_browser_frames.py
git commit -m "feat(browser): CDP 全帧枚举与隔离世界执行基础设施"
```

---

### Task 2: 快照表达式扩展与 payload 合并（`browser_observe.py`）

**Files:**
- Modify: `backend/tools/browser_observe.py`
- Test: `backend/tests/unit/test_browser_observe.py`

**Interfaces:**
- `build_snapshot_expression(mode="interactive", max_collect=..., include_offscreen=False, include_iframes=True, ref_offset=1, frame_url="") -> str`
  - 默认参数保持现行为（回归兼容）。
- JS 返回新增：`next_ref`（下一个可用 ref 序号）、`frameset_count`（`document.querySelectorAll('frame').length`）。
- `merge_snapshot_payloads(main: Dict, frames: List[Dict], frames_meta: List[Dict]) -> Dict`
- `build_frame_ref_expression(action_js: str, ref: str, expected_name: str) -> str`
- `build_frame_target_expression(ref: str) -> str`
- 常量 `IFRAME_MAX_COLLECT_PER_FRAME` 60 → 150。

- [ ] **Step 1: 写失败测试**

```python
# test_browser_observe.py 追加
def test_build_snapshot_expression_accepts_ref_offset_and_disables_iframes():
    expr = browser_observe.build_snapshot_expression(
        "interactive", include_iframes=False, ref_offset=11, frame_url="https://x/f"
    )
    assert "var START_REF = 11;" in expr
    assert 'var FRAME_URL = "https://x/f";' in expr
    assert "var INCLUDE_IFRAMES = false;" in expr
    assert "next_ref" in expr
    assert "frameset_count" in expr


def test_merge_snapshot_payloads_offsets_refs_and_annotates_frame_url():
    main = {
        "url": "https://kns/", "title": "T", "elements": [{"ref": "e1", "role": "button"}],
        "text": "主", "next_ref": 2, "iframes_scanned": 0,
    }
    sub = {
        "url": "https://kns/brief.aspx", "title": "R",
        "elements": [{"ref": "e2", "role": "link", "name": "论文A"}],
        "text": "结果", "next_ref": 3,
    }
    merged = browser_observe.merge_snapshot_payloads(
        main, [sub], [{"frame_id": "f1", "url": "https://kns/brief.aspx", "state": "scanned"}]
    )
    assert merged["elements"][1]["frame_url"] == "https://kns/brief.aspx"
    assert merged["text"] == "主\n结果"
    assert merged["iframes_scanned"] == 1
    assert merged["frames"][0]["state"] == "scanned"


def test_build_frame_ref_expression_guards_stale_ref_and_name():
    expr = browser_observe.build_frame_ref_expression("(function(){return{ok:true};})()", "e12", "论文A")
    assert "data-sage-ref" in expr
    assert "论文A" in expr
    assert "stale-ref" in expr
```

- [ ] **Step 2: 运行确认失败**

Run: `... -m pytest backend/tests/unit/test_browser_observe.py -v`
Expected: FAIL（参数/函数不存在）。

- [ ] **Step 3: 实现**

- `_INTERACTIVE_JS` 增加占位符替换：`__START_REF__`、`__FRAME_URL__`、`__INCLUDE_IFRAMES__`；`collect(document, START_REF, FRAME_URL ? FRAME_URL : null)`；iframe 遍历整段包在 `if (INCLUDE_IFRAMES) { ... }` 内；返回值加 `next_ref: nextRef`、`frameset_count: document.querySelectorAll('frame').length`。
- `_TEXT_JS` 返回值加 `frameset_count`；保留 iframe 文本遍历（fallback 路径用）。
- `build_snapshot_expression` 签名扩展并替换占位符；`_TEXT_JS` 分支忽略 offset/frame_url。
- `merge_snapshot_payloads`：元素拼接；子 frame 每个元素补 `frame_url`（若自身没有）；文本 `"\n".join` 后 `slice` 到 `SNAPSHOT_TEXT_CAP`；`iframes_scanned = len(frames)`；`iframes_truncated` 取各 payload 的或；`frames` 原样透传；`next_ref` 取最后一个 payload 的值。
- `parse_snapshot_payload`：`frames` 字段做类型校验后透传。
- `build_frame_ref_expression`：`document.querySelector("[data-sage-ref='e12']")` + `isConnected` + `data-sage-ref-name` 校验。
- `build_frame_target_expression`：按 data 属性定位后复用现有元数据读取片段（把 `_read_target_metadata` 的 `name_source` 抽成模块级常量以便复用）。

- [ ] **Step 4: 运行通过**

Run: `... -m pytest backend/tests/unit/test_browser_observe.py -v`
Expected: PASS（含既有 403 行测试）。

- [ ] **Step 5: 提交**

```bash
git commit -am "feat(browser): 快照表达式支持跨帧偏移/合并与帧内 ref 定位"
```

---

### Task 3: snapshot 工具集成帧巡检

**Files:**
- Modify: `backend/tools/browser_tool.py`（`BrowserSnapshotTool.execute` 及新增私有函数）
- Test: `backend/tests/unit/test_browser_tool.py`

**Interfaces:**
- 新增模块级 `_SNAPSHOT_FRAME_REFS: Dict[str, Dict[str, Dict[str, str]]]`（`browser_id -> ref -> {frame_id, frame_url, name}`）。
- 新增 `_collect_frame_snapshot(session, mode, include_offscreen) -> Optional[Tuple[Dict, List[Dict], Dict]]`：
  - `list_frames` 抛 `BrowserCDPError` → 返回 `None`（调用方走旧 JS fallback）。
  - 子 frame 按站点策略过滤：`allow` 扫描；`confirm`/`block` 记 `frames.state` 并跳过内容。
  - 每个可读子 frame：`create_world` → `build_snapshot_expression(..., include_iframes=False, ref_offset=next_ref, frame_url=frame.url)` → `evaluate_in_context`。
- 快照流程：主框架先按 `include_iframes=False` 取 payload → `_collect_frame_snapshot`；返回 `None` 时用 `include_iframes=True` 重拍（旧路径）并清空 ref 映射；成功时 `merge_snapshot_payloads` 并写入 `_SNAPSHOT_FRAME_REFS`。

- [ ] **Step 1: 测试 stub 适配与新增用例**

`stubbed._fake_cdp` 增加无队列消耗的缺省应答：

```python
if method == "Page.enable":
    return {}
if method == "Page.getFrameTree":
    return {"frameTree": {"frame": {"id": "main", "url": "https://x/"}}}
if method == "Page.createIsolatedWorld":
    return {"executionContextId": 1}
if method == "Runtime.evaluate" and (params or {}).get("contextId"):
    return {"result": {"value": json.dumps({"url": "u", "title": "t", "elements": [], "text": ""})}}
```

新增用例（可覆盖 `_fake_cdp` 返回值模拟子 frame）：

```python
def test_snapshot_merges_child_frame_elements(stubbed, monkeypatch):
    # getFrameTree 返回主 + 子 frame；两次 Runtime.evaluate（主/子）分别给 payload
    ...
    result = _tool(BrowserSnapshotTool).execute(browser_id="b1")
    assert any(el.get("frame_url") for el in result.content["elements"])
    assert result.content["iframes_scanned"] == 1

def test_snapshot_skips_blocked_child_frame(stubbed, monkeypatch):
    # 子 frame 域名被 block → 内容不读，frames[0].state == "blocked"
    ...
```

- [ ] **Step 2-4: 运行失败 → 实现 → 通过**

Run: `... -m pytest backend/tests/unit/test_browser_tool.py -v`
Expected: 先 FAIL（帧未合并），实现后 PASS。

- [ ] **Step 5: 提交**

```bash
git commit -am "feat(browser): snapshot 经 CDP 巡检全帧并输出 frames 元数据"
```

---

### Task 4: 交互跨 frame ref/门禁/就绪等待

**Files:**
- Modify: `backend/tools/browser_tool.py`
- Test: `backend/tests/unit/test_browser_tool.py`

**Interfaces:**
- `_read_target_metadata`：ref 命中 `_SNAPSHOT_FRAME_REFS` 时，经 `create_world` + `build_frame_target_expression` 在该 frame 读取元数据。
- `BrowserInteractTool.execute`：ref 属于子 frame 时，先 `_site_access_gate(session, frame_url, ...)`；构造 `build_frame_ref_expression` 并在该 frame 的隔离世界执行；结果信封不带 frame 的 url/title（保持顶层页面缓存）。
- 点击后等待：`_wait_after_click(session)` —— `list_frames` 显示 >1 个 frame → `browser_frames.wait_frames_settled`；否则保留 `_wait_network_idle(timeout=5.0)`；帧 API 失败按旧路径降级。

- [ ] **Step 1: 新增测试**

```python
def test_interact_frame_ref_click_uses_child_context(stubbed, monkeypatch):
    # 先执行一次 snapshot（模拟主 + 子 frame）建立 ref 映射，
    # 再 click ref → 断言 Runtime.evaluate 的 contextId == 子 frame 世界
    ...

def test_interact_frame_ref_respects_blocked_frame(stubbed, monkeypatch):
    # 子 frame 域名 block → click 被拒，错误含 site_blocked
    ...
```

- [ ] **Step 2-4: 运行失败 → 实现 → 通过**

Run: `... -m pytest backend/tests/unit/test_browser_tool.py backend/tests/unit/test_browser_observe.py -v`

- [ ] **Step 5: 提交**

```bash
git commit -am "feat(browser): 交互支持子 frame ref 与全帧就绪等待"
```

---

### Task 5: 技能与文档

**Files:**
- Modify: `backend/skills/skill_md/shipped/cnki-research/SKILL.md`
- Modify: `backend/skills/skill_md/shipped/academic-search/SKILL.md`
- Modify: `docs/technical/159-controlled-browser-use.md`

- [ ] **Step 1: cnki-research 增补「旧版 KNS 5.5 / 内网镜像」小节**：入口 URL 形态、结果在 `#iframeResult`、检索后 `iframes_scanned`/`frame_url` 自诊断、结果为空等 2–3 秒重拍、翻页点 `Page_next`（用 ref）、不要复制 QueryID 链接到新窗口、frame 内详情链接必须用 ref 点击。
- [ ] **Step 2: academic-search 明确旧站/登录场景转 `cnki-research`**。
- [ ] **Step 3: §159 更新**：观察层 v2.2（CDP 全帧巡检、`frames` 元数据、全帧就绪等待、隔离世界交互）；已知限制表删除「无跨域 iframe 定向」，改为「selector/text 定位仍只作用于顶层，子 frame 请用 ref」。
- [ ] **Step 4: 提交** `docs(browser): 更新 KNS 5.5 与跨帧快照说明`。

---

### Task 6: 全量验证与棘轮

- [ ] **Step 1: 定向测试**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_browser_frames.py \
  backend/tests/unit/test_browser_observe.py \
  backend/tests/unit/test_browser_tool.py \
  backend/tests/unit/test_browser_cdp_external.py \
  backend/tests/unit/test_browser_control.py \
  backend/tests/api/test_browser_use_routes.py -q
```

- [ ] **Step 2: ruff**：`ruff check backend/tools/browser_frames.py backend/tools/browser_observe.py backend/tools/browser_tool.py backend/tests/unit/test_browser_frames.py`
- [ ] **Step 3: 静默异常棘轮**：`python scripts/check_silent_exceptions.py`
- [ ] **Step 4: 架构棘轮**：按实测更新 `architecture-baseline.json`（`node scripts/architecture-check.mjs` 报告为准；`split('\n').length`），确认无新违规。
- [ ] **Step 5: py38 兼容自检**（win7 同步前）：`python scripts/check_py38_compat.py`（若脚本仅 win7 触发则跳过并记录）。
- [ ] **Step 6: 提交** `test(browser): 跨帧快照回归与棘轮基线`。

---

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 外部浏览器扩展桥不支持 `Page.createIsolatedWorld` | 帧巡检失败即回退旧 JS 路径；不影响现有能力 |
| 跨域 frame 读取绕过同源策略 | 强制逐 frame 站点策略；`confirm` 走现有确认流程；block 不读 |
| 隔离世界看不到主世界的 `__SAGE_ACTIVE_REQUESTS__` | 全帧等待改用 readyState + 文本长度稳定，不依赖该计数器 |
| 子 frame 导航后上下文销毁 | 求值失败视为未就绪，下一轮重建世界；ref 失效给出 stale-ref 提示 |
| 快照体积膨胀 | 每子 frame 90 元素、最多 20 帧、正文上限沿用 30KiB；`truncated` 标记 |
| 既有测试的 CDP 调用序列假设 | stub 对 Page.* 提供不消耗队列的缺省应答；新增断言集中在独立用例 |

## 验收清单

- [ ] 老版 KNS 5.5（同源 `#iframeResult`）：snapshot 返回结果链接且带 `frame_url`
- [ ] 跨域子 frame fixture：snapshot 返回结果文本与 ref
- [ ] frameset fixture：snapshot 能读取结果
- [ ] 子 frame ref 点击进入详情；`Page_next` 翻页后重新快照正常
- [ ] 子 frame 域名被 block 时 snapshot 不读内容、interact 被拒
