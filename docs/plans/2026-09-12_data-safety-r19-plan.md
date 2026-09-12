# 数据安全与可迁移性（第十九轮批次 A）实施计划

> 日期: 2026-09-12 · 分支: `feat/data-safety-r19` · 基于 main @ f4042ec7
> 来源: 第十七轮差距分析后端报告 #3（"零自动备份"是本地优先 AI 应用的
> 数据安全底线差距）。与并发批次（manage-frontend / word-repair）零交集。
> Win7 对齐: **新功能不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。

## 背景（分析结论）

- **零自动备份**: 全 backend grep `backup` 无结果（workspace checkpoints
  只是工作区文件快照，不是数据库备份）。SQLite 单文件一旦损坏/误删，
  全部会话与记忆不可恢复。
- **记忆不可导出**: memory 路由只有 search/save/delete/list，无导出；
  用户被锁定在本机数据格式里，无法迁移或备份记忆资产。

## 批次任务

### A. SQLite 自动备份服务（M）

`backend/services/backup_service.py`（纯函数 + 薄 IO）：

- `get_backup_dir()`: `<db 所在目录>/backups/`（跟随 SAGE_DB_PATH 解析）。
- `create_backup(reason: 'startup'|'daily'|'manual') -> dict`:
  独立只读源连接 + `sqlite3.Connection.backup()` 在线备份 API（WAL
  安全，不阻塞主连接）→ `<tmp>` 落盘后原子 rename 为
  `sage-backup-<YYYYmmdd-HHMMSS>.db`；保留最近 7 份轮转清理。
- `list_backups() -> List[dict]`: name/size_bytes/created_at/reason。

### B. 调度接线（S）

- `SchedulerService.register_system_task(name, fn, cron_expr)`: 公共
  方法，镜像 `register_evolution_task` 但不要求 BaseEvolutionTask
  （id 前缀 `system/`，job_id `system/daily-backup`）。
- `main.py` lifespan: 启动时后台线程跑一次 `create_backup('startup')`
  （fail-safe，不阻塞启动），并注册每日 03:10 `create_backup('daily')`。

### C. 系统路由（S）

`backend/api/system_routes.py`（新模块，无条件 include）：

- `GET /system/backups`: 备份列表。
- `POST /system/backups`: 手动立即备份（返回备份条目）。

### D. 记忆导出（S）

- `GET /memory/export`（同模块）: episodic `get_recent(limit=10000)` +
  semantic `get_all()` → JSON 信封
  `{app, version, exported_at, episodic, semantic}`。

### E. Electron IPC + 设置页 UI（S）

- `commands.ts`: `system_backups_list` / `system_backup_create` /
  `memory_export` 三个命令映射。
- `MemoryTab.tsx` 新增"数据安全"卡片：立即备份按钮 + 备份列表
  （文件名/大小/时间）+ 导出记忆按钮（Blob 下载 JSON）。

## 测试

- 后端: `test_backup_service.py`（tmp DB 建表→备份→轮转→列表→手动
  创建；损坏路径 fail-safe）；`test_system_routes.py`（列表/创建/
  memory export 信封结构）。
- lint: ruff。

## 本批不做（后续候选）

- 备份恢复端点（需处理"恢复即覆盖"的确认与重启语义，L）
- 首启向导 / prompt 模板库 / 聊天内文件 RAG
