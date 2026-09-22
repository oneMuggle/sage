# 对标循环总账 R90-R99 —— 交付索引 + 分析与优化建议

日期：2026-09-22 ｜ 覆盖窗口：2026-09-20 ~ 2026-09-22（r90 批次起）

## 一、交付索引

| 轮次 | PR | main | win7 | 内容一句话 |
| --- | --- | --- | --- | --- |
| r90 | #1309 | ✓ | — | promptApi/mcpClient/agentsApi/runtimeApi/messageApi 37 用例（API client 测试第一批收口） |
| r91 | #1314 | ✓ | ✓→#1318 | xdist 事件循环兜底 fixture + set_event_loop(None) 污染源修复（#1305 连爆面根因） |
| r92 | #1318 | — | ✓ | R89 来源去重 cherry 回移 win7（R89 主 PR #1304 的 win7 对齐） |
| r93 | #1319 | ✓ | — | worktreeApi/journalApi/learnApi/attachmentRagClient 27 用例（第二批收口） |
| r94 | #1377 | ✓ | — | **真 bug 修复**：Zotero 设置路径持久化断链（不存在的模块/类名 + KEYS 白名单缺 key）+ 路由/client 测试 17 用例 |
| r95 | #1388 | ✓ | — | Zotero MCP server 7 工具分发 12 用例（可选导入恒等装饰器直测模式） |
| r96 | #1393 | ✓ | — | orchEvents 类型守卫 + orchEventStream NDJSON 流 16 用例 |
| r97 | #1397 | ✓ | — | utils/desktopEvent/demoFlag 19 用例（第三批收口） |
| r98 | #1400 | ✓ | — | ZoteroTab UI 7 用例（状态卡片/路径保存/防抖搜索/详情批注） |
| r99 | 本 PR | — | — | desktopInvoke 错误漏斗全分支 10 用例 + 本总账 |

累计：10 个批次 PR、约 160 个新测试用例、2 个真 bug 修复、1 次架构基线重算。

## 二、过程中修复的真 bug（非测试性发现）

1. **R89 win7 cherry CI 连爆**（#1305 实证）：`test_subagent_events.py` 在
   finally 里 `set_event_loop(None)` 毒化 xdist worker；新增测试文件位移
   loadfile 分桶使 `test_replan_tool.py` 27 例连爆。main 侧修复（#1314）后
   win7 cherry 回移（#1318）。
2. **Zotero 设置路径持久化断链**（#1377）：`zotero_routes.py` import 不存在的
   `backend.services.settings_repo.SettingsRepo`（实际为
   `backend.data.settings_repo.SettingsRepository`），且 `zotero_db_path`
   不在 KEYS 白名单。症状为设置页配置静默丢失、`POST /path` 落库失败仍返回
   `ok:true`。#1367 落地时路由测试缺位所致——本轮回填。

## 三、基建踩坑与沉淀（循环 SOP 补充）

- **node_modules junction 协议**：worktree 借用依赖必须 junction → 跑完立即
  `rmdir` 摘除，且顺序先于任何 `git worktree remove`（git 删除会穿透 junction
  清空目标内容，r90 轮实证，事后 npm ci 恢复）。
- **ruff 版本对齐**：CI 用 ruff 0.4.4，与新版行为差异大（PT022/PT023/I001、
  UP045 噪声等）。本地用隔离目录安装 `ruff==0.4.4` 直调二进制（`python -m ruff`
  可能解析到系统新版本，需 `bin/ruff.exe --version` 校验），只查改动文件、
  绝不带 `--fix` 全仓跑。
- **网络降级通道**：git push/fetch 间歇卡死时，`gh api`（blob→tree→commit→ref）
  可完成远端提交与分支删除；push 超时后先核对远端 head 再决定是否重推。
- **Windows 本地跑不动的验证**：architecture-check 的路径分隔符、
  backend 全量 pytest 的依赖面——以 CI 为准，本地只做机制级复现与
  py_compile/单文件 lint。

## 四、优化建议（后续循环候选）

1. **测试面**（低垂果实已尽）：
   - demoChatScript.ts（324 行）演示数据维持不测——价值密度最低；
   - orchEventStream 的 Electron IPC relay 分支（listen 队列/error 通道）需
     jsdom window stub，可作独立批次；
   - 后端可对 `backend/mcp/http_client.py` 的 OAuth bearer 注入与刷新做
     respx 层单测（纯函数 oauth.py 已有 r60 覆盖）。
2. **基建**：
   - `backend/requirements-optional.txt` 的 `mcp` 包若纳入 CI 环境，
     MCP server 侧 handler 注册路径（非恒等装饰器）即可测——当前只测直调面；
   - architecture-baseline.json 棘轮被并发 PR 多次击穿（R94/R98 轮两次红），
     建议在 PR 模板/CI 失败信息中显式提示"改大文件须拨基线"；
   - `settings_repo.KEYS` 白名单可加启动期校验：路由代码里出现的
     `repo.get("xxx")` 字面量若不在 KEYS 内直接 fail-fast（防 Zotero 类断链复发）。
3. **流程**：
   - win7 对齐仅需 bug fix；R94 的 Zotero 断链修复因功能未回移 win7 而无需
     cherry——维持现状即可；
   - 并发会话共用 GitHub 网络时 push 高频抖动，gh api 兜底通道已验证可行，
     建议循环 SOP 固化该降级路径。
