# Office P0-B1：公式执行边界与按格式转换能力（2026-09-27）

## 工作隔离与现有成果

- main 基线：4aeddfc81812e3ab08a17c4de4ac2ffbe66e3606。
- Win7 基线：90041bc530397824e545a9c96ead3dc8571b6ec5。
- 工作分支：fix/office-execution-main-20260927、fix/office-execution-win7-20260927。
- Windows 独立 worktree：.worktrees/arena-office-execution-main-20260927、.worktrees/arena-office-execution-win7-20260927。
- 已有另一会话的 PR #1626 / feat/office-doc-revision（ff179b549）处理 F1/F2。不得改写该 worktree、强推其分支，或直接叠加上一轮重叠实现。上一轮 P0-A1 两个本地提交 e9b0659 / 444b140 保留，后续单独整合。
- 本批先推进 2026-09-26 Office 评估中不重叠的 F4/F5，避免并行会话重复开发。不是宣布全部 P0/P1/P2 完成。

## 1. 公式执行（F4）

将公式读取、数量检查、引擎导入/计算、结果标准化移至独立 Python worker；父进程只监督。

- 单实例最多一个求值 worker，超额调用明确降级，不无限排队。
- 保留 500 个公式上限；增加 50 MiB 输入、2 MiB JSON 输出、15 秒总等待预算。
- 使用 JSON 标量通信，不使用 pickle，不把子进程输出无限读入内存。
- worker 启动握手后才加载文档，Windows 以挂起状态创建进程，先附加私有 Job Object，再恢复主线程并发送握手：512 MiB Job 总内存、最多两个 OS 进程（兼容 venv 启动器 + 一个计算 worker）、关闭 job 杀掉所属进程。无法配置 job 时安全降级，不绕过宿主限制。
- POSIX worker 设置资源限制；超时、取消和异常时只终止本次 worker 的进程组并回收。
- 取消事件作为内部接口提供；没有接入现有 UI 取消按钮前，不宣称 UI 端已完整支持取消。
- 读取成功但公式未能计算时沿用现有“需在 Excel 中打开”的提示，不伪造 0 或空的正常数值。
- 这不是任意代码安全沙箱，也不保证文档不出域。文档级出口策略另批实现。

## 2. 按格式能力（F5 的发现层）

- 仅发现 pywin32 不再代表安装了 Word：Windows 同时核对 Word COM 注册和本机可执行文件。
- 返回支持的 PDF 源格式；Word COM 只标记 DOCX，LibreOffice 标记 DOCX/XLSX/PPTX。
- 明确状态为“已发现、未验证运行”，不在轻量探测时启动 Word，也不声称许可证/转换健康已通过。
- UI 按当前文档类型控制转换预览与导出；Word 无转换器仍可使用原生 DOCX 预览。
- 旧响应采用保守兼容逻辑，不再用合并布尔值推导 Excel/PPT 能由 Word COM 转换。
- COM 超时监督与实际转换健康检查、OCR 健康及文档出口验证仍在后续 P0-B 批次，不伪装完成。

## 3. 对齐、验证与交付

- 新增 Python 代码兼容 3.8；共用 worker/监督逻辑、协议和回归用例，不升级 Win7 依赖。
- 测试真实子进程的完成、失败、超时、取消、输出上限、并发占用和回收；测试 Windows Job 分支的配置与失败关闭。主渠道追加真实公式数值验证。
- 检查当前目标分支环境的 Python 3.11 / 3.8；前端类型、相关 Vitest、Ruff、架构门禁。
- 真实 Win7/原生 Office 另做验收，现代 Windows 的 Python 3.8 测试不能替代。
- main 和 Win7 分别 PR，记录交叉链接、功能差异与 CI 的准确状态。不改覆盖率阈值，不覆盖共享 checkout。
- 只维护本任务 worktree/分支/临时文件；已有 PR #1626 保持不变。

## 验证驱动的方案修订

Windows venv 的 python.exe 含重定向启动器，实际需要“启动器 + 解释器”两个 OS 进程。真实测试复现单进程 Job 限额导致退出 101。将 Job 改为两个进程、512 MiB **总**内存，并使用 CREATE_SUSPENDED → 绑定 Job → 通过文档化 Toolhelp/OpenThread/ResumeThread 恢复主线程，消除启动器抢先生成未受 Job 管理子进程的竞态。仍只允许一个求值任务，不放宽到任意子进程树。
