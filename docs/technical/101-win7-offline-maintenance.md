# Win7 内网离线维护合同

本轮代码加固不等于最终安装包已通过 Win7 验收。生产基线为管理员批准的 Windows 7 SP1 x64、组件版本和补丁集合；绝不以关闭签名/TLS校验、解除组策略或未知 DLL 替代前置条件。

## 部署策略

| 变量 | 含义 |
| --- | --- |
| `SAGE_DEPLOYMENT_MODE=offline` | Python Web 工具策略锁定 offline；Electron 更新请求及回滚遥测禁止联网 |
| `SAGE_DEPLOYMENT_MODE=intranet` | Web 工具使用管理员主机白名单；更新使用独立精确 HTTPS origin 白名单；回滚遥测关闭 |
| `SAGE_NETWORK_ALLOWED_HOSTS` | 逗号分隔的 Web 工具主机/合法域名通配，例 `wiki.corp.example,llm.corp.example`；不是 URL |
| `SAGE_UPDATE_ALLOWED_ORIGINS` | 逗号分隔的精确 HTTPS origin，例 `https://updates.corp.example:8443`；不允许路径、认证信息、通配或 HTTP |
| `SAGE_DEPLOYMENT_MODE=online` / 未设置 | 不施加管理员模式上限；Python 偏好配置仍须显式合法 mode，缺失/损坏时 offline；更新沿用用户 provider 配置 |

非法部署 mode 按 offline；非法/空白名单不得放行。企业环境应在首次启动前由管理员部署变量、内网 provider 与 CA；不要只在设置页改为 manual 就认定没有外联。

**边界**：这不是全进程防火墙。LLM、embedding、浏览器、MCP/技能及子进程须由企业网段 ACL/终端防火墙治理；维护前观察整个进程树的网络行为。本机后端保留 loopback 和鉴权。部署模式不自动安装 CA，也不启用 insecure_tls_hosts。

## 更新与诊断

- 更新网络调用默认总期限 30 秒，覆盖响应头和数据体；取消应向底层传递。内网更新不跟随重定向，仓库应直接提供批准 origin 下的制品。
- `enableTelemetry=false` 不上报回滚事件；offline/intranet 即使启用遥测也不上报。
- `resources/win7-fix/fix.bat` 仅输出诊断，不修改服务/注册表、不提权、不重启。STOPPED 或转换中仅是维护告警，不是应用运行库缺失的证明。
- 缺依赖应找管理员导入匹配版本的离线维护包，不在生产终端运行 pip/npm/conda，不安装 main 的 requirements。

## 升级前恢复点

已有 SQLite 数据库在 `init_db()` 之前按构建身份创建 `upgrade-backups/pre-upgrade-<identity>.db`。使用 SQLite backup API，覆盖 WAL 内容，检查完整性后原子发布。已有有效恢复点不覆盖，且不参与日常 backups 七份轮转；损坏、写入失败或超时阻止此次初始化/迁移。

`.pre-upgrade-*.lock` 表示备份正在进行，或进程被异常终止。先关闭所有 Sage 后端，确认没有活动备份、保存现有数据及 `.tmp`，再由管理员检查后移除过期锁并重试；不要在备份仍运行时删锁。备份默认 30 秒时间预算，超大数据库需在维护窗口准备受控离线恢复点，而非跳过保护。

应用版本身份来自安装资源中的 build-manifest.json（版本+commit/buildId）；源码开发使用 package.json。禁止在未变更构建身份的情况下悄悄覆盖发布产物。

这只保护 SQLite，不自动备份附件、配置或解密密钥。维护方还需进行完整业务数据备份、保存旧安装包及凭据恢复/重新配置方案。快照保留至现场验收和批准的维护周期结束后才可归档，切勿为了磁盘不足删除唯一恢复点。

程序目录回滚不等于数据库回滚。现有手工回滚窗口仍由 update config 控制（默认 7 天）；管理员应按现场周期设置并保留人工恢复流程。恢复时停止所有进程，选用受测的程序+schema配对，先保存当前数据库/WAL/SHM，再通过批准的 SQLite 恢复流程操作；不可逆 schema 不允许旧程序直接打开。

## 离线维护包与签名

组织维护包至少包括：批准安装器、独立预检工具、合法可分发的先决组件或内网索引、可选能力包、CA/密钥轮换材料、恢复包和本地手册。管理员在受控联网准备机取得制品并核验来源、签名/hash和授权，隔离扫描后导入内网。

清单需由预先可信密钥签名，绑定 Win7 产品线、架构、源码/Cython模式、全部制品hash、升级起点/桥接版和恢复说明。单独 SHA 文本不是来源认证。此 PR **没有实现新的签名维护包导入 UI/平台**，不要把手册示例当成已有功能。

## 发布前外部门禁（仍待完成）

1. 固定经 Win7 实机验证的 VC++/UCRT 与 native 依赖工具链，禁止未经验证地宣称某个浮动下载兼容。
2. 更新产品线/架构/模式与签名 manifest 协议专项；现有 provider 选择首个资产的风险未由本轮网络边界替代。
3. 全进程断网验收、企业 CA/时间服务、最低补丁基线、旧 CPU/GPU、普通用户/中文路径验收。
4. 最老受支持版本直升/桥接升级、磁盘满/断电/迁移失败及超维护周期恢复演练。
5. ONNX/OCR/模型/native 组件逐项验收。缺模型的 HashEmbedder 降级不等于语义检索完整；Win7不必安装现代推理运行时，优先使用内网受支持服务器。
6. 完全离线无本地/内网模型时，只承诺本地数据读取/导出等受测能力，不承诺离线聊天推理。

内网模式下，旧 electron-updater 下载链路无法统一约束重定向，因此直接拒绝该链路（包括先前在线检查留下的缓存元数据）。必须使用受控 provider；不具备对应签名/资产校验能力时，走管理员核验后的离线维护包。离线模式同样拒绝所有下载入口，但不阻止本地恢复。
