# 159 — 受控浏览器使用（Controlled Browser Use）

> 2026-11-17 M1–M5：CDP 工具面 / 无障碍观察层 v2 / 可见步骤化与接管 / 安全模型 / 视觉兜底

## 能力概览

让主对话里的 AI 像人一样操作网页：打开 URL、观察页面结构、点击/输入、切换标签页、处理下载，
同时把「看得见、停得下、接得住、管得了」作为硬约束：

- **全程可见**：默认打开可见浏览器窗口；右栏浏览器面板提供地址栏与前进/后退/刷新，AI 侧边栏显示
  操作时间线（最近 8 步）、暂停/继续/接管/归还控制/定位窗口按钮。
- **可暂停、可接管**：控制状态机 `agent → paused → user_takeover`，用户接管期间所有受控工具被
  门禁拦截，AI 无法与用户争夺鼠标键盘。
- **安全分层**：持久站点策略（allow/block）→ 会话级站点授权（仅本次/始终允许/拒绝）→
  敏感动作分类（放行/需确认/硬阻断）→ 每次确认绑定一次性指纹，避免「批准一次、复用多次」。
- **纯 CDP、无 Playwright**：直接复用 Electron 内嵌 Chromium 的 DevTools Protocol，兼容
  Win7 / Chromium 106，不引入额外浏览器运行时。
- **观察层不是文本抓取**：基于无障碍树的元素引用协议（`e1`、`e2`…），token 开销可控；
  页面文本一律视为不可信数据，疑似提示注入给出警告。
- **视觉兜底**：`browser_screenshot(return_image=true)` 把画面作为**临时**多轮消息注入下一轮
  上下文（不落库），无视觉能力时降级为本地 OCR 文本。

## 架构分层

```
┌──────────────────────────── 渲染层（React） ────────────────────────────┐
│ BrowserPanel.tsx（右栏：地址栏 / AI 时间线 / 暂停·接管 / 确认条 / 审计） │
│ BrowserUseSection.tsx（设置页：默认可见 / 步骤缩略图 / 站点策略表）      │
└───────────────┬──────────────────────────────────────────┬──────────────┘
                │ REST /api/v1/browser/*                   │ IPC agent_browser_focus
┌───────────────▼───────────────────┐        ┌─────────────▼──────────────┐
│ backend/api/browser_use_routes.py │        │ electron/main.ts            │
│ 控制面 / 确认 / 站点策略 / 配置   │        │ 窗口定位 + 内嵌桥启动        │
└───────┬──────────────┬────────────┘        └─────────────┬──────────────┘
        │              │                                    │
┌───────▼──────┐ ┌─────▼──────────┐              ┌──────────▼─────────────┐
│ browser_     │ │ browser_       │              │ agentBrowserBridge.ts   │
│ control.py   │ │ safety.py      │              │ 127.0.0.1 HTTP/WS 桥    │
│ 状态机        │ │ 策略/分类/确认 │              │ headless/visible 目标表 │
└──────────────┘ └─────┬──────────┘              └──────────┬─────────────┘
                       │                                    │ CDP
              ┌────────▼─────────┐                 ┌────────▼─────────────┐
              │ browser_action_  │                 │ Electron Chromium     │
              │ repo.py（审计）   │                 │ （无头 / 可见窗口）   │
              └──────────────────┘                 └──────────────────────┘
                       ▲                                    ▲
              ┌────────┴────────────────────────────────────┴──────────────┐
              │ backend/tools/browser_tool.py（10 个工具）                  │
              │ backend/tools/browser_observe.py（快照 v2 / ref 协议）       │
              │ backend/tools/browser_cdp.py（CDP 客户端 + 内嵌桥传输）      │
              └───────────────────────────┬────────────────────────────────┘
                                          │ ToolRegistry
                                 ┌────────▼────────┐
                                 │ 主对话 Agent 循环 │
                                 └─────────────────┘
```

