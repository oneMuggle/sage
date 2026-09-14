# P8 计划——wiki recent_projects 存储迁移到 projects 注册表（SQLite）

> 日期: 2026-09-15 · 基线: main `8a2f4ab3`（P7 #810 合入后）
> 分支: `feat/wiki-recents-sqlite-p8` · 前置: P1 #727 / P6 #775（授权桥接）/ W5 #802（Windows 解锁）

## 1. 动机与前置确认

P6 桥接后 recents（JSON）与 projects 注册表（SQLite）双轨并行：授权/
MCP 已并集，但**存储仍是两份**——wiki 侧 JSON（MAX_RECENT=10、intent、
opened_at 秒）与侧栏 projects 表（无 intent、ms、上限 50）存在语义与
生命周期漂移。#760 解除 POSIX 阻塞、W5 解锁 wiki Windows 全链路后，
迁移条件成熟：**recents 成为 projects 注册表的一个只读投影**，单一事
实源落在 SQLite。

## 2. 语义处理（本批核心决策）

| 维度 | JSON 现状 | 迁移后 | 决策依据 |
| --- | --- | --- | --- |
| intent | `"create"\|"open"` 必填 | projects 加**可空 `intent` 列**；record_recent 显式写入；NULL（侧栏登记等来源）读侧映射 `"open"` | 保真 wiki 语义；侧栏来源本就是"打开"性质 |
| opened_at | float 秒 | 不新增列：读侧 `last_opened_at/1000.0` 映射 | 避免冗余时间戳 |
| name | wiki create 可自定义 | record_recent upsert 时更新 name（最后写入者胜）；侧栏 register() 仍用 basename 且不覆盖 | wiki 命名权在 wiki 流 |
| MAX_RECENT=10 | 截断清单 | `load_recent()` 读侧 `LIMIT 10`（注册表本身保留 50，不删行） | 截断是 recents 投影语义，不是注册表生命周期 |
| 越窗删除 | save_recent 重写即丢 | save_recent 仅删除"上一窗口内且不在新清单"的行，**绝不触碰窗口外的注册行** | 保护侧栏清单 |

## 3. 实现

1. **database.py**：projects 表追加 `intent TEXT` 列（PRAGMA table_info
   守护的幂等 ALTER，NULL 兼容旧行）。
2. **recent_projects.py 重写为 SQLite 适配器**（公共 API 全保）：
   - `load_recent()`：先 `_ensure_legacy_import()`（一次性：旧 JSON 存在
     → 逐条 upsert 进 projects（opened_at×1000）→ 文件改名 `.migrated`
     备份；损坏/失败 fail-open），再 SELECT 前 MAX_RECENT 映射
     RecentProject（NULL intent → "open"）；异常 → []（fail-closed 空清单）；
   - `record_recent(path, name, intent)`：校验 intent → upsert（含
     name/intent/last_opened_at），删除 JSON 依赖（wiki/files import 一并
     移除——recent_projects 从此不再依赖 POSIX/平台原语）；
   - `save_recent(items)`：见 §2 越窗删除语义；
   - `most_recent_parent()` / `RecentProject` / `user_data_dir` /
     `recent_projects_file`（迁移期备份路径用）：不变。
3. **消费方零改动**：authorize_registered_project（P6 并集，迁移后两源
   同表，无害）、MCP、search_routes、entity_refs、GET /wiki/recent-projects
   响应形状不变（intent 列保证）。

## 4. 测试

- 重写 `test_recent_projects.py`（SQLite 语义）：去重/upsert、MAX_RECENT
  截断（读侧投影）、intent 校验 ValueError、most_recent_parent、
  **legacy JSON 导入**（SAGE_USER_DATA_DIR 指向含旧 JSON 的目录 →
  load_recent 迁移入库 + `.migrated` 改名）、损坏 JSON → 忽略、
  intent 写入后 GET 投影。
- `test_security_final_paths.py::test_recent_projects_keeps_payload...`
  重写：fixed-temp-symlink 攻击随 JSON 弃用而失效，改为断言 save_recent
  经注册表持久化且不触碰杂散 tmp 文件。
- `test_wiki_recent_projects_route.py`（monkeypatch record_recent）不变。
- 集成：record → GET /recent-projects 投影含 intent；projects 表行同步。

## 5. win7 对齐

recent_projects.py 移除 wiki/files 依赖后不再触碰平台原语（win7 LTS 的
wiki/files 仍 POSIX-only 不受影响）；database.py projects intent 迁移为
幂等 ALTER（win7 分支 database.py 分歧大，cherry-pick 时照其本地结构
插入同款守护块）；pydantic v1/v2 双版本兼容写法保留。
