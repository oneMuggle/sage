# Recap 功能（M1 手动触发）

> 日期：2026-11-08
> PR：#2947 (main) / #2948 (release/win7)
> 对标：Claude Code `/recap` 命令

## 1. 背景与定位

Sage 已有上下文压缩（`compaction.py`），但后台静默执行，用户无法主动触发或查看结构化进度。Recap 补上了"面向人类"这一面：

- 用户通过 `/recap` 斜杠命令主动触发
- 后端调用 LLM 生成结构化总结（进度 / 决策 / 下一步 / 待确认问题）
- 前端以 `RecapCard` 卡片形式渲染在聊天流中

与 compaction 的分工：

| 维度 | compaction             | recap                     |
| ---- | ---------------------- | ------------------------- |
| 面向 | 机器（续接上下文）     | 人类（可理解性）          |
| 触发 | 自动（context 超阈值） | 手动（用户输入 `/recap`） |
| 输出 | 压缩后的摘要文本       | 结构化 JSON（4 段）       |

## 2. 涉及文件

### 后端

| 文件                                | 说明                                                                      |
| ----------------------------------- | ------------------------------------------------------------------------- |
| `backend/chat/recap.py`             | 核心逻辑：`generate_recap` + `_parse_recap_output` + `build_recap_prompt` |
| `backend/api/legacy_chat_routes.py` | `POST /api/v1/chat/recap` 路由                                            |
| `backend/api/legacy_models.py`      | `RecapRequest(session_id: str)`                                           |

### 前端

| 文件                                        | 说明                                     |
| ------------------------------------------- | ---------------------------------------- |
| `src/shared/api/types/chatAndEventTypes.ts` | `RecapResult` 类型定义                   |
| `src/shared/api/sessionApi.ts`              | `requestRecap(sessionId)` + 5 种响应分支 |
| `src/widgets/chat/RecapCard.tsx`            | 卡片渲染（可折叠段落）                   |
| `src/widgets/chat/ChatInput.tsx`            | `/recap` 命令分发（`onRecap` 回调）      |
| `src/widgets/chat/slashCommands.ts`         | 命令注册（`mode: 'recap'`）              |
| `src/pages/chat/useChatMessageActions.ts`   | `handleRecap` + 5 分钟节流               |
| `src/pages/Chat.tsx`                        | 渲染 `RecapCard`（`recapResult` 存在时） |
| `src/widgets/welcome/WelcomeInputCard.tsx`  | 欢迎页 `/recap` 静默忽略（无会话）       |

## 3. API 契约

### `POST /api/v1/chat/recap`

请求：`{ "session_id": string }`

响应分支：

| 场景          | 状态码 | 响应体                                                                   |
| ------------- | ------ | ------------------------------------------------------------------------ |
| 成功          | 200    | `{ ok: true, recap: { progress, decisions, nextSteps, openQuestions } }` |
| 会话不存在    | 404    | `{ detail: "会话不存在" }`                                               |
| 消息不足 3 条 | 200    | `{ ok: false, reason: "too_short", message: "..." }`                     |
| 无 LLM 配置   | 502    | `{ ok: false, error: "llm_not_configured" }`                             |
| LLM 调用失败  | 502    | `{ ok: false, error: "recap_failed" }`                                   |

前端 UX 对应：

- `ok + recap` → 渲染 RecapCard
- `reason: "too_short"` → `toast.info`
- `error: "llm_not_configured"` → `toast.error`
- `error: "recap_failed"` → `toast.error`

### `RecapResult` 形状

```typescript
interface RecapResult {
  progress: string;
  decisions: string[];
  nextSteps: string[];
  openQuestions?: string[];
}
```

camelCase 字段名（与 `to_dict()` 输出一致），前端直接用，无需转换。

## 4. 节流策略

`useChatMessageActions.ts` 内 `lastRecapAtRef`（`useRef<number>(0)`）记录上次成功时间戳，`RECAP_THROTTLE_MS = 5 * 60 * 1000`（5 分钟）。重复点击 → `toast.info`，不发请求。

## 5. 错误处理层次

`backend/chat/recap.py`：

- `RecapError`（基类）— LLM 调用失败 / 解析失败 / 未生成 progress
- `RecapTooShortError(RecapError)` — 消息数 < 3，单独 catch 返回 200 + `reason: "too_short"`（前端以 info 级别处理）

路由层 `legacy_chat_routes.py` 分开 catch 两个异常类，避免把"消息不足"误报为错误。

## 6. 测试覆盖

| 文件                                                  | 条数 | 覆盖                                                                     |
| ----------------------------------------------------- | ---- | ------------------------------------------------------------------------ |
| `backend/tests/unit/chat/test_recap.py`               | 14   | 解析（JSON/Markdown/降级）+ `to_dict` camelCase + prompt 构造 + 错误路径 |
| `backend/tests/api/test_session_recap_api.py`         | 5    | 404 / 502 llm / 200 too_short / 成功 camelCase / 502 fail                |
| `src/widgets/chat/__tests__/RecapCard.test.tsx`       | 6    | 渲染 + 折叠/展开 + 空段落跳过 + onDismiss                                |
| `src/widgets/chat/__tests__/ChatInput.recap.test.tsx` | 7    | 静态注册 + 菜单展示 + onRecap 回调 + 安全 no-op + loading/disabled 忽略  |

## 7. 与 release/win7 同步

PR #2948 从 `feat/recap-feature` cherry-pick 到 `release/win7`（通过 `cherry-pick/recap-to-win7` 分支）。冲突解决：`src/widgets/chat/slashCommands.ts` 中 `Activity`/`Stethoscope`/`Settings`（自透明对等命令）与 `ClipboardList`（recap 命令）四个图标全部保留，合并后命令列表同时包含两批命令。

Python 3.8 兼容：`backend/chat/recap.py` 顶部 `# ruff: noqa: UP006, UP007, UP035, UP045` + `from __future__ import annotations`。
