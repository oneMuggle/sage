# 114 — 桌面宠物（大肥鱼）

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
│   ├─ windows.ts      透明置顶窗/穿透/拖拽/位置/看门狗     │
│   └─ ipc.ts          pet:* 白名单通道（校验发送窗口）      │
└───────┬──────────────────────────────────────────────────┘
        │ webContents.send('pet:state' | 'pet:config')
┌───────▼──────────────── 宠物渲染器 ──────────────────────┐
│ pet.html + src/pet/PetApp.tsx                            │
│   engine/animation.ts  动作选择 / 气泡文案                │
│   engine/packs.ts      内置素材清单（大肥鱼）             │
│   public/pet/dafeiyu/  WebM 动画（VP9-alpha）             │
└──────────────────────────────────────────────────────────┘
```

**IPC 信任边界**：宠物窗不是 `isTrustedRenderer` 认可的窗口，不能调用
`sage:invoke` / `sage:listen`。它只有 `window.electronAPI.pet` 的窄桥；
主进程校验 `BrowserWindow.fromWebContents(sender)` 是主窗或宠物窗。

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
- 以上互动不读取消息正文/参数，只记录本地计数。

## 4. 窗口行为

- `transparent` + `frame:false` + `alwaysOnTop` + `skipTaskbar` + `focusable:false`。
- 点击穿透：主进程每 60ms 读取光标，落在角色命中框内才可交互
  （`electron/pet/geometry.ts: petHitBox`）；`setIgnoreMouseEvents(true, {forward:true})`。
- 穿透 API 异常（Win7/VM）时永久退回「整窗可交互」并记日志。
- 面板打开时整窗可交互；面板关闭后恢复按角色命中框穿透。
- 拖拽：渲染层 pointer 事件 → 主进程按全局光标位移窗口；松手保存到
  `userData/pet-window.json`（面板打开时保存的是收起后的基准位置）。
- 位置：启动时按当前显示器工作区夹取；支持多屏/DPI。
- Win7：`compatibilityMode=auto` 时检测到 Windows 6.x 使用不透明窗口、关闭穿透。

## 5. 配置

`<userData>/pet-config.json`（dev 为 `<repo>/data/pet-config.json`）：

```json
{
  "version": 1,
  "enabled": true,
  "displayMode": "desktop",
  "size": "medium",
  "tempo": "standard",
  "reduceMotion": false,
  "bubbleMode": "important",
  "soundScenes": { "waiting": true, "error": false, "done": false },
  "showSessionTitle": false,
  "compatibilityMode": "auto",
  "petPack": "dafeiyu",
  "followActiveSession": true
}
```

配置由主进程独占写入（原子 rename），设置页经 `pet:get-config` /
`pet:set-config` 读写，不进入 `AppSettings`，因此不影响后端 settings
canonicalizer 与 Win7 设置 schema parity。

陪伴数据独立存 `<userData>/pet-profile.json`（`version/firstSeenAt/patCount/lastPatAt`），重置宠物配置不会清空摸头计数与陪伴天数。

## 6. 素材与许可

- `public/pet/dafeiyu/*.webm`：从 dsh-pet `assets/webm` 选取 20 个动作（含摸头/生气），
  MIT；完整 109 个动作共 52.7MB，未全部内置。
- 出处、修改与角色 IP 提示见 `third_party/dsh-pet/NOTICE.md`。
- 新增素材：在 `public/pet/<id>/` 放 WebM + `pack.json`，并在
  `src/pet/engine/packs.ts` 注册清单（打包环境不走 `fetch(pack.json)`，
  避免 `file://` CORS）。

## 7. 测试与验证

- 单测：`electron/__tests__/petState.test.ts`、`petConfig.test.ts`、
  `petGeometry.test.ts`、`petProfile.test.ts`、`src/pet/__tests__/animation.test.ts`。
- 设置守卫：`settingsTabs.guards.test.ts`（tab 数 19）、
  `settingsSearchIndex.test.ts`（`pet` 为合法 tab）。
- 手工/自动冒烟：Electron 启动后确认 `pet.html` 窗口存在、置顶、视频源正确；
  用本地假 NDJSON 流验证 thinking → acting(edit) → done 的动画与气泡。
  面板冒烟额外验证：会话标题、待办 2/5、步骤 3/7、上下文 31%（40k/128k）、
  窗口 300×241 → 300×541、完成态显示 7/7 与「已完成」。
  互动冒烟：长按 750ms → 摸头动画 + 气泡 + `patCount=1`；2 秒内点 5 下 → 生气动画 + 「别戳啦」。
- 体积门禁：主 chunk 1.67MB / 1.80MB；`dist/assets` 11.07MB / 12MB。

## 8. 已知限制 / 下一步

- P0 仅实现「桌面」形态；`displayMode=in-app/both` 暂按桌面处理，应用内角落
  浮层待后续。
- 未在 Win7 真机验证透明/穿透；兼容模式已写好但需真机回归。
- 提示音为 WebAudio 合成短音，不是角色语音；需一次用户手势解锁 AudioContext。
- 面板已能列出最近/活跃会话，但「每个会话一只宠物」未实现。
- 独立编排 run（`orch-events-*`）、Task Center、定时任务尚未接入宠物聚合；
  聊天流内的 `task_status` / `task_progress` 已覆盖。
- 上下文条依赖 chat 参数里的 `maxContext` 与 usage 事件；自动推断上下文时可能只显示已用量、不显示百分比。
- 素材完整包/自定义 pet pack 导入待后续；聊天/TTS 未做。
