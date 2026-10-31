# 117 — 桌面宠物（大肥鱼）

> 2026-10-30 起实施。P0 状态陪伴 + P1 状态面板 + P2 互动/提示音已落地；素材与窗口层一次性移植自
> [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)（MIT），
> 许可与出处见仓库根 `third_party/dsh-pet/`。

## 1. 定位

桌宠不是独立聊天机器人，而是 Sage Agent 的「实体状态灯」：

- 只消费 Sage 已有的 Agent 事件（思考 / 工具 / 审批 / 重试 / 完成 / 错误）。
- 不读取屏幕、不截屏、不为宠物额外调用 LLM。
- 透明置顶小窗，单击回到对应会话，右键打开设置/大小/节奏菜单。

## 2. 架构

```
FastAPI chat stream (NDJSON)
        ▲ attach (relayChatStream)
        │
┌───────┴──────────────── Electron 主进程 ─────────────────┐
│ electron/pet/controller.ts  ← main.ts: trackStream()     │
│   ├─ state.ts        纯函数：AgentEvent → PetSnapshot    │
│   ├─ config.ts       userData/pet-config.json            │
│   ├─ packStore.ts    userData/pets/ 导入/导出/删除        │
│   ├─ packProtocol.ts sage-pet:// 协议（Range 支持）       │
│   ├─ windows.ts      透明置顶窗/穿透/拖拽/位置/看门狗     │
│   └─ ipc.ts          pet:* 白名单通道（校验发送窗口）      │
└───────┬──────────────────────────────────────────────────┘
        │ webContents.send('pet:state' | 'pet:config')
┌───────▼──────────────── 宠物渲染器 ──────────────────────┐
│ pet.html + src/pet/PetApp.tsx                            │
│   engine/animation.ts  动作选择 / 气泡文案                │
│   engine/packs.ts      内置素材清单 + 用户包 URL 解析     │
│   usePetPacks.ts       当前动画包（内置/用户导入）         │
│   public/pet/dafeiyu/  WebM 动画（VP9-alpha）             │
└──────────────────────────────────────────────────────────┘
```

**IPC 信任边界**：宠物窗不是 `isTrustedRenderer` 认可的窗口，不能调用
`sage:invoke` / `sage:listen`。它只有 `window.electronAPI.pet` 的窄桥；
主进程校验 `BrowserWindow.fromWebContents(sender)` 是主窗或宠物窗。
动画包管理（`pet:import-pack` / `pet:export-pack` / `pet:delete-pack`）
只接受主窗发送者，宠物窗仅能 `pet:list-packs` 读取清单。

## 3. 状态映射

来源：`backend/core/legacy/agent_state.py` 的 13 态 + 工具名。

| 事件                                                                                   | 宠物动作                                        | 优先级 | 气泡       |
| -------------------------------------------------------------------------------------- | ----------------------------------------------- | ------ | ---------- |
| `permission_request` / `ask_user_question` / `awaiting_step_confirm` / `approval_mode` | `waiting`                                       | 100    | 有         |
| `failed`                                                                               | `error`                                         | 90     | 有         |
| `done`                                                                                 | `done`                                          | 80     | 有         |
| `acting` + 工具名                                                                      | `acting`（bash/edit/read/web/mcp/office/other） | 60     | 视气泡模式 |
| `retry`                                                                                | `retry`                                         | 50     | 有         |
| `thinking` / `reasoning` / `content_delta`                                             | `thinking`                                      | 40     | 无         |
| `observing` / `step_done`                                                              | `observing`                                     | 30     | 无         |
| 无活跃会话                                                                             | `idle` → 2 分钟后 `sleeping`                    | 0      | 无         |