| 层 | 模块 | 职责 |
|---|---|---|
| 工具面 | `backend/tools/browser_tool.py` | 10 个 `browser_*` 工具：schema、门禁串联、执行、审计 |
| 观察层 | `backend/tools/browser_observe.py` | 无障碍树快照、ref 注册与解析、按键组合解析 |
| 传输层 | `backend/tools/browser_cdp.py` | CDP 客户端；子进程浏览器或 Electron 内嵌桥二选一 |
| 控制面 | `backend/services/browser_control.py` | 会话控制状态机（线程安全内存注册表） |
| 安全层 | `backend/services/browser_safety.py` | 站点策略、授权、敏感动作分类、确认注册表、注入扫描 |
| 审计 | `backend/data/browser_action_repo.py` + v18 迁移 | `browser_action_log` 表写入与查询 |
| REST | `backend/api/browser_use_routes.py` | 控制/确认/站点策略/配置/审计接口 |
| 桌面桥 | `electron/agentBrowserBridge.ts` | 内嵌浏览器目标管理、CDP 命令白名单转发、窗口聚焦 |
| 渲染层 | `src/features/browser/BrowserPanel.tsx`、`src/pages/settings/BrowserUseSection.tsx` | 右栏面板、设置页区块 |
| 提示词 | `backend/agents/profiles.py` | 含浏览器的系统提示词纪律；主专家/研究型专家的工具种子 |

### 门禁顺序

写操作的执行路径串联多道门禁，任一环节拒绝即返回结构化前缀错误（AI 可据此决策，前端据此着色）。
两条路径的门禁集合不同：

**导航路径（`browser_navigate`）**

1. 参数校验（未知参数直接拒绝）
2. URL 协议校验（`http` / `https` / `about` / `data`；`file://` 拒绝）
3. 网络模式门禁（仅 `http/https` 出网受 `check_host` 约束，与 `web_fetch` 同口径）
4. 控制状态门禁（`user_paused: ` / `user_takeover: `）
5. 站点策略与站点授权（`site_blocked: ` / `denied_by_user: ` / `needs_confirmation: `）
6. 执行导航并等待就绪（含 SPA 稳定）
7. 重定向后按**最终域名**再次校验站点策略
8. 步骤缩略图（失败静默）
9. 审计写入（失败静默，不影响主流程）

**交互路径（`browser_interact`）**

1. 参数校验（upload 额外校验工作区边界与文件存在性——先于确认创建，确认描述
   因此可以带上解析后的文件名）
2. 控制状态门禁（`user_paused: ` / `user_takeover: `）
3. 当前页面站点复核（页面域名被持久策略 `block` → `site_blocked: `，不执行动作）
4. 读取目标元素元数据
5. 敏感动作分级（`hard_blocked: ` / `needs_confirmation: `；用户拒绝后会话暂停）
6. 执行 CDP 动作（ref 失效时返回 stale-ref 提示）
7. 若交互把页面带到**不同域名**（点击链接 / JS 跳转），按最终 URL 重跑站点门禁
   （block → `site_blocked: `；confirm → 站点确认 + paused）
8. 步骤缩略图（失败静默）
9. 审计写入（失败静默，不影响主流程）

> 站点策略同时覆盖其他会产生导航的入口：`browser_tabs(action=create)` 在
> `Target.createTarget` 之前走与 `browser_navigate` 相同的站点门禁；
> `browser_login` 只应用策略的 **block** 部分（blocked 拒绝；未知站点保持允许，
> 因为它是用户主动登录，不应被首次站点确认打断）。`browser_snapshot` 与
> `browser_interact` 在动作前都会复核当前页面域名，策略中途改为 block 或用户拒绝
> 后（会话暂停）不会继续读取被禁止的页面。

### 面板数据源与失败恢复

- **时间线数据源**：持久化消息里的 `tool_calls`（step_done 已逐条写入 assistant
  消息）与实时 `streamingToolCalls` 按 `id` 去重合并。`finalizeStep` /
  `finishStream` 清空实时切片后，历史步骤仍在，面板不会「闪一下就没」。
- **会话记忆**：浏览器 `session_id` 按对话 id 记在独立 zustand store
  （`browserSessionStore`），跨 step / stream 生命周期保留；面板始终轮询该会话。
- **无 meta 恢复**：拿不到 `browser_meta.session_id` 时，面板回退到
  `GET /browser/control`（唯一存活会话）与无过滤的 `/browser/confirmations`，
  首个确认不会因会话 id 推导失败而永久卡死。
