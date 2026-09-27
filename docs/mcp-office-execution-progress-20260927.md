# Office 执行边界双分支实施进度（2026-09-27）

## 阶段 1：基线与工作隔离 — 完成

已建立 main / release/win7 两个独立 worktree，未改共享 checkout 和其他会话 worktree。详细基线、方案与验收边界见 [实施计划](plans/2026-09-27-office-execution-boundary.md)。

远端 Git HTTPS fetch 曾失败；通过公共仓库检出核对两线最新提交，并以已校验的增量 bundle 导入 Win7 基线，不覆写共享 remote-tracking ref。与 OPEN PR #1626 重叠的 F1/F2 留待后续整合，本批仅推进 F4/F5 的限定范围。

## 阶段 2：实现 — 完成

方案分别先行提交：main 0755e288、Win7 31995abd。两线已实现同一公式 worker/监督器/Job 协议和按格式发现契约，未修改依赖清单。

公式从线程改为单并发子进程；解析、导入、计算、序列化在 worker 内，超时/取消终止并回收。Windows 使用挂起创建和 Job，总内存 512 MiB、最多两个 OS 进程（含 venv 启动器）。真实 venv 测试先复现单进程限额退出 101，随后补正方案并修复启动竞态。

能力发现返回 DOCX/XLSX/PPTX 支持范围；Word 注册/文件与 pywin32 同时存在才报告 DOCX。UI 按格式控制 PDF 入口，保留 Word 原生预览；显示“已发现、未验证运行”。取消尚未接 UI，转换健康/COM 超时仍在后续批次。

## 阶段 3：验证 — 进行中

- 现代 Windows / Python 3.11（本任务独立 venv，含 formulas）：重点测试 51 passed。
- 同一 Windows 主机 / Python 3.8：重点测试 48 passed、3 skipped（未安装 formulas，符合 Win7 依赖策略）。
- 两线相关前端：各 128 passed / 13 files；前端与 Electron 类型检查已通过。
- Linux main Office 单测上一轮 865 passed、3 skipped；新增生命周期用例及集成回归将再完整运行。
- Windows 广域 Win7 单测遇到既有 symlink 权限限制（WinError 1314），且运行收到 KeyboardInterrupt；不作为全量通过证据。改用 Linux Python 3.8 做完整回归，同时保留 Windows 重点生命周期实测。
- 架构棘轮仅登记本批真实增量：main 四项合计 +7 行；Win7 三项合计 +4 行（types 仍低于既有基线，不降低）。
- 尚无本批 CI 或原生 Win7 SP1/Office 人工验收结论。

## 阶段 4：交付 — 待开始

尚未发布本批 PR，尚未合并。完整 P0-B 的 COM 监督/健康检查、F6 出口策略与全部 P1/P2 未在本批完成。