- `done` / `error` 45 秒后衰减回 `idle`；最近一次终态结果保留在面板里。
- 多会话并发时显示优先级最高的会话；平级取最近更新。
- 工具分类：`electron/pet/state.ts: classifyTool()`。
- `todo_snapshot` 记 `待办 n/m` + 当前项；`task_progress` 记 `步骤 n/m`。这两类事件只更新进度，不覆盖等待审批/工具执行的更高优先级气泡。
- 会话标题/上下文用量由 controller 异步补充：`GET /api/v1/sessions/{id}` 拿标题；流结束后 `GET /api/v1/usage/requests?session_id=…&limit=1` 拿最近一次 `prompt_tokens`，配合 chat 参数里的 `maxContext` 计算上下文占比。两者都是 best-effort，失败不影响状态动画。

### 3.1 面板与常驻徽章（P1）

- 单击宠物打开/关闭面板；主进程把窗口高度 +300px 并向上扩展，关闭时恢复。
- 面板内容：
  - 当前会话名（无标题时显示短 ID）、状态、当前工具；
  - 待办/步骤进度条 + 当前 todo；
  - 上下文用量条（有 `contextUsed/contextMax` 时）；
  - 最多 5 个最近/活跃会话，点击直达；
  - 「回到会话」「设置」按钮；
  - 空闲时显示「最近：已完成/出错 · N 分钟前」。
- 常驻状态徽章：宠物右上角的小圆点/字符，颜色区分等待审批/出错/完成/工具/思考/重试/睡眠，不受气泡模式影响。
- 气泡：`showSessionTitle=true` 时追加会话名；等待审批/出错会带工具名；待办/步骤显示 n/m。面板始终显示会话名（用户主动打开）。
- 面板打开时关闭点击穿透，保证面板按钮可点；关闭后恢复 60ms 光标命中。
- 面板底部显示「陪伴 N 天 · 摸头 M 次」（来自 `pet-profile.json`）。

### 3.2 互动、提示音与陪伴数据（P2）

- **单击**：延迟 240ms 后切换面板；2 秒内连点 5 下触发「别戳啦」生气动画与提示，不打开面板。
- **长按 550ms**：摸头。渲染层播放「挠痒咯咯笑」动画 + 本地气泡，调用 `pet:pat`；主进程把 `patCount+1` 写入 `pet-profile.json` 并推送新快照。
- **拖拽**：移动超过 4px 取消长按/点击，进入窗口拖动；松手保存位置。
- **提示音**：WebAudio 合成等待审批/出错/完成三种短音，按 `soundScenes` 开关播放；首次 pointerdown 时 prime AudioContext，失败静默。
- **陪伴数据**：`<userData>/pet-profile.json`，字段 `version/firstSeenAt/patCount/lastPatAt`（毫秒时间戳）；`bondDays = floor((now-firstSeenAt)/86400000)+1`。
- **完整动画包**：内置 dsh-pet 全部 109 个 WebM（约 52.7MB，MIT）。其中 87 个进入待机池，每段播完回到 `待机呼吸休闲` 循环，按 `tempo` 的 quiet/standard/lively（45–90 / 25–45 / 12–22 秒）随机休息后播下一段；点击回应从 5 个里随机抽。
- 以上互动不读取消息正文/参数，只记录本地计数。

### 3.3 应用内角落形态（P1 补全）

- `displayMode` 四种取值现在互相独立：`desktop` 只开透明置顶窗；`in-app` 只在主窗口右下角显示；`both` 同时显示；`off` 全部关闭。
- `in-app` 不创建额外 `BrowserWindow`：controller 仍聚合同一份 `PetSnapshot`，并在 `emit` / `broadcastConfig` 时推给主窗口；`src/widgets/pet/InAppPet.tsx` 渲染固定右下角的小宠物。
- 点击 in-app 宠物 → 打开当前会话；右键 → 打开宠物设置；尺寸按 `size` 映射 96/120/150/190/230px；`reduceMotion` 时暂停在首帧。
- 这条形态不依赖透明窗/点击穿透，作为 Win7 无 Aero、远程桌面或不想开桌面窗时的可用方案；与桌面窗共用动作/气泡/徽章。

### 3.4 后台任务聚合（P1 补全）

