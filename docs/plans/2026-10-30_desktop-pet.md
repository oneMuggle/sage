# Sage 桌面宠物（Sage Pet）方案

> 日期：2026-10-30
> 状态：P0 + P1 状态面板 + P2 互动/提示音 + 应用内形态 + Task Center 聚合 + 自定义动画包 + 多宠物已实施（2026-10-31），技术文档见 `docs/technical/117-desktop-pet.md`
> 参考：DeepSeek Harness（DSH）「大肥鱼」桌宠生态、豆包系 AI 桌宠、vscode-pets / BongoCat 等开源实现

---

## 1. 背景与目标

### 1.1 为什么做

Sage 是一个桌面 Agent 应用，但 Agent 在后台跑长任务时，用户切换到浏览器/编辑器后只能靠侧栏徽章或系统通知感知进度。桌宠把「Agent 的工作状态」变成一个一直在场的实体：

- **状态可见**：思考、调工具、等审批、重试、完成、出错，不用切回 Sage。
- **情感连接**：把冰冷的流式状态变成有性格的反馈，提升留存与好感。
- **快速回流**：点一下宠物直接回到对应会话 / 审批弹窗。

### 1.2 参考产品给我们的三条结论

| 结论                                                          | 证据                                                                                                                                  |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| 桌宠的核心价值是「真实状态 + 陪伴感」，不是另起一个聊天机器人 | `dsh-dafeiyu`（周下载 3.9 万）明确「不读屏幕、不发起模型调用」，只把 DSH 会话事件映射成动作；`dsh-stamina-pet` 把上下文用量做成体力条 |
| 透明置顶窗 + 帧动画是当前最成熟的技术路线                     | `dsh-pet`（3.7k stars）用 Electron 透明置顶窗 + VP9-alpha 动画；BongoCat 用 Tauri + Live2D；豆包 PetAgent 用 Electron + Live2D        |
| 过度主动、读屏、虚假进度会迅速变成负体验                      | 多个项目专门提供「减少动态 / 安静模式 / 免打扰」；`dsh-dafeiyu` 明示「推理强度与进度只显示上游真实提供的信息」                        |

### 1.3 目标与非目标

**P0 目标**

- 一个可开关的桌面宠物窗：透明、无边框、置顶、可拖动、窗口透明区域点击穿透。
- 跟随 Sage Agent 的真实状态切换 8 类动作 + 状态气泡。
- 宠物右键菜单与设置页入口；系统托盘可显示/隐藏。
- Win7 / Linux / macOS 有明确降级路径。

**非目标（至少 P0 不做）**

- 不读取屏幕、不截屏、不做 OCR。
- 不为了桌宠额外调用 LLM（聊天/语音放到 P2，且走 Sage 已有 Agent）。
- 不做天气、系统监控、喂食经济等与 Agent 无关的功能。
- 默认不把「大肥鱼」作为 Sage 的品牌形象；可复用 MIT 素材作为**可选素材包**（授权与取舍见 §4.9）。

---

## 2. 产品设计

### 2.1 形态

| 形态                   | 说明                                                         | 适用                                         |
| ---------------------- | ------------------------------------------------------------ | -------------------------------------------- |
| **独立桌面窗（主）**   | 透明置顶小窗，浮在其他应用之上；宠物本体可点击，透明区域穿透 | Win10+ / macOS / Linux（有合成器）           |
| **应用内角落（降级）** | 挂在主窗口右下角的轻量角色，不占独立窗口                     | Win7 无 Aero、远程桌面、VM、用户不想开桌面窗 |
| **关闭**               | 设置/托盘一键关闭                                            | 所有平台                                     |

三种形态共用同一套状态机、动作定义与素材包；应用内形态只是渲染宿主不同。

### 2.2 状态 → 动作映射（P0）

Sage 现有 `AgentState`（13 态，`backend/core/legacy/agent_state.py`）与工具事件映射为宠物语义：

| 宠物动作        | 触发来源                                                             | 优先级 | 说明                                              |
| --------------- | -------------------------------------------------------------------- | ------ | ------------------------------------------------- |
| `waiting`       | `permission_request` / `ask_user_question` / `awaiting_step_confirm` | 最高   | 举手/看屏幕；气泡「有个操作等你确认」；提示音可选 |
| `error`         | `failed`、工具 `is_error`                                            | 高     | 播放一遍 + 气泡 8s                                |
| `done`          | `done`                                                               | 高     | 播一遍庆祝 + 气泡 6s                              |
| `acting:bash`   | 工具名 `bash` / `run_command` / 终端类                               | 中     | 「敲命令」                                        |
| `acting:edit`   | `edit` / `write` / `apply_patch`                                     | 中     | 「改代码」                                        |
| `acting:read`   | `read` / `grep` / `glob` / 文件检索                                  | 中     | 「翻文件」                                        |
| `acting:web`    | `web_search` / `web_fetch` / 浏览器类                                | 中     | 「上网查」                                        |
| `acting:mcp`    | `mcp__*` 及其它外接工具                                              | 中     | 「用外部工具」                                    |
| `acting:office` | `office_*` / 文档类                                                  | 中     | 「写文档」                                        |
| `retry`         | `retry`（自动重试）                                                  | 中低   | 「再试一次…」                                     |
| `thinking`      | `thinking` / `reasoning` / `content_delta`                           | 低     | 常驻循环                                          |
| `observing`     | `observing` / `step_done`                                            | 低     | 短暂                                              |
| `idle`          | 无活跃流                                                             | 最低   | 待机动作链；静默超 2 分钟转 `sleeping`            |
| `sleeping`      | 空闲超时                                                             | 最低   | 打盹                                              |

