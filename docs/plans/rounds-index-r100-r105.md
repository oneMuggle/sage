# 对标循环总账 R100-R105 补遗 —— 交付索引 + 阶段分析与后续建议

日期：2026-09-23 ｜ 前篇：`rounds-index-r90-r99.md`（该篇第四节建议的落地情况见下）

## 一、交付索引（R100-R105）

| 轮次 | PR | 内容一句话 |
| --- | --- | --- |
| r100 | #1408 | SettingsRepository KEYS 白名单 AST 守卫（R94 复盘建议落地，3 用例） |
| r101 | #1412 | orchEventStream Electron IPC relay 分支测试（5 用例）+ database.py 基线拨正 |
| r102 | #1415 | HttpClientMcpClient OAuth 注入/刷新/自愈测试（7 用例，MockTransport 注入） |
| r103 | #1423 | transparencyPayload 载荷校验器测试（11 用例，含 sources 非空契约锁定） |
| r104 | #1432 | HttpClientMcpClient SSE 解析路径测试（8 用例，r102 遗留项收口） |
| r105 | #1437 | architecture-check 棘轮门禁失败输出补修复指引（流程 DX，见前篇建议 2） |

## 二、前篇建议落地核对

| 前篇建议 | 状态 |
| --- | --- |
| mcp/http_client.py OAuth respx 测试 | ✅ r102（含 r104 补 SSE 路径） |
| orchEventStream 深层分支 | ✅ r101（IPC relay 分支；direct 路径 r96 已覆盖） |
| KEYS fail-fast 校验 | ✅ r100 以 AST 守卫形式落地（运行时校验暂缓，守卫覆盖同一风险面） |
| 棘轮击穿的流程防线 | ✅ r105 失败输出补修复指引 |
| mcp 可选依赖纳入 CI | ⏸ 未做：py38 兼容面与 conda env 变更风险大，建议单独评估 |

## 三、阶段分析（R100-R105）

1. **测试面进入维持态**：shared/api 全覆盖（demoChatScript 按设计不测）、
   Zotero 全栈、MCP HTTP/SSE/OAuth、编排事件流、KEYS 守卫均已闭环。
   后续测试类批次应主要跟随**并发会话新增代码**（如 DSH-R1 session_events
   已自带 424 行测试，质量良好）。
2. **时间敏感测试 flake 模式**：R102 轮两次 CI 红均因
   `test_todo_service` 的真实时钟依赖（23:00-23:59 跨午夜），#1417 已用
   时钟冻结修复。后续新增时间相关测试应一律冻结时钟，禁用裸 `now()`。
3. **棘轮门禁 DX 已闭环**：r105 后门禁失败自带修复指引（含目标行数与
   棘轮单向性红线），预期不再出现"红 main 迭代定位"的损耗。

## 四、后续建议（R106+ 候选）

1. **测试类**（跟随增量）：
   - `session_events` 后续轮次（SE2+）落地时按 #1421 的测试口径跟进；
   - `backend/wiki/mcp_server.py`（613 行）目前仅安全路径有测试，可参照
     Zotero MCP server 的恒等装饰器直测模式补 handler 面。
2. **基建类**：
   - `mcp` 依赖纳入 CI env 的可行性评估（py38 兼容 + conda env 漂移）；
   - `settings_repo.KEYS` 运行时校验暂缓维持（AST 守卫已覆盖）。
3. **流程类**：
   - gh api 兜底通道（blob→tree→commit→ref）已多次验证，应对 git 网络抖动
     的标准降级路径，维持；
   - non-blocking job（legacy smoke）失败不挡门禁，但连续失败值得在
     总账跟踪，避免长期漂移。