- Task Center 是 renderer 本地状态（office/wiki/custom/编排任务在页面里 register），主进程无法轮询；`TaskCenterPetBridge` 在 App 层订阅 store，把非终态任务压缩为 `PetTaskReport`，经 `pet:report-tasks` 上报。
- 主进程 `normalizeTaskReports` 校验/去重/限制 20 条；`PetSnapshot.tasks` 随状态一起下发。
- 仅在聊天空闲/睡眠时用后台任务覆盖动作：`awaiting_approval` > `failed`（10 分钟窗口）> `running/queued/paused`；活跃聊天会话始终优先。
- 面板「后台任务」区显示 kind/title/status/percent；带 `sessionId` 的任务可点击回到对应会话。
- 主进程补充轮询（`electron/pet/backgroundTasks.ts`，桌宠启用且 `displayMode≠off` 时每 20s）：
  - `GET /api/v1/orchestration/lanes?limit=20`：按 `metadata.team_id` 把一个编排 run 的多个 lane 聚合成一行（标题优先 `metadata.goal`），`blocked→awaiting_approval`、`running→running`、`created/ready/queued→queued`、近期 `failed→failed`；成功/取消的组不常驻面板。
  - `GET /api/v1/scheduled/tasks`：后端没有持久「运行中」状态，只在 `last_status=failed` 且 `last_attempt` 在 10 分钟内时上报失败（带目标 `session_id`，可点回会话）。
  - 轮询失败保留上一份快照；与 Task Center 报告按 id 去重合并（Task Center 优先），总量仍限 20 条。

## 4. 窗口行为

- `transparent` + `frame:false` + `alwaysOnTop` + `skipTaskbar` + `focusable:false`。
- 点击穿透：主进程每 60ms 读取光标，落在角色命中框内才可交互
  （`electron/pet/geometry.ts: petHitBox`）；`setIgnoreMouseEvents(true, {forward:true})`。
- 穿透 API 异常（Win7/VM）时永久退回「整窗可交互」并记日志。
- 面板打开时整窗可交互；面板关闭后恢复按角色命中框穿透。
- 拖拽：渲染层 pointer 事件 → 主进程按全局光标位移窗口；松手保存到
  `userData/pet-window-<petId>.json`（默认宠物仍用旧 `pet-window.json`；面板打开时保存的是收起后的基准位置）。
- 位置：启动时按当前显示器工作区夹取；支持多屏/DPI。
- Win7：`compatibilityMode=auto` 时检测到 Windows 6.x 使用不透明窗口、关闭穿透。

### 4.1 多宠物（1–3 只）

- 每个宠物是独立窗口，拥有自己的 `id`、动画包、大小与位置文件；节奏/气泡/提示音/减少动态/兼容模式等行为设置保持全局。
- 默认位置从右下角向左依次错开；拖动/「回到初始位置」只影响当前宠物。
- 所有宠物共享同一份 Agent 快照（同一状态、同一气泡），避免多窗口状态漂移。
- 应用内模式按 `pets` 顺序横向排列，气泡只显示在第一只上；桌面模式每只都有气泡。
- 设置页可添加/移除宠物（最多 3 只），导入动画包会自动赋给第一只；删除动画包会把使用它的所有宠物回落到内置包。

## 5. 配置

`<userData>/pet-config.json`（dev 为 `<repo>/data/pet-config.json`）：

```json
{
  "version": 2,
  "enabled": true,
  "displayMode": "desktop",
  "tempo": "standard",
  "reduceMotion": false,
  "bubbleMode": "important",
  "soundScenes": { "waiting": true, "error": false, "done": false },
  "showSessionTitle": false,
  "compatibilityMode": "auto",
  "followActiveSession": true,
  "pets": [
    { "id": "default", "petPack": "dafeiyu", "size": "medium" },
    { "id": "pet-2", "petPack": "my-pack", "size": "small" }
  ]
}
```