**规则**

- 同一时刻只显示一个动作；高优先级打断低优先级，装饰动作播完自动回落到当前状态。
- `done` / `error` 是瞬态：播完 6–8 秒后回落到 `idle`，新任务可立即打断。
- 多会话并发时默认显示「最紧急的会话」（优先级最高者）；设置里可切换为「指定会话」。
- **进度只显示真实数据**：有待办/步骤就显示，没有就显示阶段名，不伪造百分比。

### 2.3 交互

| 交互            | 行为                                                                                              |
| --------------- | ------------------------------------------------------------------------------------------------- |
| 单击宠物        | 唤起 Sage 主窗口并跳到当前活跃会话；若在等审批，直接聚焦审批弹窗                                  |
| 右键宠物        | 原生菜单：大小（5 档）、安静/标准/活泼、减少动态、气泡开关、回到初始位置、打开设置、本次隐藏/关闭 |
| 拖拽            | 按住拖动，位置记忆；松手后吸附到屏幕工作区内；跨显示器可用                                        |
| 摸头 / 戳（P1） | 0.55s 长按摸头，连戳 5 下生气（参考 `dsh-stamina-pet`）                                           |
| 双击（P2）      | 打开宠物面板（心情、陪伴天数、上下文用量）                                                        |

### 2.4 气泡与提示音

- 气泡文案全部来自**模板**（动作名、工具类别、会话标题可选），不显示命令参数、文件路径、消息正文。
- 默认气泡模式：只在 `waiting` / `error` / `done` 时出现；可设为常驻/隐藏。
- 提示音场景独立开关：对话完成、工具出错、等待审批；默认只开「等待审批」。
- 遵守系统免打扰 / Sage 的安静模式。

### 2.5 上下文体力条（P1，参考 dsh-stamina-pet）

- 在宠物脚下/头顶显示一个细条，表示当前会话上下文窗口已用比例。
- 数据来自现有会话 token 用量与窗口上限；**不引入「注意力塌缩」等未经验证的指标**。
- 阈值/颜色可配；满时提示「该压缩上下文了」，并链接到 Sage 的压缩操作。

---

## 3. 参考实现拆解

### 3.1 DSH 生态

| 项目                          | 技术路线                                                                                                                                 | 可借鉴                                                                                                                 | 不照搬                                                   |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| `dsh-dafeiyu`（39k 周下载）   | 插件启动原生 Helper（Windows/Qt/Swift）渲染透明窗；16 组动作、3,444 帧、24fps 透明 WebP，412×344 画布                                    | 状态来自会话事件、不读屏幕；空闲节奏三档（45–90 / 25–45 / 12–22s）；拖拽/摸头/戳身体；点击穿透与多屏拖动；设置实时生效 | 不引入第二套原生运行时——Sage 本身就是 Electron           |
| `dsh-pet`（3.7k stars）       | Web overlay + 桌面 Electron helper；VP9-alpha WebM；动画链与权重；双缓冲交叉淡入；拖拽物理；pet pack；六档工作状态；HTTP/Cordis 对外接口 | 动画链/权重/无缝切换；pet pack 扩展；对外 API；多宠物；减少动态                                                        | 不下载 Electron 运行时（Sage 已有）；不做浏览器/桌面双头 |
| `dsh-stamina-pet`             | 每会话一只；上下文体力条；手写 canvas Live2D 渲染器；60ms 轮询光标决定是否穿透                                                           | 体力条产品化；鼠标穿透的轮询兜底；表情/睡眠档位                                                                        | 不内置 Live2D（许可与体积），不做「传承/临终」重功能     |
| `mdd111/deepseek-dafeiyu-pet` | Python/PySide6 桌宠；读本地会话日志 zstd 增量映射 11 动作                                                                                | 工具→动作的映射表；增量读取性能优化；隐私说明写法                                                                      | 不读会话日志正文——Sage 有结构化事件流，无需读日志        |

### 3.2 主流 AI 应用 / 通用开源

