# client_message_id 消息身份协议 Round 1 实施计划

> 日期: 2026-09-18 · 分支: `docs/update-rollback-cmid-r1-plan` · 基于 main
> 系列: 消息对账专项第二批 (#940) 的根治设计
> Win7 对齐: **适用 release/win7**（协议三层改动，随下一轮 cherry-pick 同步；
> 两分支必须同版合入，否则旧 win7 后端与新前端混跑时退化为现状=计数去重兜底）。
> 依赖: 零新增。

## 背景

消息重复显示的根因：前端乐观消息用本地 UUID，后端持久化用服务端 UUID——
流结束后 `loadMessages` 对账时同一轮内容以两份不同 id 存在。#940 落地的
`(role, content)` 计数感知去重是**治标**：依赖内容逐字节相等，在后端对
content 做任何规范化（trim、附件转写）时失配；且无法表达"同一条消息"
的身份语义（编辑重发、fork 的 `at_message_id` 引用仍指向服务端 id）。

## 协议设计

### A. 请求侧（ChatRequest）

- 新增可选字段 `client_message_id: str | None`
  （校验：`^[0-9a-f-]{8,64}$`，由前端 `crypto.randomUUID()` 生成）；
- 未传 → 行为与现状完全一致（服务端生成 UUID），旧客户端零影响。

### B. 持久化侧（producer）

- 传了 `client_message_id` 时，user 消息落库 id = `u-<client_message_id>`
  （确定性；同 id 重复提交 → 该轮已存在时直接复用既有消息，天然幂等）；
- assistant 消息 id 仍服务端生成，但 DONE 事件新增
  `message_id: <assistant_id>`（`AgentEvent.to_dict` 加可选字段）。

### C. 前端侧（useChat / store）

- `sendMessage` 生成 `clientMessageId`，乐观 user 消息 id 直接用
  `u-<clientMessageId>`（与服务端一致）；
- DONE 事件携带 `message_id` 时，把 assistant 占位消息 id 替换为服务端 id
  （`updateMessage` 改 id 需要新原语 `replaceMessageId(old, new)`，或占位
  消息直接以服务端 id 创建——后者需 DONE 提前，不现实；采用 replace 原语）；
- `mergeLoadedMessages`：id 精确命中为主；`(role, content)` 计数去重降级为
  legacy 兜底（仅当请求缺 `client_message_id` 时才有机会触发）。

## 批次任务

### A. 后端

- `ChatRequest` 加字段 + 校验；
- producer user 消息落库 id 规则；
- `AgentEvent`/DONE 信封加 `message_id`；
- 幂等：`u-<cmid>` 已存在且内容一致 → 复用（跳过重复 user 落库）。

### B. 前端

- 乐观 id 规则对齐；`replaceMessageId` 原语（store）；
- chatApi/类型：`client_message_id`、`message_id` 字段；
- `mergeLoadedMessages` 双轨（精确 → 计数兜底）。

### C. 测试

- 后端：id 规则、幂等复用、未传字段兼容；
- 前端：乐观 id 对齐后对账零重复、DONE 替换占位 id、旧服务端（无
  message_id）退化路径。

## 兼容与灰度

- 两分支（main/release/win7）需**同版合入**：新前端 + 旧后端混跑时
  `u-<cmid>` 不被服务端识别 → 退化为计数去重兜底（现状），无破坏；
- 旧前端 + 新后端：后端兼容未传字段 → 现状。

## 风险

- 消息 id 格式变化对 fork `at_message_id` / U5' 编辑重发的影响：
  id 仅需唯一，格式无假设（需 grep 复核无 UUID 格式断言）；
- 幂等复用与"编辑重发"的交互：编辑重发生成新 cmid，不受影响。
