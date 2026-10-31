# 114 — 桌面宠物（大肥鱼）

> 2026-10-30 起实施。P0 状态陪伴已落地；素材与窗口层一次性移植自
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

- `done` / `error` 8 秒后衰减回 `idle`。
- 多会话并发时显示优先级最高的会话；平级取最近更新。
- 工具分类：`electron/pet/state.ts: classifyTool()`。

## 4. 窗口行为

- `transparent` + `frame:false` + `alwaysOnTop` + `skipTaskbar` + `focusable:false`。
- 点击穿透：主进程每 60ms 读取光标，落在角色命中框内才可交互
  （`electron/pet/geometry.ts: petHitBox`）；`setIgnoreMouseEvents(true, {forward:true})`。
- 穿透 API 异常（Win7/VM）时永久退回「整窗可交互」并记日志。
- 拖拽：渲染层 pointer 事件 → 主进程按全局光标位移窗口；松手保存到
  `userData/pet-window.json`。
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

## 6. 素材与许可

- `public/pet/dafeiyu/*.webm`：从 dsh-pet `assets/webm` 选取 18 个动作，
  MIT；完整 109 个动作共 52.7MB，未全部内置。
- 出处、修改与角色 IP 提示见 `third_party/dsh-pet/NOTICE.md`。
- 新增素材：在 `public/pet/<id>/` 放 WebM + `pack.json`，并在
  `src/pet/engine/packs.ts` 注册清单（打包环境不走 `fetch(pack.json)`，
  避免 `file://` CORS）。

## 7. 测试与验证

- 单测：`electron/__tests__/petState.test.ts`、`petConfig.test.ts`、
  `petGeometry.test.ts`、`src/pet/__tests__/animation.test.ts`。
- 设置守卫：`settingsTabs.guards.test.ts`（tab 数 19）、
  `settingsSearchIndex.test.ts`（`pet` 为合法 tab）。
- 手工/自动冒烟：Electron 启动后确认 `pet.html` 窗口存在、置顶、视频源正确；
  用本地假 NDJSON 流验证 thinking → acting(edit) → done 的动画与气泡。
- 体积门禁：主 chunk 1.67MB / 1.80MB；`dist/assets` 11.07MB / 12MB。

## 8. 已知限制 / 下一步

- P0 仅实现「桌面」形态；`displayMode=in-app/both` 暂按桌面处理，应用内角落
  浮层待 P1。
- 未在 Win7 真机验证透明/穿透；兼容模式已写好但需真机回归。
- 提示音字段已持久化，尚未接线播放。
- 多会话聚合已支持，但「每个会话一只宠物」未实现。
- 素材完整包/自定义 pet pack 导入待 P1/P2。
