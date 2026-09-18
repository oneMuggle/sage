# 桌面宠物（Pet）设计：状态联动宠物 + 可替换宠物包（2026-09-18）

- **状态**：方案定稿，P1 实施中
- **范围**：main 与 release/win7 双分支均需交付（对齐优先政策，见 [`technical/31-win7-lts.md`](../technical/31-win7-lts.md) §2）；P3 桌面悬浮宠带 Win7 降级硬门禁
- **编号约定**：P1 = 应用内宠物；P2 = 宠物包导入管线；P3 = 桌面悬浮宠物窗；状态枚举 = `PetState`（八态）
- **方法**：主流 AI 应用桌宠范式调研（Codex 宠物 / Clawd 桌宠 / TRAE 状态联动 Demo）+ 本仓事件链路与 store 模式勘察（附 `file:line`）

## 0. 结论速览

主流桌宠的共同范式：**宠物 = AI 会话状态的可视化入口**——动画与 agent 状态机联动、可拖拽、点击唤起主窗、自身不承载输入。Sage 已具备全部数据链路：单 agent 事件词表（`src/shared/api/types.ts:164-202`）、全局流状态 `chatStreamStore`（`src/features/send-message/chatStreamStore.ts:223`）、等待确认态（`src/entities/permission/permissionState.ts:31`、`src/entities/question/questionState.ts:28`）、多 run 聚合（`src/features/task-center/taskCenterStore.ts:118`）。宠物本质是把 TaskCenter 的状态投影换成角色动画，**不新增任何后端/IPC 链路**。

差异化点：**宠物做成声明式资产包，可替换、可导入、可选择**——只收数据（动画 + 清单），禁止代码，杜绝导入通路上的任意执行风险。

## 1. 目标与非目标

**目标**

1. 应用内宠物（P1）：常驻角落，动画实时反映「思考/干活/等确认/完成/失败/空闲」
2. 宠物包体系（P1 定规范、P2 开导入）：内置包与导入包走同一渲染路径
3. 桌面悬浮宠（P3）：透明置顶小窗，真·桌面伴随
4. 双分支零分叉：全部改动落在 Electron/前端同构层，**后端 Python 零触点**

**非目标**

- 宠物不接收文本输入、不做命令入口（点击只做唤起/跳转）
- 不支持宠物包携带 JS/可执行逻辑
- 不做宠物成长/数值系统（先验证状态联动手感）
- 不进编排设置 6 文件链路（纯前端 pref，与后端 `settings_canonicalizer` 无关）

## 2. P1：应用内宠物

### 2.1 状态机 `petStore`

新文件 `src/features/pet/petStore.ts`（zustand module-singleton，模式抄 `src/features/right-panel/rightPanelStore.ts:20,79`，含 localStorage 手工持久化路子）。

八态优先级归约（高→低），聚合源均为现成 store：

| PetState | 触发条件 | 来源 |
| --- | --- | --- |
| `attention` | 任一会话有挂起权限请求/提问 | `permissionState` / `questionState` |
| `thinking` | 任一 session `streaming && status==='thinking'` | `chatStreamStore.sessions` |
| `working` | 任一 session `streamingToolCalls` 非空 | `chatStreamStore.sessions` |
| `celebrate` | `done` 后 8s 庆祝窗口 | 由 `streaming` 翻转沿检测 |
| `failed` | 最近一次 turn `failed`（10s 窗口） | 同上 |
| `reporting` | 编排多 run 有进行中任务 | `runControlStore` / `laneBoardStore` |
| `idle` | 有前台活动、无以上状态 | 默认 |
| `sleeping` | `idle` 持续 5 分钟 | 计时器 |

`celebrate/failed` 用「沿触发 + 定时器衰减」实现，避免常驻。聚合函数 `computePetState(snapshot)` 写成纯函数便于测试。

### 2.2 宠物包规范

```
<pet-pack>/
├── pet.json              # 清单：id / name / author? / bodyClass / animations
└── *.css | *.png | *.webp  # 每态动画类名在 CSS 中定义；图片仅经相对 url() 引用
```

> **2026-09-18 P2 实施时修订**：清单定为 `pet.json`（JSON 而非 YAML）——
> 主进程无 YAML 解析器，引入依赖违反门禁 3；JSON 同样满足"纯数据、
> 禁可执行代码"。白名单 `.json/.css/.png/.webp`、限额 zip≤8MB /
> 单文件≤2MB / 解压总量≤5MB / 条目≤64，均落在 `electron/petImport.ts`。

P1 内置包以 TS descriptor 形式声明（`src/features/pet/builtin/`），但**渲染层只认 `PetPackDescriptor` 接口**（id、每状态 → CSS 关键帧类名或雪碧图参数），P2 导入的 zip 解包后生成同型 descriptor——两来源同一路径，无特例。

视觉基线：以 `public/sage.svg`（薄荷 `#5eead4` + 紫 `#a855f7` 对角分割）派生 Q 版形象，遵守 `docs/technical/45-brand-icons.md` 单一来源规范：新增 `PetSprite` 组件消费 descriptor，不得散落 inline SVG。P1 内置 2 只：`mint-blob`（圆滴形）、`violet-cat`（耳廓剪影），CSS keyframes 驱动，**不引入 lottie-web**（表达力够用时保持零依赖；不够用再按门禁 3 评估）。