- **失败结果信封**：失败工具结果若带结构化 `content`（例如 `browser_meta`），
  agent 序列化为 `{"success": false, "error": ..., "content": {...}}`；模型与
  持久化的 `tool_calls[].result` 都能读到 `content.browser_meta`。

## 工具清单与参数

10 个工具注册在 `backend/domain/tool_names.py` 的 `BROWSER_TOOLS`，由 `browser_tool.py` 提供实现。

| 工具 | 风险类 | 主要参数 | 说明 |
|---|---|---|---|
| `browser_launch` | EXEC | `headless`(默认 true)、`persistent`(默认 false)、`profile_name`(默认 default) | 启动独立 Chrome/Edge 实例；`headless=false` 为可见窗口。注意：即使设置了「默认可见」，本工具自身默认仍是无头——`default_visible` 只影响 `browser_navigate` 的自动拉起 |
| `browser_navigate` | EXTERNAL | `url`(必填)、`browser_id`、`new_tab`、`wait_for` | 打开 URL 并等待就绪（含 SPA 稳定）。**不含** back/forward/reload 参数（前进/后退/刷新由右栏面板手动工具栏提供） |
| `browser_snapshot` | READ | `mode`(interactive/text/full)、`max_nodes`(默认 120，钳位 1-500)、`query`、`include_offscreen`、`browser_id` | 观察主入口。interactive 返回可交互元素（ref/role/名称/状态）；text 只返回正文（上限 30KiB）；full 两者都返回 |
| `browser_interact` | WRITE_LOCAL | `action`(必填，9 种)、`ref`、`selector`、`text`、`value`、`path`、`key`、`clear`、`browser_id` | 定位优先级 `ref > selector > text`。action：click / type / press / scroll / select / hover / check / uncheck / upload。press 支持组合键；upload 仅限工作区内文件且目标必须是 `input[type=file]` |
| `browser_screenshot` | READ | `path`、`return_image`(默认 false)、`full_page`(默认 false)、`browser_id` | PNG 存工作区；`return_image=true` 附带 ≤1.5MB / 宽 ≤1568px 的 data URL 供视觉模型 |
| `browser_close` | WRITE_LOCAL | `browser_id`、`target_id` | 只传 `target_id` 关单个标签页；否则关闭实例并清理临时目录（受控工具门禁对 close 豁免，保证用户接管时仍能收尾） |
| `browser_tabs` | WRITE_LOCAL | `action`(list/create/switch/close)、`url`、`tab_id`、`index`(1-based)、`browser_id` | create/switch 后活动标签页改变，后续工具作用于活动页；create 在创建前走站点门禁 |
| `browser_downloads` | READ | `browser_id`、`wait_for_complete`、`timeout`(默认 60s) | 查看下载：url/文件名/状态/字节数/最终路径；路径可直接交给 `read_file` / office 工具 |
| `browser_cookies` | WRITE_LOCAL | `action`(export/list/delete/set_header)、`domain`、`header_name`、`header_value`、`ttl_seconds`、`browser_id` | 导出登录态到加密凭据档案，供 `web_fetch` / `http_download` 以 `credential_domain` 引用；`set_header` 保存头部型凭据，值不回显 |
| `browser_login` | EXTERNAL | `url`(必填)、`timeout_seconds`(默认 300) | 打开**可见**窗口让用户手动登录，完成后自动保存 cookie 到加密档案；仅应用站点策略的 block 部分 |

### 观察层 v2 细节

- 快照元素输出字段：`ref`、`role`、`name`、`tag`、`value/state`（如 checked、disabled）、
  `placeholder` 等；`elements_total` 与 `truncated` 反映是否被截断。
- ref 协议：页面侧注入 `window.__SAGE_REFS__`（ref → 元素）与 `window.__SAGE_REF_NAMES__`
  （ref → 可访问名）。执行前校验引用仍 `isConnected` 且 `data-sage-ref-name` 与快照时一致；
  页面变化导致旧 ref 失效时返回 `ref 已失效（页面已变化），请先调用 browser_snapshot 重新观察`。
- 文本上限 30KiB；默认节点 120，硬上限 500。
- **Canvas 提示**：可交互元素少于 3 个且正文少于 200 字符时，在快照结果里提示「页面可能是
  Canvas/图片渲染，考虑截图 + 视觉模型」。