- **豆包系 PetAgent / PetAI-Desktop-Pet**：透明悬浮窗 + Live2D + 豆包对话 + 系统监测 + 用量统计；支持 macOS / Windows / Android。说明「陪伴 + 轻工具」是主流组合，但 Sage 的差异化应放在 Agent 状态联动，而不是系统监控。
- **BongoCat（Tauri + Rust + PixiJS Live2D）**：输入驱动（键盘/鼠标/手柄）→ Live2D 参数；安装包 <20MB、内存 <50MB。说明输入/事件驱动的状态机是低成本高反馈的路线。
- **vscode-pets（MIT）**：Webview + Canvas，每个宠物一个有限状态机（idle/sit/walk/run/chase），24 种像素宠物、球互动、导入导出。说明「简单帧动画 + 状态机 + 收集/换装」足以支撑长期可玩性。
- **硬件桌宠（piyta / AI 水晶球）**：情绪识别、TTS、主动安慰。提醒我们「主动互动」必须有边界感（专注模式、触发频率上限）。

### 3.3 对我们最有价值的三条工程经验

1. **状态必须来自真实事件**，且要有优先级与瞬态衰减，否则宠物会「乱演」。
2. **透明窗的点击穿透是最大坑**：Electron 的 `setIgnoreMouseEvents(true, { forward: true })` 是标准解，但 Win7/VM 下有兼容问题；需要主进程光标轮询兜底与「兼容模式」。
3. **素材管线决定迭代速度**：帧序列 + manifest + 可导入 pet pack，比把动画写死在代码里可持续得多。

---

## 4. 技术方案

### 4.1 总体架构

```
┌────────────────────────── Electron 主进程 ──────────────────────────┐
│                                                                      │
│  backendLauncher (已有) ── HTTP/NDJSON ──► FastAPI                   │
│        ▲                                                             │
│        │ 轮询 /chat/stream/active + attach NDJSON                    │
│  petController.ts ──► petState.ts（纯函数归并）──► PetSnapshot        │
│        │                                                             │
│        ├── petWindow.ts（透明置顶窗生命周期/位置/穿透）                │
│        └── webContents.send('pet:state', snapshot)                   │
│                                                                      │
│  petIpc.ts（白名单：drag / open-session / context-menu / config）     │
└──────────────────────────────┬───────────────────────────────────────┘
                               │ 窄 preload（contextBridge）
┌──────────────────────────────▼───────────────────────────────────────┐
│ 宠物渲染器（独立 Vite entry：pet.html + src/pet/）                     │
│  React + Canvas/帧序列；状态机 + 动画控制器 + 交互；不直接访问后端       │
└──────────────────────────────────────────────────────────────────────┘
```

**关键决策：宠物窗口不走 `sage:invoke` / `sage:listen`。**

现有 `isTrustedRenderer()`（`electron/main.ts:907`）只信任主窗口；放宽它会扩大 IPC 攻击面。宠物窗采用：

- 主进程 → 宠物窗：单向 `webContents.send('pet:state' | 'pet:config', …)`；
- 宠物窗 → 主进程：独立的 `pet:*` 白名单通道，主进程校验 `BrowserWindow.fromWebContents(sender) === petWindow`；
- 宠物窗永远不接触后端 token，也不发起任意 HTTP。

### 4.2 状态来源与聚合

| 方案                             | 做法                                                                                                                                                                                          | 取舍                                                                          |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| **A. 主进程自聚合（推荐 P0）**   | `petController` 每 1.5s `GET /api/v1/chat/stream/active`，对新 streamId attach NDJSON（`BroadcastQueue` 支持多订阅者），解析事件喂 `petState` reducer；同时轮询会话 `run_status` 处理后台任务 | 不依赖主窗口 renderer 是否订阅；主窗口最小化/隐藏也工作；新增代码集中在主进程 |
| B. 复用主窗口 relay              | 主窗口把 `chatStreamStore` 变化经 IPC 转给宠物窗                                                                                                                                              | 依赖 renderer 订阅与页面生命周期，耦合高；主窗口未加载时失效                  |
| C. 新增后端 `/api/v1/pet/stream` | 后端新增全局 NDJSON 聚合端点                                                                                                                                                                  | 最干净但引入新契约与测试面；P1 若要做「无主窗口常驻」再上                     |

P0 选 A。`petState.ts` 保持纯函数（事件数组 → 快照），便于单测与回放。

### 4.3 窗口实现要点

- `BrowserWindow`：`transparent: true`, `frame: false`, `alwaysOnTop: true`, `skipTaskbar: true`, `resizable: false`, `hasShadow: false`, `show: false` → `ready-to-show` 再显示，`focusable: false`（Windows 上配合 `WS_EX_NOACTIVATE` 行为）。
- 尺寸：按动作帧画布等比缩放；窗口只包住角色 + 气泡，不铺满屏幕。
- 位置：`app.getPath('userData')/pet-window.json` 持久化；启动时按当前显示器工作区夹取（参考多屏 DPI 变化）。
- 点击穿透：
  - 默认 `setIgnoreMouseEvents(true, { forward: true })`，renderer 收到 mousemove 判断是否进入角色包围盒，进入时 IPC 关闭穿透、离开时恢复；
  - **兜底**：Win7 / VM 下改用主进程 `screen.getCursorScreenPoint()` 60ms 轮询（`dsh-stamina-pet` 同款），避免 forwarded 事件在这些环境不稳定；
  - 兼容模式下不做穿透，窗口本身就是角色大小。