### 2.3 宿主与交互

- `src/features/pet/PetDock.tsx` 挂 `src/widgets/layout/Layout.tsx`（与 `TaskCenterWidget.tsx:157` 同区，`Layout.tsx:162` 附近）
- 点击宠物 → 跳到优先级最高的关联会话（复用侧栏导航 action，参照 `Sidebar.tsx:141` 消费 `permissionState` 的跳转路子）
- 多 run 进行中 → 徽标显示计数（`taskCenterStore` 聚合）
- hover tooltip：当前状态文案（i18n）
- 拖拽位置暂不做（P3 宠物窗天然可拖，P1 dock 固定角落）

### 2.4 设置项

`pet-enabled`（默认 off）、`pet-selected`（默认 `mint-blob`）走 **localStorage 手工持久化**（`rightPanelStore.ts:8-20` 先例，zustand module-singleton 内读写），**不进** `PreferenceKey` 白名单与后端 settings blob——保持"后端零触点"。设置面板 GeneralTab 加 `SettingRow`+`Toggle`（原语 `src/pages/settings/components.tsx:30,42`）+ 宠物单选预览列表（复用 `PetVisual`）。

## 3. P2：宠物包导入管线（已实施，2026-09-18）

- 全部落 **Electron 主进程**（新 `electron/petImport.ts` 纯逻辑 + `electron/petIpc.ts` 接线），复用 office staging quarantine 的 plan/commit/discard 分段：zip 字节 → 内存校验解包（新 `electron/zipRead.ts`，零依赖手写 reader：仅 method 0/8，拒加密/ZIP64/symlink/路径穿越/重复条目，CRC 校验，声明与实际解压双限幅防爆）→ 写入 `pet-quarantine/<token>/` → 渲染端确认（同 id 冲突需显式覆盖授权）→ commit 移入 `userData/pets/<id>/`（路径解析走 `electron/userDataPaths.ts`）
- 校验：`pet.json` 清单字段白名单正则（id/bodyClass/动画类名即注入 DOM 的字符串）、扩展名白名单 `.css/.png/.webp`、CSS 拒 `@import` 与网络 `url()`、包内相对图片按引用内联为 data: URL 后经 IPC 一次返回
- 渲染进程经 preload `pet` 桥（`electron/preload.ts`，接口声明进 `src/shared/types/electron-api.d.ts`）读包列表/导入/移除；`features/pet/importedPacks.ts` 把导入包转成同型 `PetPackDescriptor` 注册 + `<style data-pet-pack>` 注入——内置/导入同一路径
- 同 id 冲突在确认行提示「覆盖导入」；Web 通道（无 Electron）桥缺省 → 隐藏导入入口
- 契约测试：`electron/__tests__/petImport.test.ts`（手工 zip writer 构造合法/恶意包字节）+ `petIpc.test.ts` + `src/features/pet/__tests__/importedPacks.test.ts`

## 4. P3：桌面悬浮宠物窗（后续 PR）

- 新 `electron/petWindow.ts`，模板抄 `electron/splash.ts:67`（自包含、`ready-to-show` 兜底、幂等降级），补仓内首例的 `transparent / alwaysOnTop / frame:false / skipTaskbar`
- 状态同步：主窗渲染进程把 `petStore` 快照经 preload 新方法发到主进程，主进程转发宠物窗（宠物窗不直连后端）
- 位置持久化 `electron-store`（同 `closeToTray.ts:12` 的主进程偏好文件路子）
- **Win7 硬门禁**：`os.release().startsWith('6.1')` → 禁用 `transparent`，降级为不透明圆角深色底 + 阴影贴图（Chromium 106 在 Win7 无 DWM 合成时透明窗黑块是已知问题）；无降级实现不予合入
- 人工烟测清单（`31-win7-lts.md` §3）追加：宠物窗在 Win7 真机可见、无黑块

## 5. 双分支对齐门禁自查

| 门禁 | 自查结果 |
| --- | --- |
| 后端 py3.8 纪律 | 后端零改动（导入管线刻意收进 Electron 主进程） |
| Chromium 106 / ES2020 | CSS keyframes + zustand + 纯 JS，全部在基线内；无新前端依赖 |
| 依赖检查 | P1/P2 无新依赖；lottie 仅在 CSS 表达力不足时按门禁重评 |
| 同步方式 | main PR 合入 CI 绿 → cherry-pick `release/win7` → 双分支各自 CI；P3 需 Win7 真机验证后同步打 tag |

## 6. 测试与验收

- `petStore` 纯函数映射测试：各聚合源组合 → 期望 `PetState`（含沿触发衰减）
- `PetDock` 组件测试（testing-library，参照 `right-panel/__tests__` 布局）
- 设置持久化测试：`pet.enabled/pet.selected` 读写
- 门禁：`npm run typecheck && npm run test:run && npm run lint` 全绿
- 验收：开一个带工具调用的会话，宠物依次呈现 thinking → working → celebrate；触发权限请求 1s 内变 attention；关闭开关后 dock 消失且状态不残留

## 7. 里程碑

1. **M1（本 PR）**：§2 全部（P1 + 包规范落码）
2. **M2**：§3 导入管线 + 宠物管理 UI
3. **M3**：§4 桌面悬浮宠（含 Win7 降级与真机验证）