- 组合键解析支持 Control/Ctrl、Shift、Alt/Option、Meta/Cmd/Command/Win/Super。
- **iframe 遍历（v2.1 → v2.2 CDP 全帧巡检）**：snapshot 现在同时启用两条路径：
  - **CDP 主路径（v2.2）**：`Page.getFrameTree` 枚举所有 frame（含跨域 iframe、
    frameset `<frame>`、多层嵌套），对每个子 frame 通过
    `Page.createIsolatedWorld(frameId, "sage_snapshot")` 建隔离世界，再用
    `Runtime.evaluate(contextId)` 执行同一套采集 JS。子 frame 的 URL 过
    `browser_safety.check_site` 站点策略——`confirm`/`block` 一律不读内容，
    在快照里标注 `state: needs_confirmation` 或 `state: blocked`；
    读取/交互失败标注 `state: error`。每个子 frame 最多 150 个候选
    （`IFRAME_MAX_COLLECT_PER_FRAME`），一次最多 20 个 frame（`MAX_FRAMES`）。
    每个来自子 frame 的元素都带 `frame_url` 字段标注来源；快照输出新增
    `frames: [{frame_id, url, name, state, elements, text_len}]` 元数据，
    以及 `frameset_count` / `iframes_scanned` / `iframes_truncated` 诊断字段。
  - **JS 回退路径**：当 CDP frame API 不可用时（外部浏览器扩展桥异常等），回退
    到原 `iframe.contentDocument` 遍历同源 iframe；其余路径与 CDP 一致。
  - **ref 协议**：主 frame 仍走 `window.__SAGE_REFS__`；子 frame 元素统一用
    DOM 属性 `data-sage-ref` / `data-sage-ref-name` 跨世界定位——`build_frame_ref_expression`
    与 `build_frame_target_expression` 封装此路径。跨 frame 交互前先过站点策略
    （`_site_access_gate`），敏感动作分类走 `_read_target_metadata` 的 frame 分支。
  - **就绪等待**：`browser_interact click` 后的等待改为 `_wait_after_click`：若
    frame tree 包含子 frame，调用 `browser_frames.wait_frames_settled`（每 0.3s
    轮询所有 frame 的 readyState + 文本长度稳定度），否则沿用顶层网络空闲等待。
  - **安全判定（来源优先 + TOCTOU 防护）**：子 frame 是否可读/可交互按**真实来源**
    判定——优先用采集时 `location.origin`、其次 CDP `securityOrigin`，再退回
    `location.href` / frame tree `url`；`about:blank`/`srcdoc`/`data:`/空 URL 等
    originless frame 继承最近有 host 的祖先 frame 的判定，无法确定来源或 scheme
    不在 `{http, https, about, data, blob}` 白名单时 fail-closed（block）。读取后
    用 payload 自带的采集时刻 `url/origin` **再判一次**，检查后发生自导航到被禁
    站点则丢弃内容。子 frame 交互前在隔离世界读取当前 `location` 再过
    `_site_access_gate(tool="browser_interact")`，无可靠来源直接拒绝；敏感动作
    审批指纹额外绑定 `frame_id` + policy URL，防止跨 frame 重放批准。
  - **隔离世界生命周期**：`wait_frames_settled` 开始时为子 frame 建世界并复用，
    结束后 `Page.removeIsolatedWorld` 回收；探活只覆盖站点策略 allow 的 frame，
    连续两次探活失败的 frame 不再重试。
  - **去重与截断**：CDP 逐帧巡检时主/子 frame 的快照 JS 都关闭页面内 iframe
    遍历（text 模式同样尊重 `include_iframes`），避免同源正文重复；返回节点数
    超过 `max_nodes` 时**子 frame 元素优先保留**，避免检索结果被主框架导航元素
    挤出窗口。每次采集先清理文档内上一代 `data-sage-ref` 属性，防止同一 ref 号
    指向多个元素。
  - 快照输出里 `frames` 中未授权/读取失败的 frame 还会在 hint 中提示用户到
    设置→网络→浏览器站点策略中放行。
