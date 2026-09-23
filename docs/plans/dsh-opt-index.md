# DSH 对标优化系列总账（dsh-opt）

> 对标对象：[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)
> （"everything-is-a-plugin" agent harness）。本账本由 dsh-opt 循环维护，
> 随轮次追加；循环 SOP 沿用 [parity-loop-sop.md](parity-loop-sop.md)。

## 1. 系列路线（源自 2026-09-23 差距分析）

参考 dsh 的六个机制映射 sage 短板（详见各轮计划文档）：

| 机制 | sage 现状痛点 | 计划轮次 |
| --- | --- | --- |
| "Model-visible ⟺ logged" append-only 事件日志 | messages 表被压缩就地删行，唯一事实源可变 | **R1（SE1）** 地基 + R2 读取切换 + compaction surface-op |
| token-meter（重放日志确定性估算） | 32K/256K 字符截断 + 阈值×3，四处独立预算逻辑 | R3 |
| 工具五段管线（审批/超时是监听者） | 审批硬编码在 run_loop（agent.py:1640-1700） | R4-R5 |
| isConcurrencySafe 声明式并行调度 | 批级"全有全无"并行（agent.py:651，仅 READ 批） | R6 |
| Capability Seam 三角色拆分 | legacy_routes.py 5,463 行装配+路由+流管理混杂 | R7+ |
| 性能预算即 CI 门（按用户路径） | E2E 分层好但无数值预算 | R8+ |

## 2. 交付总账

| 轮 | 差距 | main PR | win7 PR | 状态 |
| --- | --- | --- | --- | --- |
| R1 | SE1 会话事件日志地基 + 双写 + 投影 parity | #1421（`1faaa49e`） | #1425（`8194fc78`） | ✅ 双分支已合 |
| R2 | SE2 读取切换 + 存量回填 + fork 钩子 | #1435（`e45dc7be`） | #1445（`aea6cad4`） | ✅ 双分支已合 |
| R3 | B2 声明式并行调度（concurrency_safe + 池屏障） | #1451（`67685820`） | #1459（`c3feb150`） | ✅ 双分支已合 |
| R4 | TM1 上下文压力计量（token meter 后端薄片） | #1462（`d545bb1f`） | #1466（`bd35e989`） | ✅ 双分支已合 |
| R5 | GT1 分发前门控链抽离（pre-execute 第一刀） | #1468（`ff654f54`） | #1471（`9edb7fd2`） | ✅ 双分支已合 |
| R6 | GT2 审批闸口抽离（ask 阶段，box 决议） | 本 PR | （待对齐） | 交付中 |

—— 本账本由对标循环维护，随轮次追加。