v1 单宠配置（顶层 `petPack`/`size`）读取时自动迁移为一只 `default` 宠物；`id` 只允许 `^[a-z0-9][a-z0-9-]{0,31}$`，重复或非法 id 会被替换，列表最多 3 只。

配置由主进程独占写入（原子 rename），设置页经 `pet:get-config` /
`pet:set-config` 读写，不进入 `AppSettings`，因此不影响后端 settings
canonicalizer 与 Win7 设置 schema parity。

陪伴数据独立存 `<userData>/pet-profile.json`（`version/firstSeenAt/patCount/lastPatAt`），重置宠物配置不会清空摸头计数与陪伴天数。

## 6. 素材与许可

- `public/pet/dafeiyu/*.webm`：完整 109 个动作（约 52.7MB），MIT；其中 87 个作为待机随机池，6 个工作状态、5 个点击回应、3 个睡眠、6 个余额（预留）、1 个拖拽、1 个重试，以及摸头/生气两个专属动作。
- 出处、修改与角色 IP 提示见 `third_party/dsh-pet/NOTICE.md`；清单由 `scripts/pet-pack/generate-dafeiyu-pack.mjs` 从 WebM 文件生成。
- 新增内置素材：在 `public/pet/<id>/` 放 WebM + `pack.json`，并在
  `src/pet/engine/packs.ts` 注册清单（打包环境不走 `fetch(pack.json)`，
  避免 `file://` CORS）。完整包会让安装包增加约 45MB，这是当前全量内置的代价。
  **用户导入的动画包不需要改这里**，见下一节。

### 6.1 自定义动画包（导入 / 导出）

用户可在 **设置 → 智能体 → 桌宠 → 动画包** 导入 zip。包解压到
`<userData>/pets/<id>/`，与安装包解耦；选中项存在 `pet-config.json` 的
`pets[].petPack` 字段（每只宠物可不同）。

```
my-pet.zip
├─ pack.json              # 可放在 zip 根，或唯一的顶层文件夹内
└─ frames/
   ├─ idle-0.webp
   ├─ think.webm
   └─ 待机.webm
```

`pack.json`：

```jsonc
{
  "id": "my-pet",                 // ^[a-z0-9][a-z0-9-]{1,31}$，不能是 dafeiyu
  "name": "小叶灵",
  "version": "1.0.0",
  "license": "CC-BY-4.0",         // 必填，便于署名
  "source": "https://example.com", // 可选，仅 http(s)
  "canvas": { "width": 256, "height": 256 },  // 64–2048
  "anchor": { "x": 128, "y": 236 },           // 位于 canvas 内
  "actions": {
    "idle": ["frames/idle-0.webp"],           // 必填，1–64 个文件
    "thinking": ["frames/think.webm"],
    "acting_edit": ["frames/coding.webm"]
  }
}
```

- 动作键白名单：`idle/sleeping/thinking/acting/observing/retry/waiting/done/error/click/pat/angry/drag/sleep_start/sleep_loop/sleep_end/balance` 及 `acting_{bash,edit,read,web,mcp,office,other}`；缺失动作回落到 `idle`。
- 素材扩展名：`webm/mp4/webp/png/jpg/jpeg/gif/apng`；允许 `README.md` 等未引用的纯文档，其余未引用文件拒绝。
- 限制：zip ≤ 320MB、解压总计 ≤ 256MB、单文件 ≤ 64MB、条目 ≤ 512、`pack.json` ≤ 1MB。
- 校验（`electron/pet/packManifest.ts` + `zip.ts`）：拒绝路径穿越（含 `%2F`/`..`）、符号链接、加密/ZIP64、重复条目、CRC 不符、未知动作、越界 canvas/anchor；**不执行包内任何脚本**。
- 写入采用“先解压到隐藏 staging 目录，再 rename 到位”，失败不会留下半成品；同名 id 不覆盖，需先删除或改 id。
- 渲染层通过 `sage-pet://<id>/<相对路径>` 读取素材（`packProtocol.ts`），协议只服务上述扩展名且根目录限定在 `<userData>/pets/<id>/`，支持 200/206/416，WebM 可正常 Range 播放。
- 导入成功后自动切换到新包；删除当前包会回落到内置 `dafeiyu`。导出仅针对用户包，生成 stored zip（`<id>/pack.json` + 引用的素材），可再次导入或分享。