- **网络空闲等待（AJAX 适配）**：`web_render.py` 在每次 `Page.navigate` 前通过
  `Page.addScriptToEvaluateOnNewDocument` 注入 XHR/fetch monkey-patch 计数器
  （`window.__SAGE_ACTIVE_REQUESTS__`），`wait_page_ready` 在 readyState 达标后额外等待
  活跃请求归零（连续 2 轮 0，上限 8 秒，轮询间隔 0.3 秒）。`browser_navigate`（含 `new_tab`
  两条路径）同样在导航前注入；`browser_interact click` 成功后追加最多 5 秒网络空闲等待，
  避免 SPA 内容更新前 AI 提前 snapshot。

### 视觉兜底（M5）

- `browser_screenshot(return_image=true)` 触发 `data:image/...` → `attach_image_to_next_turn=true`。
- Agent 循环每轮清理临时载荷；存在视觉能力时注入一条**临时** user 消息（文本 + `image_url`），
  无视觉能力时调用本地 OCR 提取文本（上限 8000 字符）注入，再不行给出可操作提示。
- 临时消息**从不持久化**到会话历史；工具结果本身只保留路径等轻量字段，避免顶层截断丢失图像。

## 安全模型

### 1. 站点策略与授权

| 层级 | 存储 | 语义 |
|---|---|---|
| 持久站点策略 | 设置键 `browser_site_policies`（JSON 对象） | `allow` 直接放行；`block` 直接拒绝并返回 `site_blocked: …` |
| 会话级授权 | 进程内会话授权表（`browser_safety._SESSION_GRANTS`，与确认注册表独立） | 用户在选择「仅本次会话 / 始终允许 / 拒绝」后生效；`always` 同时写入持久策略 |
| 默认 | 无记录 | 首次访问新站点要求用户确认（`needs_confirmation:`） |

域名归一化（小写、去首尾点、取 host）；优先级：持久 block > 持久 allow > 会话授权 > 需确认。
无主机名的协议（`about:` / `data:`）不走站点策略。

### 2. 敏感动作分级

执行前读取目标元素元数据（tag/role/name/type/placeholder，避免读正文 innerText）。元数据不可用
时按失败即关闭（fail-closed）处理，进入确认而非放行。

| 判定 | 触发 | 行为 |
|---|---|---|
| 硬阻断 | `password_entry`、`sensitive_credential`、`payment`、`account_creation`、`account_deletion` | 直接返回 `hard_blocked: …`，提示用户自行接管完成（如 `browser_login` 或面板接管），AI 不可代劳 |
| 需确认 | `file_upload`、`sensitive_submit`、`destructive_click`、`safety_unknown`（元数据不可用） | 生成待确认项并暂停控制，返回 `needs_confirmation: <id> …` |
| 放行 | 其余操作 | 正常执行并写审计 |

`press` 的 Enter/Return 与 click 同口径分类（回车可能触发表单提交）。

### 3. 确认注册表（一次性指纹）

- 待确认 TTL 600s，批准后可复用窗口 120s，拒绝备忘 300s。
- 每条确认绑定
  `sha256(tool|action|domain|ref 或 selector|target_name|session_id|scope)` 的指纹：
  - `session_id` 把批准/拒绝绑定到具体浏览器会话（跨会话不可复用）；
  - `scope` 承载动作参数：`upload` 为解析后的文件绝对路径，`select` 为目标值，
    因此「批准上传 A 文件」不能被重放为上传 B 文件；
  - 定位参数为 ref / selector 二选一。
- `consume_approval(fingerprint, session_id)` / `is_denied(fingerprint, session_id)`
  在批准/拒绝窗口内**一次性**消费，并二次校验指纹所属会话；同样的动作第二次仍需
  再次确认。
- 前端通过 `POST /api/v1/browser/confirmations/{id}` 提交决定；`approve` 后仅当
  会话处于 `paused` 才恢复为 `agent`（迟到的裁决不会夺回 `user_takeover`），
  被阻塞的工具在下一轮重试时可消费批准并执行（审计 `approval=approved`）。
- 确认项公开字段不含指纹：`id / session_id / kind / code / domain / description /
  options / screenshot_path / thumbnail_data_url / thumbnail_unavailable / created_at`。
  截图位于数据目录（不在 `sage-file://` 白名单内），因此后端把截图压成 ≤100KB 的
  内联 data URL（Pillow 可用时降采样到最长边 320px，PNG→JPEG 质量阶梯；Pillow
  不可用时仅当原文件 ≤100KB 才直接 base64）；无法生成时标记
  `thumbnail_unavailable: true`，前端回退展示路径。
