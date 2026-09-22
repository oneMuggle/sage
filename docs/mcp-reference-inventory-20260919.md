# Sage reference 盘点与分阶段计划

日期：2026-09-19
范围：用户选择先盘点、再确定实现范围；本轮不修改业务代码，不启动真实注册或抽卡。
基线：main / 673548b9。以下为静态盘点，不是完整代码审计或运行验收。

## 1. 结论

不能从零重写，也不能把既有 P0–P5 文档的完成声明等同于当前应用已经端到端可用。当前主要资产分为已合并主线、main 中大量未提交修改、一个注册测试 stash。参考目录包含两套产品，旧 ArenCard 计划并未覆盖 C# 模型助手全部用户体验。

## 2. Git 与历史工作

已枚举 git worktree list --porcelain 返回的所有 worktree，并逐个检查 Arena/reference 相关未提交路径及最近相关提交。包括 .worktrees 下各开发目录、四个 Qoder worktree 及 sibling sage-sources。没有在这些其他 worktree 的路径筛选结果中发现新的 Arena 未提交工作；这不排除名称无关的文件内仍有相关逻辑。

全 refs 提交信息检索发现：

| 提交 | 工作 | 处理建议 |
|---|---|---|
| bbf594dc / #1030 | automation + model probe，历史 27 commits 汇总 | 复用现有基础，不重复 cherry-pick |
| de8f3225 / #1211 | 单账号注册辅助、邮箱 provider、被动模型观测、账号管理面板 | 当前 main 历史已有 |
| 4c0019c4 / #1213 | 上述能力的 Win7 同步及 Python 3.8 适配 | 独立兼容基线，不覆盖 main |
| fa77259e / #1224 | temporary_mail 测试补齐 | 后续跨通道回归时对照 |
| 1d99b0aa / #1179 | Windows SQLite 文件锁测试修复 | 保留测试清理语义 |
| stash@{0} / e6a7302b | local expanded test_arena_registration | 只读比对，禁止直接 pop 覆盖已暂存测试 |

分支名/分支 tip 描述筛选未发现 Arena 命名的专用分支；结论仅针对当前本地已知 refs，未 fetch 远端，也未对每一分支做全量内容差异审计。

当前 main 未暂存的已跟踪差异：18 文件，1461 additions / 48 deletions；暂存区另有注册测试差异，464 additions / 324 deletions。这些数字不包含大量 untracked 新文件，且工作区可能被其他会话继续修改。

主要未提交资产：
- backend/services/arena_{protocol,http,jobs,keystore,proxies,proxy_relay,token_cache,trace_ext,draw_engine}.py
- backend/services/temporary_mail/tenminmail.py 与 backend/utils/machine_id.py
- backend/api/arena_routes.py、backend/config/arena_automation.py、backend/services/arena_accounts.py 的扩展
- electron/arenaTokenWindow.ts 及测试、main/preload/types 接线
- src/pages/Arena.tsx、src/widgets/arena 下任务和状态组件、src/entities/arena/api.ts
- 配套 Python/React/Electron 单元测试及 docs/mcp-arena-p0-verification.md 至 docs/mcp-arena-p5-ui.md

整合纪律：不 reset、不 checkout 覆盖、不清理 untracked、不 pop stash、不提交其他人的改动。若进入实现，先记录文件归属和差异快照，再单独批准并实施整合。

## 3. 两套参考能力与现有覆盖

状态“已见”表示存在源码或接口，不表示运行验收通过。“待补齐”仅针对检查到的 Arena 专用界面/服务；实施前仍需检索 Sage 通用组件以复用。

| 能力 | 参考依据 | Sage 当前证据 | 判断 |
|---|---|---|---|
| 账号管理、隔离、单账号辅助 | 两套参考 | arena_accounts.py、arena_registration.py、AccountTable/RegisterAssist | 主线有基础，本地有扩展 |
| 被动模型观测与证据解析 | C# ProbeReader/ProbePanel | arena_observation.py、model_probe_py、run_trace_resolver | 可复用，需运行回归 |
| 批量任务、模型筛选任务与状态页 | ArenCard | arena_protocol.py、arena_draw_engine.py、Arena.tsx 三页签 | 大量本地实现，不再重复开发；外部服务自动化须单独评估授权边界 |
| 任务事件与停止 | ArenCard | arena_jobs.py、JobConsole、NDJSON after_seq | 已见；内存存储，不是持久恢复 |
| 暂停/继续、运行中操作互锁 | C# RetryController 与使用说明 | Job 状态仅 running/stopping/done/failed/stopped | 暂停恢复语义待补齐 |
| 本地模型归档、筛选、多选删除 | ArchiveStore/GalleryWindow/使用说明 | 当前 Arena 页仅 accounts/register/draw | 专用归档体验待补齐；本地删除与网站删除必须分开 |
| 手动收集当前会话、稳定性检查 | ManualCollection.cs | 未见对应 Arena 页入口 | 需会话 ID、回答签名、生成状态、模型证据的一致性校验及幂等保存 |
| 未知模型保留、运行策略快照 | ModelRetention.cs | 当前任务采用 keep_pattern 等参数 | 不等同于 C# 精确目录/排除策略，需独立产品语义 |
| 会话导出、附件副本、导出标记 | SavedConversationStore/AttachmentUpload/使用说明 | 既有注册结果导出不能替代会话导出 | 需独立归档与导出模型，复用 Sage 文件能力 |
| 多实例数据和浏览器环境隔离 | InstanceManager/InstanceEnvironment | 账号池不等于完整实例工作区 | 需评估与现有 browser/session 基础的整合 |
| 代理设置与生命周期 | ProxySettings/ClashNodeRuntime | 本地代理解析/测试/fetch 接口已见 | 正常网络配置可复用；进程所有权、失败不直连需要验收 |
| 配置 UI、国际化、打包 | 参考使用说明、P5 文档 | P5 记录仍依赖 YAML，中文硬编码 | 待产品化，不以 mock 组件测试替代安装包验证 |

