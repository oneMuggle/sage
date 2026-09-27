# Office 执行边界双分支实施进度（2026-09-27）

## 阶段 1：基线与工作隔离 — 完成

已建立 main / release/win7 两个独立 worktree，未改共享 checkout 和其他会话 worktree。详细基线、方案与验收边界见 [实施计划](plans/2026-09-27-office-execution-boundary.md)。

远端 Git HTTPS fetch 曾失败；通过公共仓库检出核对两线最新提交，并以已校验的增量 bundle 导入 Win7 基线，不覆写共享 remote-tracking ref。与 OPEN PR #1626 重叠的 F1/F2 留待后续整合，本批仅推进 F4/F5 的限定范围。

## 阶段 2：实现 — 完成

方案分别先行提交：main 0755e288、Win7 31995abd。两线已实现同一公式 worker/监督器/Job 协议和按格式发现契约，未修改依赖清单。

公式从线程改为单并发子进程；解析、导入、计算、序列化在 worker 内，超时/取消终止并回收。Windows 使用挂起创建和 Job，总内存 512 MiB、最多两个 OS 进程（含 venv 启动器）。真实 venv 测试先复现单进程限额退出 101，随后补正方案并修复启动竞态。

能力发现返回 DOCX/XLSX/PPTX 支持范围；Word 注册/文件与 pywin32 同时存在才报告 DOCX。UI 按格式控制 PDF 入口，保留 Word 原生预览；显示“已发现、未验证运行”。取消尚未接 UI，转换健康/COM 超时仍在后续批次。

## 阶段 3：相关验证 — 完成

- 现代 Windows / Python 3.11（本任务独立 venv，含 formulas）：重点测试 51 passed。
- 同一 Windows 主机 / Python 3.8：重点测试 48 passed、3 skipped（未安装 formulas，符合 Win7 依赖策略）。
- 两线相关前端：各 128 passed / 13 files；前端与 Electron 类型检查已通过。
- Linux main Office 单测与集成共 1184 passed、3 skipped；Python 3.8 / Win7 共 1065 passed、13 skipped；另两线各 3 项公式闭环通过。
- Windows 广域 Win7 单测遇到既有 symlink 权限限制（WinError 1314），且运行收到 KeyboardInterrupt；不作为全量通过证据。改用 Linux Python 3.8 做完整回归，同时保留 Windows 重点生命周期实测。
- 架构棘轮仅登记本批真实增量：main 四项合计 +7 行；Win7 三项合计 +4 行（types 仍低于既有基线，不降低）。
- 两线完整 Ruff、相关 ESLint、架构/diff 检查通过。细节、失败修正和环境限制见 [验证记录](verification/2026-09-27-office-execution-boundary.md)。
- 尚无本批 CI 或原生 Win7 SP1/Office 人工验收结论。

## 阶段 4：PR 已发布，未合并

- main：[PR #1714](https://github.com/oneMuggle/sage/pull/1714)，目标 main，基线 1b8aced5。
- Win7：[PR #1715](https://github.com/oneMuggle/sage/pull/1715)，目标 release/win7，基线 6359bdae。
- 代码/验证发布版本：main d80494e0；Win7 dc561531。16 个共用源文件/测试逐字节相同，OfficeCapabilities 接口一致；本页随后仅补记发布信息。
- 基线移动后的棘轮冲突保留全部上游条目，只增加本批实际行数；最新基线上再次通过两线 TypeScript、相关前端 128 项、Ruff、架构/diff 检查。
- Git HTTPS fetch/push 持续被连接重置。经公共克隆和已验证 bundle 同步基线，再用主机已有 gh 认证调用 Git Data API 发布。三阶段提交的 **commit SHA 与 tree SHA 均与 Windows 工作树完全相同**；没有导出凭据，没有改写共享/目标分支。
- PR 刚创建时尚无 checks；CI 的动态状态以两条 PR 为准，未通过前不合并。工作树保留用于 CI 修复，未提前清理。

完整 P0-B 的 COM 监督/健康检查、F6 出口策略与全部 P1/P2 未在本批完成。