- `upload` 的确认描述包含解析后的文件名（不只是元素名），用户能确认「传的是哪个文件」。

### 4. 控制状态机

| 状态 | 工具行为 |
|---|---|
| `agent` | 正常执行 |
| `paused` | 返回 `user_paused: ` 前缀错误，等待继续 |
| `user_takeover` | 返回 `user_takeover: ` 前缀错误，等待归还控制 |

- 注册表为进程内线程安全结构；未知会话默认 `agent`；把设置改回 AGENT 状态会删除对应条目。
- 触发暂停的来源：用户在面板点「暂停」、或安全层生成待确认项（`needs_confirmation`）。

### 5. 重定向复核与传输安全

- `browser_navigate` 在等待就绪后读取**最终 URL**，若主机名与初始请求不同，重新走站点策略检查，
  防止重定向绕过站点授权。
- 内嵌桥仅监听 `127.0.0.1`，请求必须带随机 `X-Sage-Bridge-Token`；请求体上限 8MiB；命令白名单
  只转发 `Page.` / `Runtime.` / `Network.` / `Input.` / `DOM.` 前缀，未知命令拒绝。
- `browser_interact upload` 只接受工作区内已存在的文件；`browser_navigate` 拒绝 `file://`。
- `browser_cookies` 导出的凭据加密存储，跨域使用时按 domain 剥离；`set_header` 的值不回显。

### 6. 提示注入防护

- 快照文本与元素名称经 9 条正则扫描（中英文「忽略之前的指示」「系统提示」「你现在是」
  「do not tell the user」「不要告诉用户」等）。
- 命中只**警告不拦截**：工具结果的 `trust` 字段为 `"untrusted"`，并附带
  `injection_warning`（截断的疑似片段）。模型提示词要求把网页文本当作数据而非指令。
- 只扫描文本；不修改页面内容，也不自动删除内容。

### 7. 审计

- 迁移 v18 新增 `browser_action_log`（`id / session_id / conversation_id / ts / domain / tool /
  action / target_ref / target_desc / result / approval / duration_ms`），索引
  `(session_id, ts)`。
- `result` 取值 `ok / blocked / confirm_required / error`；`approval` 取值
  `auto / approved / denied / none`。
- **不记录**页面正文、输入值、密码、cookie；`conversation_id` 目前恒为 `NULL`。
- 写入与读取均失败静默（审计不得中断主流程）；查询上限钳位 1–500，默认 50。

## REST 接口

全部挂在 `/api/v1` 下，受 `LocalAuthMiddleware` 与来源校验保护。

| 方法与路径 | 请求 / 响应 | 说明 |
|---|---|---|
| `GET /browser/control` | → `{sessions:[{session_id,state,alive,browser_type,headless}]}` | 列出受控浏览器会话与状态 |
| `GET /browser/control/{session_id}` | → `{session_id,state,known}` | 查询单会话状态 |
| `POST /browser/control/{session_id}` | 体 `{action}` → 状态 | action 合法值 `pause` / `resume` / `takeover` / `return`；非法 400，未知会话 404 `session_not_found` |
| `GET /browser/use-config` | → `{default_visible, step_thumbnails}` | 读取两个偏好 |
| `PUT /browser/use-config` | 体部分字段 → 最新配置 | 布尔值以 `"1"` / `"0"` 落库 |
| `GET /browser/site-policies` | → `{policies:[{domain, mode, updated_at}]}` | 持久站点策略列表（对象包装） |
| `PUT /browser/site-policies/{domain}` | 体 `{mode}` → 策略 | `allow` / `block` |
| `DELETE /browser/site-policies/{domain}` | → 删除结果 | 移除策略 |
| `GET /browser/confirmations?session_id=` | → 待确认项列表 | 面板 2 秒轮询；公开字段不含指纹 |
| `POST /browser/confirmations/{confirmation_id}` | 体 `{decision}` → 结果 | `session` / `always` / `approve` / `deny`；按确认类型校验可选项；批准后控制状态回 `agent`，站点类 `session`/`always` 同时授予站点访问 |
| `GET /browser/audit?session_id=&limit=50` | → 审计行 | 面板「操作审计」懒加载 |

