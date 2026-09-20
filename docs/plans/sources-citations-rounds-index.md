# 聊天参考来源专项·双分支交付总账（R81-R87 索引）

> 本文件是「统一参考来源 / 引用溯源」专项循环（分析 → worktree → 实施 →
> PR → CI 绿 → merge → win7 对齐 → 清理）的交付总账，体例对齐
> `parity-rounds-index.md`。专项起点：R81（回答下方列出命中的记忆/知识库/
> 搜索等来源，类文章引用，供用户核对可靠性）。

## 1. 交付轮次索引（main PR / win7 PR / squash SHA）

| 轮 | 主题 | main | win7 |
| --- | --- | --- | --- |
| R81 | 统一参考来源区块（sources_extractor + sources_used 事件 + rag_citations/sources 落库回读 + 前端统一折叠区块） | #1259 `6a8eba0c` | #1264（py38 适配：无 r66/r71，捕获沉睡、列对齐） |
| R82 | L13 记忆注入去重（双倍 token + 段隔离失效）+ 唯一性护栏测试 | #1267 `1f38a78f` | #1271 |
| R83 | sources_used 增量推送（STEP_DONE 边界快照，仅新增时推） | #1275 `d2f8cb69` | #1279 |
| R84 | producer 级集成回归（事件→落库→回读 + 无工具负例） | #1282 `9801414a` | #1288（win7 版测试适配：无 STEP_DONE，断言 done 全量兜底） |
| R85 | 重接路径 sources_used 载荷校验对齐主路径 MEDIUM-2 口径 | #1286 `240da05b` | #1288（合并对齐） |
| R86 | @memory:/@wiki: 实体引用命中纳入统一来源（process_with_sources 一次解析两用；kind 增 memory） | #1292 `b49f6926` | #1295 |
| R87 | browser_navigate 纳入来源 + 重接路径 memory_used/attachment_rag_used 校验收口 | #1296 `6cf0ed89` | #1299 |
| R88 | 专项总账（本文件） | #1301 `b6823cb7` | 文档无需对齐 |
| R89 | merge_sources 去重改为补齐合并（navigate→fetch 同 url 摘要不丢）；附带 py38 replan 测试 loop 兜底 | #1304 `0c2a4de2` | #1305 `0c0548b1` |
| R90 | 实体 wiki 来源补 score + browser_navigate 集成用例 + 本回填 | —（本 PR） | 文档随代码无需单独对齐 |

## 2. 专项方案要点（R81 管道全景）

```
注入/检索路径                                结构化来源                    前端统一区块分组
─────────────────────────────────────────────────────────────────────────────
memory_used（记忆召回注入）                → memory_refs（已有）        → 记忆
attachment_rag_used（附件 RAG，r71）       → rag_citations（已落库）    → 附件检索
web_search / web_fetch / browser_navigate ┐
wiki_search / wiki_answer                  ├→ sources_extractor → r81_turn_sources → 记忆引用(@memory)/知识库/网页
mcp__<server>__<tool>                      ┘   （OBSERVING 全文解析）      → 工具
@memory: / @wiki: 实体引用（S3）           → entity_refs.sources        → 记忆/知识库
```

- 事件：`sources_used`（STEP_DONE 增量 + DONE 前全量兜底），前端整体替换语义、幂等。
- 落库：`messages.rag_citations`（首条 assistant 行）与 `messages.sources`（终稿行）
  均为 JSON-in-TEXT，fork 随行复制，`GET /sessions/{id}/messages` 回读。
- 提取器全 fail-safe：畸形 JSON/未知工具一律空列表，绝不影响对话主流程；
  去重键 web=url、wiki=path、memory=title、tool=(server,tool)，总量 cap 50。

## 3. STEP_DONE（step-by-step 事件流）向 win7 同步——可行性分析结论

win7 缺口是**三层联动**，非单点：

1. `agent_state.py`：缺 `STEP_DONE` 枚举成员与 `AgentEvent.step_index` 字段；
2. `agent.py`：无 STEP_DONE 产出（main 在并行/串行迭代边界各 yield 一次）；
3. producer：`steps_completed` 计数缺失（多步落库时 `message_count` 增量公式不同）；
4. 前端：useChat 的 step_done 换气泡 / chatStreamStore.completedSteps 快照机制未同步。

**结论**：工作量 ≈ 在 win7 重做一轮完整的 step-by-step（多文件联动 + 多步落库
语义 + 用户可见的消息分桶行为变化），且 win7 的 run_loop 不产 step_done，
R83 增量推送在其上是沉睡代码（DONE 前全量兜底有效，功能不缺、只是不增量）。
**不宜自主盲改，标记为需维护者拍板的候选项**。

## 4. 过程经验（专项循环沉淀）

1. **worktree 清理 + node_modules junction 穿透删除**：Windows 下为跑
   前端测试在 worktree 里 `mklink /J node_modules` 指向主树后，
   `git worktree remove --force` 会**穿透 junction 清空主树 node_modules**
   （本专项实证两次）。清理前必须先 `rmdir <worktree>\node_modules` 删除
   junction 本体；恢复用 `npm ci`（锁文件齐全，43s）。
2. **GitHub 直连不稳**：push/fetch 间歇 `SSL_read: Connection was reset`。
   本机系统代理在 `127.0.0.1:7890`，用 `git -c http.proxy=... push` 单次
   参数（不改全局配置）稳定。
3. **双分支测试适配**：同一测试文件在 main/win7 行为不同时（如本专项
   STEP_DONE 差异），win7 版按其真实行为改写断言并在注释里写明差异原因，
   不共享文件名不同内容之外的魔法。
4. **CI ruff 版本差异**：本地 `ruff check` 过 ≠ CI 过（PLW2901 在 CI 侧
   规则集更严），提交前用与 CI 相同 rule target 复核。

## 5. 后续优化建议（候选项，非承诺）

1. **wiki 正文内联 [S1] 引用编号**（专项二期，需产品拍板 prompt 方案与
   未标记降级策略）。
2. **loadMessages 长会话分页**：当前 `limit=100000` 全量加载，长会话首屏
   与内存成本随历史线性增长（改动涉及 mergeLoadedMessages 对账语义，需
   单独立项）。
3. **memory 检索合一**：producer 现存 `get_context`（注入）+ `recall`
   （召回事件）两次检索，可让 MemoryManager 暴露"一次检索、两种形态"。
4. **STEP_DONE 全量同步 win7**（见 §3，需拍板）。
5. **orchestration 编排模式的来源聚合**：单 agent 模式已覆盖；多 agent
   编排如需 per-task 来源，需扩展 ChatDispatcher 事件投影。

—— 本账本由参考来源专项循环维护，随轮次追加。