- 拖拽：renderer `pointerdown/move/up` + IPC `setPosition`（避免 `-webkit-app-region: drag` 与穿透切换互相打架）。
- 置顶层级：默认 `floating`；可选 `screen-saver`（全屏应用之上，默认关闭）。

### 4.4 渲染与动画

- 独立 Vite 多页入口：`vite.config.ts` 的 `rollupOptions.input` 增加 `pet: 'pet.html'`；开发态加载 `VITE_DEV_URL/pet.html`，生产态 `loadFile(dist/pet.html)`。
- 不把宠物挂在主应用 `App.tsx` 里做独立窗口：那会连带加载完整 Layout、路由与主 bundle，违背体积预算。
- 动画格式（P0）：**复用 dsh-pet 的 VP9-alpha WebM + 动画链/物理引擎**（MIT，Chromium 106 已验证）；WebM alpha 在目标环境不可用时回落到透明 WebP/PNG 帧序列。24fps 上限；空闲动画播完即停 rAF。
- 具体移植清单、适配层与许可处理见 §4.9。
- 减少动态：`prefers-reduced-motion` + 设置项，命中时只显示静态姿势，状态用气泡表达。

### 4.5 pet pack 格式（P1 开放导入）

```jsonc
{
  "id": "sage-leaf",
  "name": "Sage 小叶灵",
  "version": "1.0.0",
  "license": "CC-BY-4.0",
  "canvas": { "width": 256, "height": 256 },
  "anchor": { "x": 128, "y": 236 },
  "actions": {
    "idle": { "frames": ["frames/idle-0.webp", "..."], "fps": 12, "loop": true },
    "thinking": { "frames": ["..."], "fps": 18, "loop": true },
    "waiting": { "frames": ["..."], "fps": 8, "loop": true },
    "done": { "frames": ["..."], "fps": 24, "loop": false },
    "error": { "frames": ["..."], "fps": 12, "loop": false },
  },
}
```

- 内置包放 `public/pet/<id>/`，随 `dist/` 打包；用户导入包放 `userData/pets/<id>/`。
- 校验：zip 路径穿越、文件类型白名单（webp/png/json）、单包体积上限、manifest schema、帧数/分辨率上限；**不执行包内任何脚本**。
- 缺动作时回落到 `idle`，不报错。

### 4.6 设置项

新增 `pet` 设置 Tab（`agent` 分组），字段：

| 字段                  | 默认                                      | 说明                                  |
| --------------------- | ----------------------------------------- | ------------------------------------- |
| `enabled`             | false（P0 灰度）/ true（正式）            | 总开关                                |
| `displayMode`         | `desktop`                                 | `desktop` / `in-app` / `both` / `off` |
| `size`                | `medium`                                  | 5 档                                  |
| `tempo`               | `standard`                                | quiet / standard / lively             |
| `reduceMotion`        | false                                     | 减少动态                              |
| `bubbleMode`          | `important`                               | important / always / off              |
| `soundScenes`         | `{waiting:true, error:false, done:false}` | 分场景提示音                          |
| `showSessionTitle`    | false                                     | 气泡是否带会话名（隐私）              |
| `compatibilityMode`   | 自动                                      | Win7/VM 下的不透明兜底                |
| `petPack`             | `sage-leaf`                               | 当前素材包                            |
| `followActiveSession` | true                                      | 多会话时跟随最紧急会话                |

**存储决策**：宠物配置与窗口位置放 `userData/pet-config.json`，由主进程单一持有，设置页经 `pet:get-config` / `pet:set-config` 读写。理由：窗口几何天然属于主进程；同时避免把宠物字段塞进 `AppSettings` 触发 `settings_canonicalizer` / `test_settings_schema_parity` / win7 同步的三处改动。代价是不进设置导出/重置，P2 可再并入 `AppSettings`。

设置 Tab 注册仍走单一注册表：

- `src/pages/settings/settingsTabs.tsx`：`SettingsTabKey` 加 `'pet'`，`SETTINGS_TABS` 加条目；
- 中英 i18n（`locales/zh|en/chatAndSider.ts` 或 `settingsAndModels.ts`）；
- `settingsSearchEntries.ts` 加搜索项；
- 守卫测试 `settingsTabs.guards.test.ts` 的 tab 数量 18 → 19。

### 4.7 托盘与入口

- `electron/tray.ts` 菜单增加「显示/隐藏桌面宠物」「宠物设置…」；
- 主窗口命令面板/帮助入口（P1）。

### 4.8 Win7 / 兼容性

