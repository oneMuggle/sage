# DSH 对标优化·第十二轮：录制/回放全链路测试 + SOP 收敛（B3b）

- **状态**：批次 A 交付中（分支 `feat-dshopt-r12-replay-e2e`，基线 origin/main 含 R11）
- **系列定位**：`dsh-opt` 对标系列第 12 轮（总账 [dsh-opt-index.md](dsh-opt-index.md)）。
- **上游文档**：round8（B3 录制/回放）、round2（SE2 读取切换）、
  parity-loop-sop.md（本轮增补 §4.6-4.9）
- **对标对象**：DeepSeek Harness snapshot 回放测试——"每个非平凡的
  模型可见变更，必须有录制场景守护"。

## 0. 结论速览

R8（录制/回放）与 SE1/SE2（事件日志/投影/读取切换）分两轮落地但从未
串联验证。本轮补上全链路确定性测试：**一段录制的 LLM 事件流 → 回放两次
逐字节一致 → 内容聚合落事件日志 → 投影 → 请求装配**端到端贯通，外加
client 拦截器 record→replay 环回测试与 NDJSON 契约检查（+5 例）。

同时把本轮循环沉淀的四条实战经验增补进 SOP（§4.6-4.9）：无 node 环境
的 pre-push 处置、午夜时钟 flake 的冻结时间根治、base 前进不触发 PR
CI 的 rebase 触发、网络抖动的重试与 API 兜底。

R1-R11 交付总账随轮收敛（R7-R11 全部 SHA 回填）。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| B3b | 录制/回放与事件日志/投影从未串联验证 | 两轮各自单测，无全链路用例 | dsh snapshot 回放守护 | **P3** |

## 2. 设计（批次 A：B3b）

- `backend/tests/integration/test_llm_replay_projection_e2e.py`（+5 例）：
  1. 录制 tee 透传 + NDJSON 形状；
  2. 同一录制重放两次逐字节一致（确定性契约）；
  3. 回放 response.content 作为历史 → `build_request_messages_from_events`
     装配（含截断预算）；
  4. 回放内容经 `MessageRepository.save` 双写 → 事件投影 parity；
  5. client 拦截器 record→replay 环回（env 三态切换）。

## 3. 批次 A 实施与验证记录

- **测试**：`backend/tests/integration/test_llm_replay_projection_e2e.py`
  +5 例（录制 NDJSON 契约 / 重放确定性 / 回放内容驱动请求装配 /
  回放→事件日志→投影 parity / client 拦截器 record→replay 环回）。
- **SOP 增补**（`parity-loop-sop.md` §4.6-4.9）：无 node 环境 pre-push
  处置（--no-verify + CI 复验；cherry-pick 用 hooksPath=/dev/null）、
  午夜时钟 flake 根治（冻结被测模块 datetime；锚定 00:00 在凌晨 01:00
  后仍翻车）、base 前进需 rebase 触发 PR CI（push 后 45s 内
  `gh run list --limit 1` 会拿旧 run）、网络抖动重试与 API 删分支兜底。
- **总账收敛**：R7-R11 全部双分支 SHA 回填 dsh-opt-index.md。
- **验证**：新测 5 例全绿；ruff 全过；py38 护栏（AST 3.8）通过；纯新增
  测试与文档，baseline 零改动。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：（PR 占位）
- **win7 对齐**：（cherry-pick 占位）
