# Sage Arena 使用与设计落地核查

日期：2026-09-19
基线：远端工作区 main / 673548b9，含未提交修改。静态源码与文档核查，不是运行验收。

## 结论

当前源码已有 Arena 控制台，但不能直接在 UI 打开总开关。磁盘配置 backend/config/arena_automation.yaml:16 为 enabled: false；registration、draw、proxy、token_window 子开关默认也为 false。当前运行进程是否加载同一配置、本机安装包是否包含这些修改，本轮未验证。

确有参考 reference 完整移植的设计，不过目前是基础服务、部分任务 UI 已实现，产品化和端到端验收尚未收口，不能视为两套参考产品的完整替代。

## 入口与现有用法

- 使用 Sage Electron 桌面端。src/shared/api/backendRequest.ts:19-24 要求 Electron bridge，普通浏览器打开页面不提供后端回退。
- 侧边栏更多区域的 Arena：src/widgets/layout/Sidebar.tsx:61-67。
- 命令面板搜索 Arena 控制台：src/widgets/command/commandItems.ts:43。
- 路由 /arena；页签 /arena?tab=accounts、/arena?tab=register、/arena?tab=draw。旧 /arena-accounts 重定向到 /arena。
- 账号池：查看状态、隔离、重新启用、软删除；右侧单账号注册辅助与被动模型观测。账号行“重新启用”不是功能总开关。
- 单账号辅助：开始注册、在 Sage 打开的浏览器中由用户完成人机验证、打开邮件验证链接、设置密码、入池。依赖可用邮箱 provider 和 Sage 自管浏览器。
- 被动观测：先启动 Sage 自管浏览器会话，再点“启动观测”；在该页面正常使用 Arena 后查看模型、来源、置信度。这不是强制选择上游模型，也不保证所有响应都可识别。
- 批量注册页：有数量、并发、代理 off/pool、启动、日志、停止、注册结果导出。描述的是现有界面，不代表已获第三方平台授权或本轮已测试。
- 抽卡页：账号选择、轮数、保留 pattern、未命中策略、命中改名、偏好推理、启动、停止、最近记录和 token 状态卡。会产生真实网站操作，未做实际调用。

## 如何启用与为何不能 UI 直开

对于源码开发运行，基础账号管理/单账号辅助/观测由 backend/config/arena_automation.yaml 顶层 enabled: true 控制，保存后需重启后端。现有 max_accounts、mail_provider 等配置保留并核对。不要盲目替换整个配置。

批量注册另依赖 registration.enabled；抽卡依赖 draw.enabled，其协议路径另需 token_window.enabled 和可用 Electron token 窗口；代理能力另受 proxy.enabled 控制。打开顶层开关不等于所有子功能可用。

证据：
- src/pages/Arena.tsx:46-55：403 时提示改 YAML 后重启。
- backend/config/arena_automation.py:31-102：总开关和子开关定义；未知字段/非法值会回退禁用默认配置。
- backend/api/arena_routes.py:412-479：已有 capabilities 与脱敏 GET config，没有相应配置写入路由。
- src/widgets/arena/TokenWindowCard.tsx:18-115：轮询状态与禁用提示，无启停按钮。
- docs/mcp-arena-p5-ui.md:73-74 明确承认应用内开关未实现。

本轮未修改开关，未重启后端。若存在旧账号数据，应先处理下述数据库/密钥风险，再启用。安装包的可写配置位置及设置持久化尚需单独验证，不能直接套用源码目录操作。

## 找到的设计与实施文档

1. docs/superpowers/specs/2026-09-16-arena-automation-model-probe-design.md：原始总体设计，含账号池、浏览器辅助、模型探测、SettingsCard 设想；仍标 draft。
2. docs/superpowers/plans/2026-09-16-arena-automation-model-probe.md：早期分阶段实施计划。
3. docs/mcp-aren-card-implementation.md：ArenCard 移植初稿。
4. docs/mcp-aren-card-port-plan.md：v2 核实版，reference/ArenCard 的协议/任务/代理/token/UI 移植方案，P0–P6。其“现状缺口”是设计时快照，不代表当前仍无实现。
5. docs/mcp-arena-p0-verification.md、docs/mcp-arena-p1-protocol.md、docs/mcp-arena-p2-proxies.md、docs/mcp-arena-p3-token-window.md、docs/mcp-arena-p4-draw-engine.md、docs/mcp-arena-p5-ui.md：阶段实施与历史测试记录。
6. docs/mcp-reference-inventory-20260919.md：既有综合盘点，区分两套 reference、未提交资产、持久化与产品化缺口。

## 两套 reference 的覆盖边界

### reference/ArenCard

已有对应代码：arena_protocol/http/jobs/proxies/proxy_relay/token_cache/trace_ext/draw_engine 等后端模块，electron/arenaTokenWindow.ts，以及 src/pages/Arena.tsx 和 src/widgets/arena 的任务组件。不是只剩设计，也不应从零重复开发。

