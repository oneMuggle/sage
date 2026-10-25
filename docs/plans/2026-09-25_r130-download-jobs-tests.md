# R130：DownloadJobManager 任务管理器单测补齐（2026-09-25）

- **上游文档**：parity-loop-sop；DL2（Round 21）下载任务管理器
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`tools/download_jobs.py`（~160 行，ThreadPoolExecutor + 线程安全任务表 +
诚实 cancel 语义 + 终态淘汰 + 全局单例）此前零测试——r129 覆盖了查询
工具，本轮钉住管理器本体：生命周期状态机与并发契约。

## 覆盖矩阵（15 例）

1. submit 返回 12 位 hex job_id，初始 PENDING；2. fake 工具 success →
SUCCESS 且 result=content；3. ToolResult 失败 → FAILED + error；
4. 工具抛异常 → FAILED + str(exc)；5. cancel pending → ok=True、
CANCELLED、error="cancelled by user"、run kwargs 移除（worker 空转）；
6. cancel running → ok=False cannot_cancel（诚实口径）；
7. cancel 未知 → job_not_found；8. status 返回副本（改返回值不影响
表内）、未知 → None；9. all_jobs 返回副本字典；10. reset 清空；
11. 终态淘汰：压小 MAX_FINISHED_JOBS，超额终态按 created_at 淘汰最旧；
12. 单例：get 恒同实例、reset 后换新实例；
13. 排队中被取消的任务被 worker 取到时早退（status 保持 CANCELLED，
不覆盖）。

fake 工具用 threading.Event 控制节奏，轮询等待异步迁移（有界）。

## 验证

- pytest 新文件 + tools 邻近用例；ruff（CI 同版本 0.4.4）。

## 明确不做

- 不测真实 HTTP 下载（HttpDownloadTool 另有域）。
