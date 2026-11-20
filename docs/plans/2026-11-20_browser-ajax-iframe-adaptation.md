# 受控浏览器 AJAX / iframe 适配方案

> 日期：2026-11-20
> 分支：`feat/browser-ajax-iframe-adaptation`
> 目标：修复受控浏览器在知网等 SPA + AJAX + iframe 站点上"搜索后拿不到结果"的根本问题

---

## 背景与问题

**现象**：使用 alpha.83 win7 安装包访问内网知网镜像库，能登录、能输入搜索词、能点击搜索，但搜索结果获取不到。

**根因分析（已确认代码位置）**：

### 缺陷 1：`wait_page_ready` 不等待 AJAX 请求完成

**文件**：`backend/tools/web_render.py` 第 234–299 行

当前等待逻辑：
1. 轮询 `document.readyState` 直到 `complete`
2. 等待 `document.body.innerText` 长度连续 2 轮不变（上限 3 秒）

**问题**：知网搜索是 Vue SPA，提交搜索后：
- 页面 HTML 早已 `readyState=complete`
- 搜索结果由 XHR/fetch 异步加载（1–5 秒）
- 正文长度在请求发出前后都是"稳定的"（加载中内容未变化）
- `wait_page_ready` 误判为"就绪"，`browser_snapshot` 抓到空结果

### 缺陷 2：`browser_snapshot` 不扫描 iframe 内容

**文件**：`backend/tools/browser_observe.py` 第 62–254 行（`_INTERACTIVE_JS`）

```js
var raw = document.querySelectorAll(SELECTOR);  // 只查主框架
text: (document.body && document.body.innerText || '').slice(0, TEXT_CAP)
```

知网内网镜像部分版本把搜索结果放在 `<iframe>` 内，`document.querySelectorAll` 和 `document.body.innerText` 都看不到 iframe 内容。

### 缺陷 3：`browser_interact` 点击后无 SPA 内容更新等待

点击搜索按钮后 Vue router 切换、数据重新加载，没有等待机制，AI 立刻 `browser_snapshot` 拿到旧内容。

---

## 技术方案

### 方案 A：网络空闲等待（解决缺陷 1，P0）

**改动文件**：`backend/tools/web_render.py`

**核心思路**：在导航/渲染前注入 JS monkey-patch XHR/fetch 计数器，`readyState=complete` 后额外等待活跃请求归零。

```
wait_page_ready 流程变化：
1. readyState 轮询（保持不变）
2. wait_for CSS 选择器轮询（保持不变）
3. 新：等待网络空闲（活跃 XHR+fetch == 0，稳定 2 轮，上限 8 秒）
4. 正文长度稳定窗口（保持不变，_SETTLE_MAX_SECONDS）
```

**注入时机**：`render_page` 中 `Page.navigate` 之前经 `Page.addScriptToEvaluateOnNewDocument` 注入；`browser_navigate` 中 `Page.navigate` 之前同样注入。

**注入 JS（`_NETWORK_MONITOR_JS`）**：
- 拦截 `XMLHttpRequest.prototype.open/send`，在 `loadend` 递减计数器
- 拦截 `window.fetch`，在 `.finally()` 递减计数器
- 计数器暴露为 `window.__SAGE_ACTIVE_REQUESTS__`
- 幂等：`if (window.__SAGE_NET_INIT__) return`

**新增常量**：
- `_NETWORK_IDLE_TIMEOUT = 8.0`（网络空闲等待上限）
- `_NETWORK_IDLE_STABLE_ROUNDS = 2`（连续归零轮数）
- `_NETWORK_IDLE_POLL_INTERVAL = 0.3`

### 方案 B：iframe 内容采集（解决缺陷 2，P1）

**改动文件**：`backend/tools/browser_observe.py`、`backend/tools/browser_tool.py`

**核心思路**：快照时通过 CDP `Page.getFrameTree` 枚举所有子 frame，对每个 frame 用 `Page.createIsolatedWorld` 注入采集 JS，合并结果。

**新增函数**（`browser_observe.py`）：

```python
def build_iframe_snapshot_expression(mode, max_collect, ...) -> str:
    """采集 JS：主框架 + 遍历所有 document.querySelectorAll('iframe')，
    对 same-origin iframe 读 contentDocument，跨域 frame 标注 src URL"""

def collect_frame_targets(session, target_id) -> List[Dict]:
    """CDP Page.getFrameTree → 递归展平 childFrames，返回 [{frameId, url}]"""

def snapshot_frame(session, target_id, frame_id, snapshot_js) -> Dict:
    """Page.createIsolatedWorld → Runtime.evaluate → 解析 payload"""
```

