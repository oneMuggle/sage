# ZCode 产品对标差距分析（功能 / UI / 逻辑）

> 日期：2026-09-24 ｜ 参照：`E:\ProgrammingData\electron\ZCode` 产品面全量调研
> 用途：为后续对标轮次（R 系列 / RD 系列）提供经过核实的候选清单。
> **状态标注**：✅ sage 已有 ｜ 🟡 部分有 ｜ ❌ 缺失（本清单只收 ❌/🟡）。
> 所有「缺失」判定均经 sage 源码 grep 核实（非凭印象）。

## 一、功能类缺口

| # | ZCode 功能 | ZCode 证据 | sage 现状 | 规模评估 |
|---|---|---|---|---|
| F1 | **会话自动归档**（3/7/14/30 天不活跃自动归档 + 一键清空全部归档） | `settings.taskAutoArchive*`（en-US.ts:1938-1947）、`DeleteAllArchivedTasksButton.tsx` | `is_archived` 原语齐全（repo/路由/前端切换视图），缺 sweep 与清空 | 小：后端 2 端点 + 前端设置/按钮 |
| F2 | **检查点 / 文件回滚**（对话内 Checkpoint 节点 + rewind 对话框，区分不可回滚原因） | `components/ai-elements/checkpoint.tsx`、`ConversationFileRewindDialog.tsx` | 无 rewind 概念；依赖 agent 循环落检查点 | 大：需 agent 循环 + 存储协议配合 |
| F3 | **模型轨迹查看器**（完整 trajectory：时间线/搜索/工具 payload/角色样式） | `ModelTrajectoryPane.tsx` 等 | 有 run trace（arena 域）与事件日志，无聊天轨迹 UI | 中：数据已有（事件日志），缺 UI |
| F4 | **跨会话任务查找器**（TaskFindDialog：按标题/内容全局跳转） | `quickpick/TaskFindDialog.tsx` | 有跨会话消息搜索（F12），无会话级跳转面板 | 小-中 |
| F5 | **未读任务计数 + 应用徽标**（按任务/窗口汇总到 Dock/托盘） | `lib/unreadTaskCount.ts`、`desktop/unreadBadge.ts` | 右面板有局部未读概念；无会话未读 + 托盘徽标链路 | 中 |
| F6 | **任务自动归档策略可配**（关闭/3/7/14/30 天） | 同 F1 | 同 F1 | 见 F1 |
| F7 | **外部会话导入**（Claude History 迁移向导） | `settings/MigrationSection.tsx`、`ExternalAgentImportDialog.tsx` | 无（格式不同，需评估） | 大 |

## 二、UI 类缺口

| # | ZCode UI | ZCode 证据 | sage 现状 | 规模评估 |
|---|---|---|---|---|
| U1 | **轮次导航器**（多轮间快速跳转） | `ConversationTurnNavigator.tsx` | R120 已做消息定位/大纲（部分覆盖）；无独立轮次导航 | 小（R120 基础上） |
| U2 | **分屏 Workbench**（会话 Pane 拆分/拖放/多会话并排） | `WorkbenchPane.tsx`、`paneLayoutTree.ts` | 无 | 大 |
| U3 | **白板**（手绘 + 加入对话发给模型） | `WhiteboardPane.tsx` | 无 | 大 |
| U4 | **内嵌浏览器 Tab**（favicon/缩放/截屏/人工接管） | `browser-use/` | 无（sage 有文件预览 Pane，无浏览器） | 大 |
| U5 | **侧边 Pane 体系**（git/terminal/browser/白板/treemapping 多 Tab 右栏） | `App.tsx:410` | 有 RightPanel（单列），无多 Tab Pane 体系 | 中-大 |
| U6 | **可搜索快捷键绑定表**（自定义快捷键） | `ShortcutSettingsSection.tsx` | 有快捷键集合，无自定义/搜索 UI | 中 |
| U7 | **Onboarding 职业选择向导** | `OccupationOnboarding.tsx` | 有 OnboardingWizard（形态不同，可借鉴） | 小 |
| U8 | **分组虚拟化任务列表**（粘性组头/拖拽） | `workspace-grouped-tasks/` | 有分组侧栏（ConversationsSection 等 7 section） | 中 |

## 三、逻辑类缺口 / 健壮性

| # | ZCode 逻辑 | ZCode 证据 | sage 现状 | 备注 |
|---|---|---|---|---|
| L1 | **权限作用域分级**（允许一次 / 本项目始终允许 / 会话级；Deny 附文字反馈） | `PermissionDialog.tsx`、`ZCodePermissionOption.display/freeText` | 有 M1 审批对话框；作用域分级与文字反馈待核对补齐 | 中 |
| L2 | **排队输入语义分级**（startNow / queue / guide 三种投递） | `session.port.ts:295` | #1334 已有排队/插话/打断三通道 | ✅ 基本对齐 |
| L3 | **运行状态恢复**（启动时 recover 僵死运行态） | — | sage 已有 `recover_stale_run_states`（session_repo） | ✅ |
| L4 | **Worktree 感知状态卡**（会话卡展示 git worktree 行级变化） | `conversationStatusPanelModel.ts:148` | 无（git 状态在独立面板） | 中 |
| L5 | **动态工作流**（DWF：模型驱动编排 + 侧 Pane 可视化） | `packages/dynamic-workflow/`、`WorkflowRunSidePane.tsx` | 有编排（orchestration），无模型定义的动态工作流 | 大 |

## 四、建议的实施顺序（供对标轮次参考）

1. **F1 自动归档 + 清空归档**（本轮实现）——小而完整，用户可感知。
2. **U1 轮次导航器**（在 R120 基础上）+ **F4 任务查找器**——小-中，纯前端。
3. **L1 权限作用域分级**——先核对 sage 现状再补齐。
4. **F3 轨迹查看器**——数据已有，缺 UI。
5. **F2 检查点/回滚、U2 分屏、L5 动态工作流**——大工程，需单独立项。

> 维护约定：每完成一项，把行内状态从 ❌ 改 ✅ 并附 PR 号；新增发现追加行。
