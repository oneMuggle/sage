# 主流 AI 软件对标分析与优化建议（2026-09-27）

> 参照对象：Claude Code（含 /rewind 检查点）、Cursor（Checkpoints）、Cline
> （Checkpoints）、Windsurf（Cascade）、Codex CLI、Copilot Chat、Zed AI。
> 方法：先盘 sage 现有功能面（见 §1），再列差距（§2），按「价值 × 成本 ×
> 与并行会话冲突风险」排序（§3），本批实施 W1（§4）。

## 1. sage 功能面现状（事实盘点）

已有能力（抽样证据）：编辑重发（fork 语义，`Message.tsx`）、从此处分叉
（`handleFork`）、@文件/实体引用、18 个斜杠命令 + 模板库、上下文水位徽章
（TM2）、任务树/子代理实时面板/事件时间线、Changes 快照恢复 + hunk 级撤销
（U19）、DocumentPreview、终端面板、命令面板、会话导出（HTML/MD）、
OS 通知、多端点配置 + 单一 fallback_model。

## 2. 差距清单（对标主流工具）

| # | 差距 | 对标 | 价值 | 成本 | 冲突风险 |
|---|---|---|---|---|---|
| G1 | **消息↔文件快照联动回滚**：消息级「回滚到此处」统一入口（对话/文件/两者）。现有 fork 与 checkpoint 恢复是两座孤岛，用户需自己判断哪个快照对应哪条消息 | Claude Code /rewind、Cursor Checkpoints | 高 | 中 | 低（纯前端组装现有原语） |
| G2 | 显式有序 **failover chain**（多模型降级链）；现仅单一 fallback_model 偏好 | OpenRouter/LiteLLM 语义、Cursor model fallback | 中高 | 中高（动 legacy_routes 端点选择，C1a/b 拆分进行中） | 高 |
| G3 | 统一 **快捷键注册表** + 速查面板（? 呼出）；现快捷键散落各组件 | Cursor/Claude 全员标配 | 中 | 中 | 低 |
| G4 | ZCode 借鉴 **Phase 4 剩余**：Diff 单文件 accept/reject、inline↔split 切换（U19 已覆盖 hunk 级撤销） | Cursor diff UX | 中 | 中 | 中（ChangesSection 常被并行批次触碰） |
| G5 | 检查点时间线 UI（右面板快照列表加消息锚点提示） | Cursor checkpoint 时间线 | 中低 | 低 | 低 |

## 3. 排序与规避

- **W1 = G1**：三块原语（`session_fork` per-message、
  `workspace_list_checkpoints`、`workspace_restore_checkpoint`）全部现成，
  只缺组装；纯前端 + i18n + 测试，零后端改动，避开 legacy_routes 拆分战区。
- G2 在并行会话 Capability Seam 拆分（DSH-R7+）收敛前不动 `legacy_routes`。
- G3/G5 作为后续批次；G4 等 ChangesSection 稳定窗口。

## 4. W1 实施方案：消息级「回滚到此处」

### 交互设计
- `Message` 悬停操作区新增「回滚到此处」按钮（`onRewind(messageId)`）。
- 点击打开 `RewindDialog`：
  - 范围单选：**对话+文件**（默认，当存在 `created_at <= 消息时间` 的快照）/
    **仅对话**（无匹配快照时唯一选项）。
  - 快照单选列表（新→旧，含时间与文件数），默认选中最近合格快照。
  - 确认执行：先 `restoreCheckpoint`（失败则中止并 toast，可改选仅对话），
    再 `sessionApi.fork(sessionId, messageId)` 切入分叉会话（原会话保留，
    契合「透明可控」哲学；与编辑重发同一语义）。
- 仅 assistant 消息同样可用（回滚的是"这条之后"的状态，语义为回到该消息
  刚完成的时点）。

### 实现边界
- 纯前端：`Message.tsx`（+1 按钮 +1 prop）、`Chat.tsx`（+handler）、
  新组件 `src/widgets/chat/rewind/RewindDialog.tsx`、i18n zh/en、
  `RewindDialog.test.tsx`。
- 时间匹配：checkpoint `created_at`（本地时区字符串）`Date.parse` 后与
  `message.created_at`（epoch ms）比较；同机本地时间，v1 足够，UI 明示
  快照时间供人工确认。
- 不做：文件态 diff 预览（G4 范畴）、破坏性截断（与哲学冲突，fork 替代）。

### 验收
- `RewindDialog.test.tsx`：快照列表渲染/默认选中/无快照降级/确认调用序列
  （先 restore 后 fork）/restore 失败中止。
- 既有 Message 测试不回归；tsc、eslint、vitest 全绿。

## 5. 后续批次（backlog）

- W2：G3 快捷键注册表 + 速查面板。
- W3：G5 检查点时间线（右面板快照列表加消息锚点/跳转）。
- W4：G2 failover chain（等 legacy_routes 拆分收敛后）。
- W5：G4 Diff 剩余增强。
