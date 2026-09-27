# Office P0-B1 双分支验证（2026-09-27）

## 范围与契约

本批实现 F4 公式执行边界与 F5 按格式转换组件发现，见 [方案](../plans/2026-09-27-office-execution-boundary.md)。不重复另一会话 PR #1626 的 F1/F2 修订与缓存实现，不导入上一轮重叠的 P0-A1 补丁。

- 单并发、15 秒 worker 预算；输入 50 MiB、公式 500 个、JSON 输出 2 MiB。
- 解析、引擎导入、计算和序列化均位于子进程。父进程不再遗留超时计算线程。
- POSIX 进程组终止和资源限制；Windows 挂起创建、绑定 Job 后恢复主线程，Job 总内存 512 MiB、最多两个 OS 进程（venv 启动器 + 一个 worker），关闭 Job 时终止所属进程。回收失败时保留并发许可，停止继续启动计算，避免堆积。
- Job 配置/绑定失败、缺少引擎、异常、超时、取消、协议非法均降级为未求值，不伪造数值。
- Word COM 发现需要 pywin32、注册项和 Word 可执行文件；只声明 DOCX。LibreOffice 对应 DOCX/XLSX/PPTX。发现不等于许可证、健康或实际转换成功；UI 文案明确“尚未验证运行”。

## 验证记录

| 环境 | 验证范围 | 结果 |
| --- | --- | --- |
| Linux CPython 3.11.16 / main | Office 单测 + Office 集成 + agent/chat Office 集成 | **1184 passed, 3 skipped**，38.29s |
| Linux CPython 3.8.20 / Win7 分支 | 同一范围；保留 Win7 可选依赖差异 | **1065 passed, 13 skipped**，38.24s |
| 两条分支各自对应 Python | `test_excel_formula_roundtrip.py` 补充闭环 | 各 **3 passed** |
| 现代 Windows CPython 3.11.16 | 真实公式、进程监督、Windows Job、格式发现；本任务独立 venv 含 formulas 1.3.4 | **51 passed**，24.70s |
| 同一 Windows 主机 CPython 3.8.20 | 同上；不安装 formulas | **48 passed, 3 skipped**，18.15s |
| 两条分支 | 相关前端 Vitest（Office features/page/API） | 各 **128 passed / 13 files** |
| 两条分支 | 前端及 Electron TypeScript、变更文件 ESLint、完整 backend Ruff 0.4.4、架构检查、diff check | 通过；Ruff 对既有 UP045 注释有版本提示，不新增豁免或降低门槛 |

上述是本批相关回归，不是整个后端所有测试，也不是最终 GitHub CI 结论。CI 状态以 PR 为准。

### 真实进程验证

覆盖正常输出、海量 stdout 不阻塞父进程、非零退出、缺少/非法/超限 JSON、超时、运行中取消、预取消、真实并发竞争、启动失败、Job 拒绝时不发握手、进程已回收、内存分配被实际限制、Job 内存/进程参数、挂起线程恢复成功与失败。真正缺引擎的测试在子进程内安装 import 拦截，未再假设父进程 monkeypatch 能传入隔离进程。

Windows 实测暴露 venv 重定向启动器需要两个 OS 进程：原单进程配额导致退出 101，已修正为两个进程且改为 Job 总内存限制。通过 CREATE_SUSPENDED 防止启动器在附加 Job 前生成未受约束的解释器。Windows 关闭 Job 后退出码可能为 0，终止断言以真实 OS 进程句柄已结束/回收及时间预算为准，不能把非零退出码当作唯一证据。

### 已知环境限制与未完成项

- Windows 广域 Win7 Office 单测遇到既有创建 symlink 权限错误（WinError 1314），并收到 KeyboardInterrupt。该次为 **1 failed / 467 passed / 12 skipped 的中断运行**，不计作全量通过。未为此修改无关测试或扩大主机权限。
- Linux 首轮临时环境装到了非项目固定版本的 python-docx/reportlab，造成无关 PDF/批注失败；已按项目固定版本纠正环境后重跑。项目依赖清单未改。
- 部分 chat 集成测试存在事件循环清理 warning；本批没有把 warning 表述为零问题。
- Python 3.8 与现代 Windows 的 Job 实测不能替代 Win7 SP1、真实 Office/字体、安装/升级的人工验收。
- 没有完成实际转换健康 canary、COM 超时隔离、文档出口/联网控制、UI 取消闭环、原评估中 100 次超时压力验收及完整 P0/P1/P2。

## 复现命令

在各自独立 worktree、对应 Python 环境中串行运行：

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m pytest \
  backend/tests/unit/office backend/tests/integration/office \
  backend/tests/integration/test_office*.py \
  backend/tests/integration/test_agent_office_create_flow.py \
  backend/tests/integration/test_chat_office_tools.py \
  backend/tests/integration/test_chat_stream_office_refs.py -q
python -m pytest backend/tests/integration/test_excel_formula_roundtrip.py -q
python -m pytest backend/tests/unit/office/test_excel_eval.py \
  backend/tests/unit/office/test_worker_process.py \
  backend/tests/unit/office/test_capabilities.py -q
python -m ruff check backend/
npm run typecheck
npm run typecheck:electron
npx vitest run src/features/office/__tests__ \
  src/pages/__tests__/Office.workspace.test.tsx \
  src/shared/api/__tests__/officeApi.test.ts
node scripts/architecture-check.mjs
git diff --check
```

## 发布纪律

两线独立 PR，保留分支差异。架构棘轮只登记本批实际增长，已有较高条目不降低。推送前核对最新 base；若 base 移动，保留上游改动后再验证。未获 CI 通过不合并；不清理仍承担未合并成果的 worktree。