| 风险                                       | 对策                                                                                         |
| ------------------------------------------ | -------------------------------------------------------------------------------------------- |
| Win7 无 Aero/DWM 时透明窗不可用            | 启动检测 `os.release()`（Win7 = 6.1）→ 默认 `in-app`；用户可在设置里强制桌面窗（不透明模式） |
| `setIgnoreMouseEvents` 在 Win7/VM 可能卡死 | 兼容模式关闭穿透；非兼容模式用主进程光标轮询兜底，不单靠 forwarded 事件                      |
| Electron 21 / Chromium 106                 | 只用 Electron 21 已有 API；动画格式选 WebP/PNG；避免新语法与重型库                           |
| 硬件加速已全局关闭                         | 帧画布 ≤ 256px、预解码、静态时停 rAF；控制内存                                               |
| 双分支同步                                 | 新代码避开 pydantic/版本差异；仅前端 + 主进程，可整块 cherry-pick 到 `release/win7`          |

### 4.9 复用 / 改造开源项目（推荐路线）

**结论：以 `PC2005-cloud/dsh-pet` 为上游做一次性移植（MIT），把渲染引擎 + 窗口层复制进 Sage 后归 Sage 自有，不建立长期上游追踪。** 这正是「大肥鱼」本体项目，能省掉动画/物理/穿透/多屏这些最费时间的部分；后续只在有明确收益时手动 cherry-pick。

#### 4.9.1 许可核实结果

| 上游                                                                           | 代码许可     | 素材许可                                                                                                             | 结论                                                        |
| ------------------------------------------------------------------------------ | ------------ | -------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| `PC2005-cloud/dsh-pet`                                                         | MIT          | `assets/webm` 随仓库 MIT；`dsh-dafeiyu` 的 `ASSET_LICENSE.md` 明确其素材为 MIT 的 AI 生成动画（豆包生成 + 手工抠像） | ✅ **主复用对象**                                           |
| `QCYTSN/dsh-dafeiyu`                                                           | MIT          | 当前鲸鱼娘素材为 MIT（转自 dsh-pet）；`legacy/dafeiyu/` 旧 BigFish 帧**受限，不可用**                                | ⚠️ 只用当前素材；旧 BigFish 帧禁止                          |
| `theskywilldawn/dsh-stamina-pet`                                               | **AGPL-3.0** | 渲染器来自 AGPL 项目                                                                                                 | 🚫 不复制代码/素材（除非 Sage 愿意转 AGPL）；只借鉴产品思路 |
| `mdd111/deepseek-dafeiyu-pet`                                                  | MIT          | 立绘为社区二创，明确「请勿商用」                                                                                     | ⚠️ 只借鉴工具→动作映射，不复用素材                          |
| `dsh-chatting-pet` / `dsh-zyc` / `dsh-pet-dfeiyu-mo` / `cortico-world-fatfish` | 未逐项核实   | 未逐项核实                                                                                                           | 🚫 未核实前不使用                                           |

**角色 IP 的残余风险**：dsh-pet 的「蓝色大肥鱼」是 AI 生成的角色，上游以 MIT 发布；但形象与 DeepSeek 的鲸鱼吉祥物存在联想，MIT 只能解决上游作者自己的版权，不能替 DeepSeek 授权。建议：

- **默认**：Sage 用原创默认形象；大肥鱼作为**可选素材包**，由用户自行启用。
- **若坚持内置**：先取得 PC2005-cloud 的书面许可，并让法务确认不涉及 DeepSeek 商标/角色权；包内保留 `LICENSE` 与 `NOTICE.md`，不暗示 DeepSeek 官方关系。
- **个人/内部版本**：可直接内置，但仍保留署名与许可文件。

#### 4.9.2 移植清单

**A. 直接移植（纯逻辑/类型，低风险）**

| 上游路径                                                            | 用途                   | 行数（约） |
| ------------------------------------------------------------------- | ---------------------- | ---------- |
| `dsh-pet/src/shared/physics.ts`                                     | 拖拽/碰撞纯函数        | 62         |
| `dsh-pet/src/shared/state.ts`                                       | 宠物状态叶子类型与解析 | 351        |
| `dsh-pet/src/shared/work-status.ts`                                 | 六档工作状态模型       | 小         |
| `dsh-pet/runtime/electron-helper/pointer-target.js`                 | 命中区/穿透判定        | 110        |
| `.../desktop-geometry.js`、`dpi-linearization.js`、`x11-pointer.js` | 多屏/DPI/指针          | 45+58+小   |
| `.../topmost-watchdog.js`、`taskbar-watchdog.js`                    | 置顶/任务栏保持        | 56+43      |
| `.../main/displays.js`                                              | 多显示器几何           | 63         |

**B. 移植 + 适配（渲染引擎）**

