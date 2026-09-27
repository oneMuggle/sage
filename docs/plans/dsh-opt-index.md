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
| R20 | C3b 收编 ALTER 防御块进迁移框架 | 本 PR | （待对齐） | 交付中 |
| R2 | SE2 读取切换 + 存量回填 + fork 钩子 | #1435（`e45dc7be`） | #1445（`aea6cad4`） | ✅ 双分支已合 |
| R3 | B2 声明式并行调度（concurrency_safe + 池屏障） | #1451（`67685820`） | #1459（`c3feb150`） | ✅ 双分支已合 |
| R4 | TM1 上下文压力计量（token meter 后端薄片） | #1462（`d545bb1f`） | #1466（`bd35e989`） | ✅ 双分支已合 |
| R5 | GT1 分发前门控链抽离（pre-execute 第一刀） | #1468（`ff654f54`） | #1471（`9edb7fd2`） | ✅ 双分支已合 |
| R6 | GT2 审批闸口抽离（ask 阶段，box 决议） | #1474（`a7591778`） | #1478（`028caea8`） | ✅ 双分支已合 |
| R7 | GT3 post-execute 段抽离（observe/反馈/错误钩子） | #1481（`2591f40e`） | #1491（`74c23a29`） | ✅ 双分支已合 |
| R8 | B3 LLM 流录制/回放（chat_stream_events 三态拦截） | #1499（`9b8bbd44`） | #1505（`cb136fb1`） | ✅ 双分支已合 |
| R9 | C3a schema 版本化迁移框架（账本 + 有序注册表） | #1512（`eac2942a`） | #1516（`33b79797`） | ✅ 双分支已合 |
| R10 | D1a 性能预算基准第一刀（长会话四路径） | #1520（`bccda663`） | #1523（`d0657ed8`） | ✅ 双分支已合 |
| R11 | TM2 上下文水位前端呈现（流事件 + 水位徽章） | #1525（`ce759b18`） | #1533（`6c1ff17b`） | ✅ 双分支已合 |
| R12 | B3b 录制/回放/投影全链路测试 + SOP §4.6-4.9 | #1546（`63c02d1c`） | #1549（`0415b194`） | ✅ 双分支已合 |
| R13 | D1b 性能预算扩展（回填/迁移空转/双写吞吐） | #1556（`8a08428b`） | #1565（`4498ec0c`） | ✅ 双分支已合 |
| R14 | C1a 记忆 API 路由组拆分（legacy_routes -770 行） | #1573（`ae591e68`） | #1589（`8e620dee`） | ✅ 双分支已合 |
| R15 | C1b 技能 API 路由组拆分（legacy_routes 累计 -1160 行） | #1595（`1e54ad68`） | #1600（`a0c9d587`） | ✅ 双分支已合 |
| R16 | C1c Skill Draft/Audit/Rollback/Consolidation 路由组拆分 | #1611（`af319496`） | #1660（`e2af8068`） | ✅ 双分支已合 |
| R17 | 稳定化 + 总账收敛 | #1664（`edcc3e17`） | #1670（`3144a482`） | ✅ 双分支已合 |
| R18 | D1c 性能预算扩展（回填/迁移/双写/压缩四路径） | #1672（`2f60985e`） | #1675（`e296aab5`） | ✅ 双分支已合 |
| R19 | TM3 键盘快捷键帮助面板 | #1684（`2c627e8b`） | #1692（`b852b2ea`） | ✅ 双分支已合 |
| R20 | C3b 收编 ALTER 防御块进迁移框架（v1 基线 + 框架完善） | #1698（`53dce7f9`） | #1702（`6ecd9a39`） | ✅ 双分支已合 |
| R21 | C3b v2 messages 表 ALTER 收编 | #1708（`4aeddfc8`） | #1709（`90041bc5`） | ✅ 双分支已合 |
| R22 | C3b v3 sessions 表 ALTER 收编 | #1711（`ceac2052`） | #1719（`23634dce`） | ✅ 双分支已合 |
| R23 | C3b v4 memories_episodic 表 ALTER 收编 | #1734（`663f8e6c`） | #1737（`28fe8b58`） | ✅ 双分支已合 |
| R24 | C2a chat_stream 四路事件推送闭包收敛为 StreamEventSink | #1744（`8141f88c`） | #1747（`1abe24d6`） | ✅ 双分支已合 |
| R25 | C1d settings/preferences 路由组迁出（legacy_routes 3977→3699） | #1750（`0b06eb12`） | #1752（`743579cc`） | ✅ 双分支已合 |
| R26 | C2b 请求窗口策略五份重复收敛为 chat_request_policy（净 -684 行） | #1757（`62d3d6eb`） | #1759（`2b162513`） | ✅ 双分支已合 |
| R27 | C1e legacy 13 个请求/响应模型归位 legacy_models.py（legacy_routes 3977→3327） | #1763（`0f756f22`） | #1767（`e73cd600`） | ✅ 双分支已合 |
| R28 | C2c 流状态注册表与中断函数迁出 chat_stream_state（legacy_routes→3270） | #1774（`2e040f50`） | #1777（`51f9471f`） | ✅ 双分支已合 |

—— 本账本由对标循环维护，随轮次追加。
