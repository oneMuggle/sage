# Win7 内网离线可靠性实施方案

## 基线与流程

- 目标：`release/win7`，基线 `783f4a66706ac6b8277ee4c5640d5b3e4615f9f3`。
- 工作区：`.worktrees/arena-win7-offline-20260926`。
- 分支：`fix/win7-offline-hardening-20260926`。
- Windows 工作机直连 Git fetch 两次重置，已通过公开仓库生成增量 Git bundle，核验 SHA-256 与 GitHub API 的 HEAD 一致后导入；未改全局 Git/代理配置。
- 顺序：新 worktree → 本方案提交 → 实施/回归 → PR 到 Win7 → CI 全绿 → merge → 清理本次分支/worktree。
- 持续进度：仓库主目录 `docs/mcp-win7-offline-implementation-progress-20260926.md`（本任务独立交付记录，不参与代码暂存；合并/清理后继续记录实际结果），另保留 Arena 工作区副本。不要为了写“CI 已通过”改变已通过 CI 的提交 SHA。

## 目标与边界

把上轮审计中可以通过源码和自动化测试确认的缺陷落地，保持 Win7/Python 3.8/Electron 21 运行时；不通过升级 Electron、关闭 TLS、放宽签名验证或改企业组策略换取兼容。

此次覆盖：网络策略失效保护、更新超时/离线出口限制/遥测、迁移前固定备份、服务诊断与修复脚本安全、离线修复指引、自带 Bash 定位、附件 multipart 回归。提供离线交付和维护手册，明确未具备的验收条件。

不声称此次自动完成：真正 Win7 VM 的 DLL/CPU/驱动验收、企业补丁合法来源/分发授权、实际离线 CA/模型服务搭建、完整签名制品平台和全进程防火墙。这些是生产发布前外部验收项，不以现代主机 CI 替代。浮动 VC++ 下载、完整原生依赖锁、更新协议签名字段升级等需要单独完成制品基线验证，不能在没有 Win7 验证的情况下随意指定“兼容版本”。本 PR 不发布安装包。

## 实施设计

### A. 网络策略失效保护

- 缺失、损坏或无法读取的 network_policy 回退 OFFLINE，而不是 ONLINE；合法显式 ONLINE 配置仍保留。
- 支持管理员部署环境 `SAGE_DEPLOYMENT_MODE=offline|intranet|online`；非法值按 offline；offline 不可被用户设置放宽，intranet 不可变为 online。
- 企业 intranet 的允许主机由管理员环境提供，与偏好配置的职责分离；无有效主机即不放行。
- doctor 与真实策略结果一致，错误消息不再建议在线 pip/conda 或主线 requirements。
- 此开关不是 OS 防火墙；运维手册要求进程树出口控制及内网白名单。

### B. 更新可靠性与隐私

- 为更新 provider 的请求增加统一的应用级截止时间、取消信号传递及 body 消费期限，避免 DNS/TCP 黑洞长期占住检查状态。
- 企业 offline 禁止更新网络请求；intranet 限制到管理员批准的 HTTPS update origins，禁止重定向绕过；部署配置不合法则拒绝外联。
- 禁止离线/内网部署触发公网回滚遥测；任何上报必须尊重 enableTelemetry。
- 不把所有普通 fetch 都绑到更新策略，避免误伤本机后端与配置过的 LLM。

### C. 数据迁移之前保留不可轮转的恢复点

- 在数据库 init_db/schema 迁移前为已有数据库创建固定升级快照，使用 SQLite backup API，并做完整性检查及原子发布。
- 快照按应用版本身份区分；位于独立 upgrade-backups 目录，不受日常七份轮转影响；已有有效快照不覆盖。
- 首次创建空库不需备份；源损坏、备份失败或已有快照损坏必须阻止迁移，不吞错继续。
- 该机制保护 SQLite；附件/密钥/配置的整机维护快照仍由管理员执行。程序回滚不自动当成数据 schema 回滚。

### D. 服务诊断和离线修复

- STOPPED/START_PENDING/STOP_PENDING 只记录维护警告，不仅凭服务状态判应用无法运行。
- 将 fix.bat 改成只读诊断和管理员说明入口，不再改注册表/服务启动类型、注册 DLL 或执行重启。
- 提供本地维护手册、明确离线组件获取方式，禁止诱导终端自行升级 Python 依赖。

### E. 兼容性功能修复

- 后端从嵌入式 Python 的实际位置推导受约束的 Sage 安装根目录；保留可信路径/文件身份检查，覆盖每用户/中文/空格安装目录。
- 附件使用 Node 16 支持的 Buffer 构造 multipart 数据，不把 WHATWG FormData 直接传给 node-fetch 2；文件名头字段必须防 CRLF 注入，类型与大小保持现有边界。
- 测试验证 boundary、文件字节与文件名，不仅断言“调用了 fetch”。

## 验收

1. Python 3.8：已有兼容扫描、network config/doctor、备份、shell resolver 的定向测试；正常 ONLINE/intranet/offline 和五类异常输入。
2. Electron：provider 请求超时/取消/重定向、离线零请求、遥测开关；服务状态；multipart 二进制内容和头注入负例。
3. 真实 SQLite：升级快照在 schema 修改前生成；多次启动不覆盖；日常轮转不删；损坏/写失败阻止迁移。
4. TypeScript 检查、Ruff/ESLint、架构门禁；不降低现有覆盖率/基线。
5. GitHub PR 的适用 CI 全绿且对应最终代码 SHA 后才 merge；若 CI 丢事件使用仓库规定的重跑流程，不管理员绕过。
6. CI 只证明受测代码行为，不声称 Win7 实机/离线安装包验收完成。发布安装包仍需 Win7 基线和两轮审计中的外部门禁。

## 风险与回退

- 缺省网络策略变为 offline 是有意收紧；升级前给管理员说明，用户合法显式 online 设置不受影响。
- 更新源白名单只接受精确 HTTPS origin，不做隐式通配/降级 HTTP；企业 CA 仍须正确部署。
- 升级快照增加磁盘需求；失败提示必须给出本地备份路径和管理员处理方式，禁止删除唯一恢复点。
- 本 PR 可代码回退，但数据恢复仍应验证 schema；保留人工恢复说明。

## 方案阶段记录

- 已完成新 worktree 和最新基线验证。
- 本文件先于实现代码提交；之后每阶段实际证据写入独立进度记录。