| 上游路径                                                                                   | 处理                                                                        |
| ------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------- |
| `src/client/pet/animation/**`                                                              | 动画链、素材加载、cue、媒体播放；直接移植，素材根改为 `file://`/自定义协议  |
| `src/client/pet/motion/**`                                                                 | 拖拽、惯性、飞行、挤压；直接移植                                            |
| `src/client/pet/card/**`                                                                   | 宠物卡状态/交互/睡眠机/点击音效/触感；移植，替换 DSH 菜单与通知             |
| `src/client/pet/multi.ts`                                                                  | 多宠物与配置分发；把 `/state` 长轮询改为 Sage `pet:state` IPC               |
| `src/client/pet/{click-sound,haptics,menu-actions}.ts`                                     | 直接移植                                                                    |
| `src/client/index.ts`、`src/client/app.ts`、`src/client/chat/**`、`src/client/settings/**` | **不复用**：这些是 DSH Cordis 插件/聊天/设置集成，用 Sage 的 IPC 与设置替换 |

**C. 移植 + 改写（主进程窗口层，CommonJS → TS）**

| 上游路径                                                               | 处理                                                                                                |
| ---------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `runtime/electron-helper/main/windows.js`（307 行）                    | 透明窗、整窗穿透镜像、60ms 光标兜底泵、输入忙碌区、多宠物碰撞广播；改写为 `electron/pet/windows.ts` |
| `runtime/electron-helper/main/ipc.js`（206 行）                        | 只保留 `pet:*` 通道并做 sender 校验，改写为 `electron/pet/ipc.ts`                                   |
| `runtime/electron-helper/{preload.js,index.html,renderer.js,sprite/*}` | 作为参考；Sage 用 `pet.html` + React 入口替换                                                       |

**D. Sage 侧新增的适配层**

1. `electron/petState.ts`：把 Sage `AgentState` / 工具名 / `retry` / 权限事件映射为 dsh-pet 的动画名（其六档 `thinking/working/tidying/waiting/success/error` 与 §2.2 基本同构）。
2. `electron/petConfigStore.ts`：`userData/pet-config.json`，单一所有者。
3. `electron/petIpc.ts`：`pet:state` 单向推送 + `pet:*` 白名单动作（open-session / drag / context-menu / config）。
4. `src/pages/settings/PetTab.tsx`：读写宠物配置。
5. React 运行时适配：dsh-pet 用注入的 `h/useState/useEffect/useRef`，Sage 直接映射到真实 React。

#### 4.9.3 素材取舍

- dsh-pet 共 **109 个 WebM、52.7MB**（VP9-alpha）；全量进安装包会突破 `dist/assets` 12MB 预算。
- **默认包**：选 10–12 个动作（idle / thinking / working / waiting / done / error / drag / click / sleep）约 5–8MB。
- **完整包**：其余动作做成可下载/可导入的 `pet-pack`，放 `userData/pets/`，不随安装包分发。
- 旧 BigFish 帧（`dsh-dafeiyu/legacy/dafeiyu/`）**不使用**。

#### 4.9.4 一次性移植与出处管理（不追踪上游）

- 移植目标目录：`src/pet/engine/`（从此为 Sage 自有代码），主进程窗口层放 `electron/pet/`。
- 只保留最低限度的出处信息：`third_party/dsh-pet/NOTICE.md` 记录上游仓库、commit、MIT 许可、移植文件清单与修改说明；不放 `UPSTREAM.json`、不做逐文件哈希。
- 不设季度同步、不做哈希 CI、不预建 patch 登记与自动 diff 脚本（YAGNI）。
- 升级按需：只有上游修了我们会踩的 bug、出现我们想要的新能力、或本地改动多到难以维护时，才手动 `git diff` 对应 commit 后 cherry-pick。
- 架构检查若因移植文件超 800 行告警，在 `architecture-policy` 中为 `src/pet/engine/` 加白名单（一次性配置）。
- 测试护栏优先于上游追踪：适配层映射测试 + 宠物冒烟测试，防止我们自己改坏。

#### 4.9.5 工作量变化

| 项                      | 从零实现      | 复用 dsh-pet              |
| ----------------------- | ------------- | ------------------------- |
| 透明窗/穿透/多屏/看门狗 | 3–4 天        | 1–2 天（改写 500 行左右） |
| 动画链/物理/拖拽/多宠物 | 4–5 天        | 1–2 天（适配状态源）      |
| 素材                    | 需自制或外包  | 已有 109 个 MIT 动画      |
| 许可/署名/法务          | 0             | 1–2 天                    |
| **P0 合计**             | **约 1.5 周** | **约 5–8 天**             |

代价是引入上游代码风格差异，且后续不再自动获得上游更新；按「一次性移植 + 按需 cherry-pick」处理，换取长期零维护负担。

---

## 5. 实施计划

### M0 — 技术验证（2–3 天，先于正式开发）

- [x] Linux Electron 21 冒烟：透明置顶窗创建、`pet.html` 加载、状态推送与动画切换通过（Playwright Electron）。
- [ ] Windows 10/11 实测；Win7 真机（Aero 开/关）实测穿透与性能。
- [x] Electron 21 / Chromium 106 下 VP9-alpha WebM 播放与切换通过（Linux 冒烟）；透明像素真机观感待验收。
- [ ] 验证 `ready-to-show` + 透明窗无白底/黑底闪烁（真机观感）。
- [ ] 验证多屏、DPI 缩放、拖动与位置夹取（几何单测已覆盖，真机待验）。
- [x] 复核 dsh-pet 上游 commit、`LICENSE`/`NOTICE` 与素材清单（`third_party/dsh-pet/`）。
- [x] 结论：保留 60ms 光标轮询兜底；Win7 兼容模式默认自动检测。