但对照 docs/mcp-aren-card-port-plan.md:501-516，当前 UI 尚未覆盖完整代理配置/解析/测试、账号代理重绑、手动添加已有账号、丰富账号历史、浏览器路径抽卡切换、部分高级筛选/节奏控制。token IPC 接口存在不等于页面已有控制按钮。P5 文档明确 i18n 未完成。

### reference/Arena模型助手-源码-fyb-0.1.0

使用说明和源码包含更广的产品能力：本地模型归档、筛选多选删除、稳定性检查后手动收集、暂停/继续、任务保留策略快照、会话导出及附件副本、多实例数据隔离。

例如 reference/Arena模型助手-源码-fyb-0.1.0/src/ManualCollection.cs:9-24 会验证生成状态，并比较两次读取的会话、回答签名和模型证据再允许保存；不是增加一个“保存”按钮即可等价。

当前 Arena 三页签中未见这些完整入口。注册结果导出不等于会话导出；网站归档不等于本地模型归档；账号池不等于完整的多实例环境管理。

## 启用前必须明确的风险

### 1. 数据库与密钥约定并存

backend/main.py:495-505 实际采用 arena_accounts.get_or_create_master_key() 与用户数据根目录下 arena_accounts.sqlite。
backend/services/arena_keystore.py:50-69 则定义 arena/arena.sqlite 与 arena/master.key。
backend/services/arena_accounts.py:65-75 在 SecretBox 解包失败时会生成并写入新主密钥。

源码证实存在两套约定及覆盖风险。本轮没有读取真实数据库或密钥，不声称旧账号已损坏；P4 的历史损坏报告只能作为排查线索。应先备份、确认唯一数据源、显式迁移，密钥失败时保留旧材料并报错。

### 2. UI 与实际匹配语义冲突

src/widgets/arena/DrawPanel.tsx:101-103 写“模型名含 pattern，空 pattern 视为未命中”。
backend/services/arena_trace_ext.py:115-128 实际为空 pattern 返回 True；非空为不区分大小写的正则，非法正则降级为字面量。
引擎还可受 require_reasoning 附加条件影响。因此应以实际代码为准，先修正文案与测试，不让用户按错误说明操作。

### 3. “归档”可能退回删除真实网站会话

backend/services/arena_draw_engine.py:759-773：未命中选择 archive 时，archive_chat 失败会调用 delete_chat。默认 UI 未命中策略就是 archive。
这不是仅修改本地记录，也不是删除账号。应去掉未明确授权的删除回退或增加独立确认；未修复前不要用重要会话试跑。

### 4. 任务续传不等于刷新/重启恢复

backend/services/arena_jobs.py:25-30,62-78 定义有界内存事件与 running/stopping/done/failed/stopped，无 paused。
批量注册与抽卡页的 jobId 是组件 useState；没有据此证明刷新后可自动找回任务。after_seq 是已有任务的增量日志游标，不是后端重启恢复协议。

### 5. 历史验收不能证明当前安装包可用

docs/mcp-arena-p4-draw-engine.md:112-148 记录真实抽卡 ok=0、failed=3，卡在服务端 reCAPTCHA 拒绝。文档对网络信誉原因的判断不构成本轮独立证实，也不能保证改网络条件即可解决。
P5 记录组件/typecheck 通过，但并未完成真实完整链路和应用内设置。
本轮 git 只读检查确认 main / 673548b9 下 Arena.tsx、draw_engine、token 窗口和多个 UI 组件仍为 untracked，另有配置修改。不能认定现有发布安装包已包含这些工作。

## 建议收口顺序

1. 保全并整合现有本地代码；统一数据库/密钥与迁移，禁止失败后静默覆盖旧密钥。
2. 实现真正的设置闭环：capabilities 展示、总开关、合法子功能开关、配置校验/持久化、生效范围及重启提示；补一致的禁用状态。
3. 修复匹配说明及归档删除回退，补账号手动添加、历史与可恢复任务 UI。
4. 按确认后的需求补 C# 模型助手的本地归档、收集、导出、暂停恢复、多实例管理，而不是把旧 ArenCard 计划当作全部范围。
5. 合成数据/假 provider 测试、组件测试、桌面构建和安装包 smoke 分层验收。真实外部请求只在用户明确授权和平台允许的最小范围内进行；遇到验证或限流应停止/退避并交由官方人工流程处理。

## 本轮范围

完成：MCP 只读源码/文档抽样、配置门控和 UI 接线核对、reference 使用说明与源码抽样、限定路径 git 状态核对。
未做：业务代码修改、配置启用、后端重启、账号数据读取、真实注册/抽卡、GUI 点击、测试重跑、安装包验证。
仅新增本核查文档。以上源码行号对应本轮读取，后续变动可能使行号漂移。