## 7. 测试与验证

- 单测：`electron/__tests__/petState.test.ts`、`petConfig.test.ts`、
  `petGeometry.test.ts`、`petProfile.test.ts`、`petTasks.test.ts`、
  `petZip.test.ts`（CRC/穿越/zip bomb/GBK 文件名）、
  `petPackManifest.test.ts`（schema/根目录/引用校验）、
  `petPackStore.test.ts`（导入/导出/删除/同名拒绝）、
  `packProtocol.test.ts`（URL 解析/Range）、
  `petBackgroundTasks.test.ts`（编排 lane 聚合/定时失败/任务合并）、
  `src/pet/__tests__/animation.test.ts`、`src/pet/__tests__/tempo.test.ts`、
  `src/pet/__tests__/packs.test.ts`、
  `src/pages/settings/__tests__/PetTab.pack.test.tsx`、
  `src/features/task-center/__tests__/petReports.test.ts`。
- 设置守卫：`settingsTabs.guards.test.ts`（tab 数 19）、
  `settingsSearchIndex.test.ts`（`pet` 为合法 tab）。
- 手工/自动冒烟：Electron 启动后确认 `pet.html` 窗口存在、置顶、视频源正确；
  用本地假 NDJSON 流验证 thinking → acting(edit) → done 的动画与气泡。
  面板冒烟额外验证：会话标题、待办 2/5、步骤 3/7、上下文 31%（40k/128k）、
  窗口 300×241 → 300×541、完成态显示 7/7 与「已完成」。
  互动冒烟：长按 750ms → 摸头动画 + 气泡 + `patCount=1`；2 秒内点 5 下 → 生气动画 + 「别戳啦」。
  动画包冒烟：109 个 WebM 全部存在；idle 池 87 个，`resolveAnimation` 变体轮播与 `resolveInteraction` 随机回应由单测覆盖。
  多宠物冒烟：配置两只（内置包 + 用户包）→ 两个独立窗口、视频源分别来自 `./pet/dafeiyu` 与 `sage-pet://`、窗口位置不重叠。
- 体积门禁：主 chunk 1.68MB / 1.80MB；`dist/assets` 11.10MB / 12MB；`public/pet` 资源不计入该门禁，但安装包会增大约 45MB。

## 8. 已知限制 / 下一步

- P0 仅实现「桌面」形态；`displayMode=in-app/both` 由主窗口内的 `InAppPet` 承担，不再回退到桌面窗。
- 未在 Win7 真机验证透明/穿透；兼容模式已写好但需真机回归。
- 提示音为 WebAudio 合成短音，不是角色语音；需一次用户手势解锁 AudioContext。
- 面板已能列出最近/活跃会话，但「每个会话一只宠物」未实现。
- 多宠物已支持 1–3 只（独立动画包/大小/位置）；应用内模式横向排列且只有第一只显示气泡，尚未按会话分配不同宠物。
- 独立编排 run 已通过主进程轮询 lanes 接入（按 team 聚合）；定时任务只覆盖「近期投递失败」，因为后端没有持久运行中状态，成功/等待中的定时任务不会显示。
- 上下文条依赖 chat 参数里的 `maxContext` 与 usage 事件；自动推断上下文时可能只显示已用量、不显示百分比。
- 完整动画包已全量内置（约 52.7MB），安装包相应增大；如果后续要控制体积，可改成「精选内置 + 完整包可选下载/导入」。
- 自定义 pet pack 导入/导出已实现（zip + `sage-pet://`）；尚未做包内素材热更新（同名 id 需删除后重新导入），也未验证 Win7 下大体积 zip 的导入耗时。聊天/TTS 未做。