### M1 — P0 状态陪伴（约 5–8 天，复用 dsh-pet 引擎）

- [x] 一次性移植 dsh-pet 思路到 `src/pet/engine/`（动画选择、素材清单、内置 pack）+ 适配层。
- [x] 主进程窗口层：`electron/pet/windows.ts`、`electron/pet/ipc.ts`、`controller.ts`、`state.ts`、`config.ts`。
- [x] `pet.html` + `src/pet/PetApp.tsx`（动画切换、拖拽、点击穿透协议、气泡）。
- [x] 主进程状态聚合：`main.ts` 在 `agent_chat_stream` / `sage:listen` 时 `trackStream`，attach NDJSON 并归并。
- [x] 内置素材包：大肥鱼 18 个动作（7.1MB），来源与许可见 `third_party/dsh-pet/NOTICE.md`。
- [x] 设置 Tab（智能体分组）+ 托盘菜单 + 中英文文案 + 搜索索引。
- [x] 单测：状态优先级/衰减、窗口几何、pack 配置、动画选择；设置守卫与搜索索引更新。
- [x] Win7 兼容模式与回退路径代码（真机回归待验收）。

### M2 — P1 陪伴增强（约 1 周）

- [x] 摸头/戳/连戳生气、摸头计数（`pet-profile.json`）。
- [x] 气泡模板：等待/出错带工具名，待办/步骤 n/m，可选会话名；提示音已接线（WebAudio 合成）。
- [x] 上下文用量条（面板；需要 chat `maxContext` + usage 数据）。
- [x] 应用内角落形态（Win7/VM 默认可用；主窗口右下角 InAppPet）。
- [x] 多会话面板（最近/活跃会话列表，最多 5 个）；「每会话一只宠物」未实现。
- [x] pet pack 导入/导出 + 校验（zip + `sage-pet://`；设置页导入/导出/删除）。
- [x] 完整动画包：109 个 WebM 全量内置（约 52.7MB），87 个待机随机池 + 5 个随机点击回应 + tempo 休息间隔。
- [x] 状态面板 + 常驻徽章 + 终态保留 45 秒 + 会话标题/工具/进度/上下文。

### M3 — P2 生态与养成（1–2 周）

- [x] 陪伴天数 + 摸头计数（`pet-profile.json`）；好感度等级未做。
- [x] 多宠物（1–3 只，各自动画包/大小/位置；应用内横向排列，气泡只在第一只）。
- [ ] 对外只读状态 API / 本地 HTTP（供插件联动）。
- [x] 后台任务聚合：Task Center（office/wiki/custom）renderer 上报 + 主进程轮询独立编排 lanes（按 team 聚合）与定时任务近期失败；面板「后台任务」+ 空闲时驱动动作。
- [ ] 素材生成管线：视频/图片序列 → 透明帧 → manifest。
- [ ] 可选聊天/语音（走 Sage 已有 Agent 与 TTS，需单独评审隐私与成本）。

### M4 — P3 探索

- [ ] Live2D 接入（先做许可评估与体积评估）。
- [ ] 桌面漫游/物理抛掷。
- [ ] 屏幕感知（**默认关闭，需显式授权**；不建议 P2 前做）。

---

## 6. 测试与门禁

| 层     | 内容                                                                                                                                                |
| ------ | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| 单元   | `petState` 优先级/瞬态衰减/多会话合并；`petWindow` 位置夹取与显示器选择；pack manifest 校验；配置迁移                                               |
| 组件   | 动作状态机、穿透开关、减少动态、气泡模式                                                                                                            |
| 主进程 | mock BrowserWindow 的窗口生命周期；`pet:*` IPC sender 校验                                                                                          |
| 契约   | 若新增后端路由，更新 `ipc-manifest.json` 与 `test_ipc_manifest_routes.py`；若动设置，更新 canonicalizer 与 parity 测试                              |
| E2E    | Playwright Electron stub：开启宠物 → 窗口创建 → 模拟状态 → 动作切换 → 关闭清理                                                                      |
| 手工   | Win7 真机（Aero 开/关）、多屏、DPI 150%、远程桌面、全屏应用                                                                                         |
| 门禁   | `architecture-check`（maxFileLines 800）、bundle size（宠物独立 chunk，主 chunk 不增）、coverage 阈值、lint/typecheck、py38（后端无改动则天然通过） |

**性能预算**

- 宠物渲染器 JS ≤ 200KB（gzip）；内置素材 ≤ 3MB；解码内存 ≤ 60MB。
- 空闲 CPU < 1–2%；动画停止时不得有持续 rAF / 轮询（状态轮询 1.5s 一次即可）。
- 主进程新增轮询在宠物关闭时必须完全停止。