**合并策略**：
- 主框架元素 ref 从 `e1` 开始
- 每个 iframe 元素 ref 接着编号（`e{n+1}`...）
- iframe 元素额外标注 `frame_url` 字段（供 AI 知道元素来自哪个 frame）
- 跨域 iframe 若无法注入 JS：记录 `{ref, role: "iframe", name: src_url}`，提示 AI 该 frame 内容不可读

**兼容性**：
- CDP `Page.createIsolatedWorld` 在 Chromium 106（Electron 21）上支持
- 对 `target_id=None`（主框架）保持现有逻辑不变

### 方案 C：SPA 导航等待辅助（解决缺陷 3，P1）

**改动文件**：`backend/tools/browser_tool.py`

**核心思路**：`browser_interact` 成功后，若 action 是 click 且目标是 submit/button/link，自动调用网络空闲等待 + 正文稳定检查。

```python
# browser_interact 成功后，对 click 动作追加等待
if action == "click" and outcome.get("ok"):
    _wait_network_idle(session, None, timeout=5.0)  # 复用方案 A 的函数
    wait_page_ready(session, None)  # 重新跑一次正文稳定
```

**限制**：仅在 click 动作、且目标角色为 button/link/submit 时触发，避免对普通 UI 交互过度等待。

### 方案 D：CNKI SKILL.md 引导更新（快速见效，P0）

**改动文件**：`backend/skills/skill_md/shipped/cnki-research/SKILL.md`

**内容变更**：
1. 搜索导航使用 `wait_for=".result-list, .search-result-wrap, #result-table"`
2. 点击搜索按钮后，指导 AI 主动等待 2–3 秒再 `browser_snapshot`
3. 如果 snapshot 结果列表为空，指导 AI 用 `wait_for` 参数重新 navigate

---

## 涉及的文件

| 文件 | 改动类型 |
|------|---------|
| `backend/tools/web_render.py` | 新增网络监控注入 JS + `_wait_network_idle` 函数；`render_page` 和 `wait_page_ready` 接入 |
| `backend/tools/browser_tool.py` | `BrowserNavigateTool` 导航前注入网络监控；`BrowserInteractTool` click 后追加等待 |
| `backend/tools/browser_observe.py` | 新增 iframe 遍历采集逻辑；修改 `build_snapshot_expression` 支持 iframe |
| `backend/skills/skill_md/shipped/cnki-research/SKILL.md` | 搜索导航加 `wait_for`、点击后等待指导 |

---

## 实施步骤

- [x] 步骤 1：`web_render.py` 新增 `_NETWORK_MONITOR_JS` + `_wait_network_idle` 函数
- [x] 步骤 2：`render_page` 在 `Page.navigate` 前注入网络监控 JS
- [x] 步骤 3：`wait_page_ready` 在 readyState 达标后调用 `_wait_network_idle`
- [x] 步骤 4：`browser_tool.py` `BrowserNavigateTool.execute` 在 `Page.navigate` 前注入网络监控
- [x] 步骤 5：`browser_observe.py` 新增 `collect_frame_targets` + iframe 快照逻辑
- [x] 步骤 6：`browser_tool.py` `BrowserSnapshotTool.execute` 接入 iframe 采集（JS 内联遍历，无需 CDP 改造）
- [x] 步骤 7：`browser_tool.py` `BrowserInteractTool.execute` click 后追加网络空闲等待
- [x] 步骤 8：更新 `cnki-research/SKILL.md` 引导
- [x] 步骤 9：单元测试（`_wait_network_idle`、iframe 枚举、iframe 元数据透传）— 184 个测试通过
- [x] 步骤 10：文档归档（技术手册 §159 更新 iframe 遍历 + 网络空闲等待两节；已知限制表更新）

---

## 风险评估

1. **monkey-patch 冲突**：某些站点自己也 patch XHR/fetch，我们的 patch 需在它们之前执行（`addScriptToEvaluateOnNewDocument` 时机最早）；若站点 patch 链覆盖我们，计数器可能失准 → 降级为不等待（不影响功能正确性，只是等待不充分）

2. **iframe 跨域限制**：CDP `Page.createIsolatedWorld` 能绕过同源策略，但需要 `targetId` 是顶层 page target，frameId 指定子 frame → 在 Electron 21 / Chromium 106 上需实际验证兼容性

3. **性能影响**：每个 iframe 都要注入 JS + 等待执行，iframe 数量多时快照变慢 → 限制最多处理 10 个子 frame，超出标注 "truncated"

4. **向后兼容**：所有改动都是增量，不改变现有工具接口语义；`browser_snapshot` 返回的 `elements` 列表只是可能多出 iframe 内元素（带 `frame_url` 字段），不影响既有 AI 逻辑