渲染层客户端封装在 `src/shared/api/browserControlClient.ts`。窗口「定位」不经过后端，走 Electron IPC
`sage:invoke` 的 `agent_browser_focus`，由 `agentBrowserBridge.focus(session)` 只在**可见**目标表中查找
并 `show()+focus()`；无头会话返回 `false`，面板提示「当前会话为无头模式，无法定位窗口」。

## 设置项

设置页位置：**设置 → 网络 → 浏览器使用**（`src/pages/settings/BrowserUseSection.tsx`）。

| 键 | 类型 | 默认 | 语义 |
|---|---|---|---|
| `browser_use_default_visible` | 布尔 | 开 | 自动拉起浏览器时是否可见。后端只在字面值 `"0"` 时判为无头；缺失或异常按可见处理。注意它只影响 `browser_navigate` 自动拉起，`browser_launch` 自身默认仍 `headless=true` |
| `browser_step_thumbnails` | 布尔 | 开 | 是否逐步截取缩略图。`0/false/off/no` 视为关闭，其余开启；缩略图失败静默 |
| `browser_site_policies` | JSON 对象 | `{}` | 持久站点策略表：域名 → `{mode, updated_at}`；缺失时为 `{}` |

前端读取时沿用「仅显式 `false` 才算关闭」的归一化（`normalizeConfig`），与后端缺省按开启一致。
右栏面板的「自动打开」开关是渲染层本地偏好（`localStorage` 键 `sage.browser-panel-auto-open`），
**不是**后端设置键。

## Win7 兼容

- **纯 CDP**：不依赖 Playwright/Node 驱动；后端只发 JSON 命令，不引入重量级浏览器包，Python 3.8 环境
  可直接运行（避免 PEP 604/585 新语法）。
- **Electron 21.4.4 + Chromium 106**：该版本没有 `Target.createTarget`，因此内嵌桥自行维护
  headless/visible 两套目标注册表；`Target.activateTarget` 不可用，活动标签页以
  `session.active_target_id` 模拟，缺省回退到第一个页面目标。
- **内嵌桥**：桌面端启动时注入 `SAGE_EMBEDDED_BROWSER=1` + 端口 + 令牌，后端 `browser_cdp.py` 据此
  走 HTTP `/command` 与 `WS /devtools/browser/embedded?token=`；命令白名单包含 `DOM.` 前缀。
- **不转发 JS 对话框事件**：`Page.javascriptDialogOpening` 未桥接，弹窗类页面需用户接管处理。
- **截图**：内嵌桥用 `Page.captureScreenshot` / `capturePage` 实现，不依赖外部驱动。
- 功能对齐 main 分支时可整体 cherry-pick；本分支只包含 py38 可直接运行的实现。

## 会话配置（2026-11-20）

设置页位置：**设置 → 网络 → 浏览器**（`src/pages/settings/BrowserSettingsSection.tsx`），位于「浏览器选择」下方。

| 键 | 类型 | 范围 | 默认 | 语义 |
|---|---|---|---|---|
| `browser.maxSessions` | 整数 | `[2, 8]` | 4 | 最大并发浏览器实例数。硬边界由后端钳制，超出范围的值会被夹到最近边界 |
| `browser.lruEvict` | 布尔 | — | 关闭 | 达到上限时是否自动关闭最久未使用的实例。跳过 `BrowserType.EMBEDDED` 与保留渲染池（`RESERVED_BROWSER_ID` 前缀） |

**相关 API**：

| 端点 | 用途 |
|---|---|
| `GET /api/v1/browser/status` | 返回 `{active, max, lruEvict, sessions: [{id, name, browser_type, last_used_at}, ...]}`。`sessions` 过滤掉保留渲染池 |
| `PATCH /api/v1/browser/{id}` | 重命名会话；`body = {name: str}` |
| `GET /api/v1/browser/config` / `PATCH /api/v1/browser/config` | 读取 / 写入 `browser_config` JSON 字段（含 `maxSessions` / `lruEvict`） |

