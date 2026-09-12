# 数据安全第二批——备份恢复与记忆导入（第二十一轮批次 A）实施计划

> 日期: 2026-09-12 · 分支: `feat/data-restore-r21` · 基于 main @ e3c01d0f
> 来源: 第十七轮差距分析数据安全线的收口批（R19 建了备份/导出，本批补
> "恢复/导入" 使数据可回流）。与并发批次（gateway/memory-consolidation/
> excel）零交集。
> Win7 对齐: **新功能不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。

## 背景

R19 (#672) 落地了自动备份（轮转 7 份）、手动备份、备份列表与记忆
JSON 导出。但数据只能"出"不能"回"：备份文件无法恢复、导出的记忆
JSON 无法导入新环境——对标 Cherry Studio / AnythingLLM 的
"迁移与灾备"能力仍缺一半。

## 批次任务

### A. 备份恢复（M）

`backend/services/backup_service.py` 增补 + `system_routes.py` 新端点：

- `restore_backup(name) -> dict`：
  1. 校验 `name`（严格 `_BACKUP_RE` 白名单，路径拼接防御，拒绝 `..`/分隔符）；
  2. **恢复前先做一次 `pre-restore` 安全备份**（`create_backup('manual')`
     改名语义——防恢复失败丢失现有数据）；
  3. WAL 安全换库：关闭主连接池不可行（桌面单进程），采用**文件级原子
     替换 + 标记重启生效**：把备份复制为 `<db_path>.restore-pending`，
     写入 `restore-marker.json`（源备份名/时间）；下次启动时
     `apply_pending_restore()` 检测 marker → 原子替换 db 文件 → 删除
     marker → 日志记录。返回 `{ok, applied_at_startup: true, backup}`。
- `main.py` lifespan 早期（init_db 之前）调用 `apply_pending_restore()`。

### B. 记忆导入（M）

`POST /memory/import`（system_routes）：

- 接受 R19 导出信封 `{version, episodic, semantic}`；
- 逐条经既有 MemoryManager 仓库写入（episodic.save / semantic save
  通道），按内容 hash/已有 id 去重（已存在同 id 跳过）；
- 返回 `{imported, skipped, failed}` 报告；单条失败不中断（fail-safe
  汇总）。

### C. 设置页 UI（S）

`MemoryTab` 数据安全卡片扩展：

- 备份列表每项加"恢复"按钮（两步确认，提示"下次启动生效"）；
- "导入记忆"文件选择 + 上传（JSON 解析在前后端各做一层防御）。

## 测试

- `test_backup_restore`: marker 写入 / 启动应用（tmp db 原子替换）/
  非法 name 拒绝 / pre-restore 安全备份存在。
- `test_memory_import`: 空集 / 去重跳过 / 单条失败不中断 / 信封版本
  防御。
- ruff 全绿。

## 本批不做

- 聊天内文件 RAG（L，独立大项）
- 首启向导 / prompt 模板库（M，后续批）
- MCP OAuth 鉴权头（M）