---

## 7. 风险与对策

| 风险                            | 等级 | 对策                                                                                                                                                            |
| ------------------------------- | ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Win7 透明窗/穿透不稳定甚至卡死  | 高   | M0 真机验证；兼容模式默认应用内；不做穿透；保留一键关闭                                                                                                         |
| 新增窗口被现有 IPC 信任模型拒绝 | 中   | 不改 `isTrustedRenderer`；主进程单向推送 + 窄 `pet:*` 通道 + sender 校验                                                                                        |
| 素材版权/角色 IP                | 高   | dsh-pet 素材为 MIT 的 AI 生成动画，技术可用；但角色与 DeepSeek 吉祥物存在联想。默认做可选包 + 保留 LICENSE/NOTICE；商用内置前取得书面许可并做法务确认（§4.9.1） |
| 打扰用户 / 性能负担             | 中   | 默认「重要气泡 + 仅审批提示音」；安静模式、减少动态；空闲停动画                                                                                                 |
| 状态映射不准导致「乱演」        | 中   | 只映射可验证事件；优先级 + 瞬态；不伪造进度；纯函数便于回放测试                                                                                                 |
| 体积棘轮与架构基线              | 低   | 独立 entry；纯函数模块拆分；新增文件按层放置                                                                                                                    |
| 主进程轮询打断流/重复 attach    | 低   | 用 `active` 端点去重；attach 支持多订阅者；done 后关闭连接                                                                                                      |
| 双分支同步成本                  | 中   | 纯前端 + Electron，无 pydantic 差异；一次 cherry-pick 即可，Win7 只加兼容分支                                                                                   |

---

## 8. 涉及文件（预估）

**新增**

- `electron/petWindow.ts`、`electron/petController.ts`、`electron/petState.ts`、`electron/petIpc.ts`、`electron/petConfigStore.ts`
- `pet.html`、`src/pet/main.tsx`、`src/pet/PetApp.tsx`、`src/pet/animation/`、`src/pet/__tests__/`
- `src/pages/settings/PetTab.tsx`
- `src/shared/api/petBridge.ts`（preload 桥类型）
- `public/pet/sage-leaf/`（manifest + 帧图）
- `electron/__tests__/petWindow.test.ts`、`electron/__tests__/petState.test.ts`

> 一次性移植路线下追加：`src/pet/engine/`（Sage 自有的 dsh-pet 移植代码）、`third_party/dsh-pet/NOTICE.md`；主进程窗口文件由 `petWindow.ts` 调整为 `electron/pet/windows.ts` + `electron/pet/ipc.ts`。

**修改**

- `electron/main.ts`（启动/退出挂载 petController；不做信任放宽）
- `electron/preload.ts`（增加 `petBridge` 窄接口）
- `electron/tray.ts`（菜单项）
- `vite.config.ts`（多页 entry）
- `src/pages/settings/settingsTabs.tsx`、`settingsSearchEntries.ts`、i18n zh/en、守卫测试
- `src/shared/types/electron-api.ts`（桥类型）

**不改**

- `electron/main.ts:907` 的 `isTrustedRenderer`（保持只认主窗口）
- 后端设置 schema（P0 宠物配置不进 `AppSettings`）

---

## 9. 待决策

1. **默认形象与素材策略**：是否把 dsh-pet 的大肥鱼素材作为可选包或默认包；若商城内置，需先取得授权并做法务确认（§4.9.1）。
2. **P0 是否包含上下文体力条**：建议 P1，避免 P0 过重。
3. **Win7 默认形态**：建议 `in-app`（最稳），桌面窗作为可选；需真机验证后定稿。
4. **默认开启还是灰度关闭**：建议首个版本默认关闭，设置页/托盘引导开启，收集反馈后再默认开启。

---

## 10. 参考链接

- DSH 大肥鱼（原生透明窗 + 任务状态联动）：https://www.npmjs.com/package/dsh-dafeiyu
- dsh-pet（透明窗 + 动画链 + pet pack）：https://github.com/PC2005-cloud/dsh-pet
- dsh-stamina-pet（每会话体力条 + 鼠标穿透轮询）：https://github.com/theskywilldawn/dsh-stamina-pet
- 大肥鱼增强版（工具→动作映射、会话日志增量读取）：https://github.com/mdd111/deepseek-dafeiyu-pet
- vscode-pets（MIT，状态机 + Webview）：https://github.com/tonybaloney/vscode-pets
- BongoCat（Tauri + Live2D，输入驱动）：https://github.com/ayangweb/BongoCat
- 豆包系 PetAgent（Live2D + 对话 + 系统监测）：https://github.com/CianLaw/pet-agent
- Electron 无边框/透明/点击穿透文档：https://www.electronjs.org/docs/latest/tutorial/custom-window-interactions
- Live2D Cubism SDK 许可（年营收 <1000 万日元免许可费；可扩展应用例外）：https://www.live2d.com/zh-CHS/sdk/license/
