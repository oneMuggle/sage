# Win7 离线可靠性：实施与验证记录

目标：`release/win7`，基线 `783f4a66706ac6b8277ee4c5640d5b3e4615f9f3`。
先行方案：[`2026-09-26-win7-offline-hardening`](../plans/2026-09-26-win7-offline-hardening.md)，提交 `d4662b1`。
部署及维护契约：[`101-win7-offline-maintenance`](../technical/101-win7-offline-maintenance.md)。

## 已实施

- 配置缺失、损坏、读取失败及非法模式 fail closed；管理员部署模式覆盖用户可写设置，保留本地能力。
- updater 的 provider、manifest、遥测请求统一经过部署边界；内网 HTTPS 精确 origin 白名单、拒绝重定向；请求头与响应体均有 30 秒期限，支持取消。
- 已缓存 manifest 不能绕过离线下载限制；内网拒绝不能统一控制重定向的旧 electron-updater 下载链路，改走受控 provider 或管理员核验的离线维护包。
- 遥测必须同时满足显式启用与 online 模式；遥测关闭不影响本地回滚。
- `init_db()` 前生成独立 SQLite 快照，使用 SQLite backup API 包括 WAL；按版本、commit、buildId 固定身份，启动重试不覆盖；并发/残留锁及备份失败阻止迁移；显式关闭验证连接，避免 Windows 句柄阻止 rename。
- 停止/启动中的系统服务不再直接判为关键运行时缺失；修复脚本改为只读诊断，不更改服务、注册表、DLL 注册或系统重启状态。
- Bash 支持从嵌入解释器发现自定义/中文安装路径；multipart 使用 Buffer，保留 UTF-8 文件名、二进制数据与 MediaRecorder MIME 参数，拒绝头注入；移除要求 Node 18 的直接依赖 formdata-node。
- 架构基线仅增加四个本来已在基线中的文件行数：启动钩子、下载边界与对应回归；没有关闭检查或新增超限文件豁免。

## 验证证据（不是 Win7 实机验收）

| 检查 | 结果 | 环境/边界 |
| --- | --- | --- |
| Python 3.8 关键回归（策略、doctor、快照、日常备份/恢复、Bash、agent、lifespan） | 122 passed | Linux CPython 3.8.20，完整 requirements-py38.txt，Pydantic 1.10.13 |
| Python 3.8 语法兼容扫描 | 1427 文件、0 违规 | 包含新模块与测试 |
| Python 3.8 运行时 hazard AST 扫描 | 0 | 不代替本机执行 |
| 全 backend Ruff | 通过 | 锁定 ruff 0.4.4；存量 UP045 注释警告未扩大 |
| Electron 定向回归 | 20 文件、170 passed | 更新器及四类 provider、离线请求、服务诊断、multipart，以及补装 Electron 后复测的三个文件 |
| 前端全套一次运行 | 394 文件通过、3 文件环境失败、2 文件跳过；2927 passed / 13 failed / 3 skipped | 13 项均因最初 ignore-scripts 安装缺少 Electron；补跑 install.js 后，这三个文件全部通过，包含于上述 170 项。不得把该次完整运行写成全绿 |
| Renderer / Electron TypeScript | 均通过 | 独立 Linux 依赖环境；远端共享 node_modules 缺 node-pty，未修改共享依赖来掩盖环境问题 |
| 全量 ESLint | 0 errors、12 存量 warnings | 未放宽 lint 配置 |
| architecture-check | 通过 | 不将本地 venv 纳入源码基线 |
| knip | 原始报告仍非零 | 存量 unused files/types 等未在本轮清扫；已移除本轮不再使用的 formdata-node |
| 现代 Windows Python 3.8 补充回归 | 99 passed、18 skipped | 该现有 conda 环境实际为 Pydantic 2，不能替代上面的锁定依赖结果或 Win7 验收 |

快照测试还覆盖：损坏来源/既有快照拒绝、写入失败释放锁且不改源库、残留锁阻止备份、BOM manifest、同版本重新构建身份变化、每日轮转不删固定快照。每日轮转测试使用不同 mtime 模拟真实的不同日期，避免把同一时钟刻度的连续手动备份当作多日轮转。

## PR、CI 与发布约束

此记录提交时尚未合并。PR 必须指向 `release/win7`；最终提交 CI 绿后才能合并。
本地未引导的 worktree 按 AGENTS.md 允许跳过 hooks，已实际运行上述检查；CI 门禁不跳过。
PR/最终 SHA/合并/清理终态由主 checkout 的 `docs/mcp-win7-offline-implementation-progress-20260926.md` 持续记录，避免事后改动已测试 SHA。

没有 Win7 SP1 x64 实机、企业补丁/CA/签名基础设施、真实隔离网维护镜像；本轮不宣称已通过实际 Win7 安装、CPU/VC/native DLL、全离线升级恢复矩阵，也没有发布安装包。
代码边界不是 OS 防火墙；未声称阻止所有第三方库出网。SQLite 恢复点不包括附件、模型、凭据和系统密钥；程序回滚不等于数据模式回滚。可信制品导入及精确产品线资产资格验证仍属发布前条件。

## 首轮 CI 反馈与修正

PR #1615 的首轮 CI `36205960831`：前端 397 文件、2940 passed / 3 skipped，Linux/Windows 构建、Electron smoke、架构检查均成功。后端覆盖率 **82.23%** 达到原有 80% 门槛，但 52 failed / 9807 passed / 126 skipped，因此没有合并。

52 项失败来自存量网络传输测试隐含的“缺配置仍在线”假设及旧 doctor pip 建议断言：新增**非自动启用**的 `_online_network_settings` fixture，仅由相应 mock 网络传输测试显式选择；内存 SettingsRepository 测试替身同样显式配置 online。没有在全测试会话或生产代码中恢复 fail-open。默认工具注册测试改为同时验证本地工具可用、网络工具缺席，并新增显式 online 注册网络工具的对照用例。重依赖测试要求离线维护包指导且不得建议 `pip install`。

修正后相关 10 个文件在锁定 Python 3.8 环境中 **375 passed / 1 skipped**（本地没有浏览器，真实浏览器 smoke 跳过）；其中包含原有 offline/intranet/SSRF/凭据剥离负向断言。未删除或跳过失败测试，未降低覆盖率或安全检查。最终提交仍须完整 CI 重新通过。
