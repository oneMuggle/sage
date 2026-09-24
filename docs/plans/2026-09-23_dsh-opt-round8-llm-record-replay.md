# DSH 对标优化·第八轮：LLM 流录制 / 回放（B3）

- **状态**：批次 A 交付中（分支 `feat-dshopt-r8-llm-record-replay`，基线 origin/main 8b27eaf6 之后）
- **系列定位**：`dsh-opt` 对标系列第 8 轮（总账 [dsh-opt-index.md](dsh-opt-index.md)）。
- **上游文档**：round1-7（SE1/SE2/B2/TM1/GT1/GT2/GT3）
- **对标对象**：DeepSeek Harness 的 `llm-replay`——录制/回放挂在 LLM 流的
  **唯一拦截点**，测试跑真实录制会话而非 mock。

## 0. 结论速览

sage 的 LLM 流出口是 `LLMClient.chat_stream_events`（结构化事件元组）。
本轮把它改造成三态拦截器（生产行为零变化）：

- `SAGE_LLM_REPLAY_DIR=<dir>`：回放——不联网，按序重放录制目录的事件流
  （含 error 行的原位失败重现）；
- `SAGE_LLM_RECORD_DIR=<dir>`：录制——真实请求照常发出，事件流 tee 到
  `rec_NNNN.jsonl`（NDJSON，每会话一个文件，按序追加）；
- 均未设：直接透传 `_chat_stream_events_raw`（原方法体整体改名）。

录制文件即"真实会话快照"——为后续投影 parity、E2E 重放测试、离线开发
提供输入源（dsh 的 snapshot 回放测试同款输入形态）。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| B3 | LLM 流无录制/回放，测试只能 mock | llm_client.py 无拦截点 | dsh llm-replay 挂 stream waterfall | **P2** |

## 2. 设计（批次 A：B3）

- `backend/core/legacy/llm_record_replay.py`：
  - `record_stream_events(dir, source)`：tee 生成器——事件原样透传 +
    NDJSON 落盘（content_delta / reasoning_delta / response 三类，response
    经 asdict+JSON 往返保证可还原）；异常写 `error` 行后原样上抛；
  - `replay_stream_events(dir)`：按文件名排序逐文件重放；`error` 行在
    原位置抛 `LLMError(SERVER_ERROR, …)` 重现失败路径；目录无录制文件抛
    `LLMError(PARSING, …)`（绝不静默编造内容）。
- `chat_stream_events` 三态切换（方法体改名 `_chat_stream_events_raw`），
  拦截逻辑全部惰性 import（零环）。

## 3. 批次 A 实施与验证记录

- **模块**：`llm_record_replay.py`——`record_stream_events`（tee +
  NDJSON 落盘 + error 行）/ `replay_stream_events`（按序还原 +
  error 原位抛 `LLMError(SERVER_ERROR)` / 空目录抛 `LLMError(PARSING)`）。
  response 经 asdict + JSON 往返，tool_calls 还原为 `LLMToolCall` 对象。
- **拦截器**：`chat_stream_events` 三态（env 均未设 → 直接透传 raw，
  生产行为零变化）；方法体改名 `_chat_stream_events_raw`；拦截逻辑
  惰性 import（零环）。
- **测试**：+8 例（tee 透传与 NDJSON 形状 / 回放按序还原含
  LLMToolCall 类型 / error 行原位抛错 / 空目录 / 多会话递增文件 /
  replay 模式不触网 / record 模式 tee / 旁路零行为）。
- **验证**：新测 8 例全绿；ruff 全过（SIM115 加 noqa——录制句柄须跨
  async yield 存活，with 语义不适用）；py38 护栏（compat_rewrite
  --check 0 变更 + AST 3.8）通过；baseline 同步（llm_client.py 1074）。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：（PR 占位）
- **win7 对齐**：（cherry-pick 占位）
