# 网页访问 Round 21：DL2 后台下载任务化（2026-09-19）

- **上游文档**：Round 5 §2.1 DL2（后台任务化 + 进度 + 取消，本方案落地）；Round 15（web_metrics 模式参照）

## 批次

1. **J1 新模块 `backend/tools/download_jobs.py`**：`DownloadJobManager`——线程安全任务表
   （dict + Lock），`ThreadPoolExecutor(max_workers=2)` 执行；job 生命周期
   pending/running/success/failed/cancelled；`submit(url, kwargs) -> job_id`；
   `status(job_id)`；`cancel(job_id)`（ Cooperative 取消：running 中标记 cancel_requested，
   下载循环每 chunk 检查）；全局单例 + `reset()`（测试）。
2. **J2 工具接线**：`http_download` 增 `background: bool = false`——true 时提交后台任务
   立即返回 `{job_id, status: "pending"}`；新工具 `download_status`（查单任务/全部）与
   `download_cancel`。工具注册 registry + tool_names 同步。
3. **T**：单测（生命周期/并发上限/cancel/status 工具/端到端 respx 后台下载）。

## 口径

- 任务表进程内存态（重启清零，与 web_metrics 同口径）；完成后结果保留供 status 查询
  （含最终 path/bytes/sha256）。
- cancel 语义：pending 直接 cancelled；running 置 cancel_requested，下载循环在
  chunk 边界检查并中断（.part 保留供续传）。
- 安全口径不变：同 URL 校验 / check_host / 限速沿用 download_tool 现有路径。