参考中的验证码绕过、批量滥用账号、通过更换 IP 或指纹规避平台限制，不纳入后续实现计划；遇到挑战或限流应停止/退避并交由用户通过官方流程处理。真实外部服务验证必须有明确授权、最小范围与费用确认。

## 4. 已确认的优先风险

### R1：账号库路径与密钥来源分叉（高）

- backend/main.py:495-505 使用 arena_accounts.get_or_create_master_key()，数据库为用户数据根目录下 arena_accounts.sqlite。
- backend/services/arena_keystore.py:50-69 定义 arena/arena.sqlite 和 arena/master.key。
- backend/services/arena_accounts.py:50-76 使用 SettingsRepository + SecretBox；解包失败会重新生成密钥并覆盖 preference。

源码层面可确认存在两套约定。旧数据实际是否损坏、哪个库属于当前用户，本轮未读取真实凭据/数据库确认。docs/mcp-arena-p4-draw-engine.md 的历史损坏报告只能作为线索，不作为本轮复现。

应先确定唯一数据源与迁移策略：存在旧库时不能静默创建空库；旧密钥不可读时保持原材料并报可恢复错误；禁止自动覆盖旧密钥。使用临时目录和合成数据测试迁移、坏密钥、重启、打包环境。

### R2：任务恢复与历史上限（中高）

backend/services/arena_jobs.py:25-30,62-119,146-152 的 JobStore 为内存字典；事件 deque 上限 5000。没有 paused 状态。进程重启恢复及游标过旧后的 gap/resync 语义不可由现有 after_seq 接口推断为已实现。

应明确停止与暂停区别、状态持久化、事件淘汰通知、运行策略快照以及崩溃恢复时禁止自动重放有副作用操作。

### R3：历史验收不足以证明真实应用可用（高）

P5 文档记录组件/typecheck 通过，但也承认真实链路待验收、配置未写入 UI、国际化未完成。P4 标题的 CLOSED 与正文部分链路受阻/仍待验证必须分开解释。本轮未重跑这些测试，不复用其通过数字作为当前验收。

### R4：授权与许可证（实施前确认）

docs/technical/50-arena-source-license-audit.md 针对历史 ArenaHelper/arena-model-probe，不是当前两套 reference 的完整授权证明。依赖 node_modules 的许可证也不代表参考产品本身的许可证。旧审计中的行数阈值或“修改后即可安全”等说法不能作为法律规则。直接复用前确认权利/许可；不能确认时只提取行为需求、独立设计实现并保留来源记录。

## 5. 建议实施阶段与验收门槛

### A. 保全与集成基线（建议首先批准）
1. 核对暂存测试、stash、未提交模块归属与差异，不自动合并。
2. 统一数据库/密钥装配，设计备份和显式迁移，密钥失败不覆盖。
3. 校验主进程/后端关闭生命周期、feature flag、禁用状态错误契约。
4. 用临时库及 fake provider 跑相关 pytest、Vitest、两套 typecheck 和触点 lint。
验收：无真实账号写入；跨重启合成账号可读取；旧库/坏密钥不会被覆盖；既有未提交工作不丢失。

### B. 本地归档与会话管理
建立独立 archive service/repository、API、模型归档页面；先做查看/筛选/手动收集/导出，再做确认式本地多选删除。复用现有模型观测证据与 Sage 文件导出基础。
验收：生成中/读取期间变化不写；同会话幂等；未知模型不误归类；本地删除不触发网站删除；附件去重与引用计数安全。

### C. 任务控制与保留策略
为用户授权的任务实现暂停/继续、状态持久化、运行策略快照、可取消等待、事件 gap 恢复。精确保留目录与未知模型策略独立于现有正则参数设计。
验收：暂停不丢进度；恢复不重复执行副作用；切换筛选清空隐藏选择；崩溃后状态明确且不自动重发外部请求。

### D. 实例与设置产品化
基于 Sage 既有浏览器服务实现正常账号环境隔离、实例目录管理、网络配置、资源清理；补配置 UI、凭据脱敏、国际化和无障碍。
验收：会话互不串号；只清理自己创建的进程；网络失败不静默直连；导出包不包含凭据、浏览器状态或用户数据。

### E. 发布与兼容验收
先 main 集成测试、构建与安装包 smoke，再评估 Win7 通道适配。真实第三方服务只做用户批准的最小人工流程，不以规避风控作为验收条件。
验收：记录精确版本、命令和失败基线；持久化/恢复/本地归档/设置/旧路由回归覆盖；明确未测试的 OS 和外部服务条件。

## 6. 本轮验证与限制

已完成：MCP 读取、参考目录和源码抽样、主线装配源码核对、所有列出 worktree 的相关路径状态检查、全 refs 的 Arena 提交信息检索、历史计划对照。
未完成且不声称完成：全分支内容审计、远端 fetch、全量源码逐行比较、测试重跑、GUI/安装包 smoke、真实账号数据验证、外部注册或模型请求。
本轮交付仅新增本文档；未修改业务代码、配置、账号库、密钥、分支、stash 或暂存区。实施建议从阶段 A 开始，由用户确认后推进。