**标题栏状态组件**：`src/features/browser/BrowserSessionStatus.tsx`。5 秒轮询 `/browser/status`，
显示 `活跃/上限`；无实例时隐藏。点击展开面板，可重命名实例或把实例绑定到当前会话
（`rememberBrowserSession(conversationId, browserId)` → `useBrowserSessionStore`）。

**LRU 回收**：`BrowserSessionManager.require()` 每次被工具调用时调用 `session.touch()` 更新
`last_used_at`；`register()` 在超限时按 `last_used_at` 升序选择最久未用者关闭。跳过保留池槽位。

## 已知限制

| 限制 | 现状 / 影响 |
|---|---|
| 无前进/后退/刷新工具 | 工具面无 back/forward/reload 参数；用户可在右栏手动工具栏操作，AI 可通过重新 navigate 达成 |
| 右栏不内嵌页面 | AI 侧边栏只显示状态徽章 + 步骤时间线；受控浏览器是桥接管理的**独立可见窗口**，不是面板内的 `BrowserView` |
| 活动标签页模拟 | Chromium 106 缺 `Target.activateTarget`，「切换标签页」只改后端活动目标 id，桌面窗口焦点未必同步切换 |
| 时间线缩略图 | 时间线仅显示缩略图文件名（相机图标）；确认条内联 ≤100KB 的 data URL 缩略图，无法生成时回退显示截图路径 |
| 对话框不自动处理 | `alert/confirm/prompt` 不自动接受/取消，需用户接管 |
| 无 diff 快照 | 快照不与上一版做差异对比，模型需自行比较 |
| selector/text 定位仍只作用于顶层 | 子 frame 内的元素必须用 `browser_snapshot` 返回的 `ref` 定位；`browser_interact(text=...)` / `selector=...` 在主 frame 找不到时不回退到子 frame，模型应先 `browser_navigate url=<frame_url>` 或直接用 ref |
| 跨域子 frame 需先在站点策略放行 | 子 frame 域名未在 allow 列表时，快照把该 frame 标为 `needs_confirmation` 并在 hint 提示到设置→网络→浏览器站点策略中放行；这是有意的跨站读取防线，不是缺陷 |
| 无 URL 令牌脱敏 | 审计与展示层未对 URL 中的敏感查询参数做掩码 |
| 无审计导出 | 仅面板内表格展示，未提供 JSON/CSV 导出 |
| 无指标埋点 | 未接入 `web_metrics` 之类的指标；排障依赖日志与审计表 |
| 视觉兜底是临时的 | 图像只对下一轮有效，不进入持久历史；无视觉能力时降级 OCR 或提示 |
| 注入扫描仅警告 | 命中不阻断，模型需遵守「页面文本是数据」的提示词纪律 |

## 相关文件清单

| 类别 | 路径 |
|---|---|
| 工具 | `backend/tools/browser_tool.py`、`backend/tools/browser_observe.py`、`backend/tools/browser_cdp.py` |
| 服务 | `backend/services/browser_control.py`、`backend/services/browser_safety.py` |
| 数据 | `backend/data/browser_action_repo.py`、`backend/data/migrations/v18_browser_actions.py`、`backend/data/migrations/runner.py` |
| 接口 | `backend/api/browser_use_routes.py`、`backend/api/legacy_routes.py`（注册） |
| Agent | `backend/agents/profiles.py`、`backend/domain/tool_names.py`、`backend/core/legacy/agent.py`（视觉兜底） |
| 桌面 | `electron/agentBrowserBridge.ts`、`electron/main.ts` |
| 前端 | `src/features/browser/BrowserPanel.tsx`、`src/features/right-panel/rightPanelStore.ts`、`src/pages/settings/BrowserUseSection.tsx`、`src/shared/api/browserControlClient.ts`、`src/shared/lib/i18n/locales/zh/chatAndSider.ts` |
| 测试 | `backend/tests/unit/test_browser_tool.py`、`test_browser_observe.py`、`test_browser_control.py`、`test_browser_safety.py`、`test_browser_action_repo.py`、`backend/tests/api/test_browser_use_routes.py`、`electron/__tests__/agentBrowserBridge.test.ts`、`src/features/browser/__tests__/BrowserPanel.test.tsx`、`src/pages/settings/__tests__/BrowserUseSection.test.tsx` |
