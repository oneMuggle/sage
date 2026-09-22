# R94 批次计划 —— Zotero 测试收口 + 设置路径持久化断链修复

日期：2026-09-22 ｜ worktree：`.worktrees/feat-r94-zotero-tests`（基于 origin/main d506cc6d）

## 背景与发现的真 bug

#1367/#1370 落地的 Zotero 只读集成，扫描发现两个断链：

1. **模块与类名双重错误**：`backend/api/zotero_routes.py` 两处 import
   `from backend.services.settings_repo import SettingsRepo` —— 该模块不存在
   （实际为 `backend/data/settings_repo.py` 的 `SettingsRepository`）。后果：
   - `_get_configured_db_path()` 静默走 `except` → 只剩 `ZOTERO_DB_PATH`
     环境变量兜底，设置页配置的路径永远读不到；
   - `POST /zotero/path` 落库失败 → 仅 warning 日志，仍返回 `ok: true`，
     用户以为保存成功（静默数据丢失）。
2. **KEYS 白名单缺 key**：`SettingsRepository.set/get` 只接受 `KEYS` 白名单
   内的 key，`zotero_db_path` 未列入 —— 即使修好 import，`set()` 也会抛
   ValueError 被吞掉。

## 批次内容

### 修复（生产代码，2 文件）

- `backend/api/zotero_routes.py`：两处 import 纠正为
  `backend.data.settings_repo.SettingsRepository`。
- `backend/data/settings_repo.py`：KEYS 白名单加 `"zotero_db_path"`。

### 测试（2 文件，9 用例）

- `backend/tests/unit/test_zotero_routes.py`（9 用例，新增）——fake client
  注入模块单例：status 可用/不可用（200+error 语义）、search 参数透传与
  summary 映射、limit 越界 422、item detail 映射与 404、annotations 与 404、
  collections parent_key 透传、/path 落库 + 单例清空、构造失败 503、
  KEYS 白名单回归。
- `src/shared/api/__tests__/zoteroClient.test.ts`（8 用例，新增）——6 方法
  通道约定、listCollections 无参 parent_key 归一化 null、IPC 失败原样抛出
  （无 handleApiError 包装契约）。

## 验证矩阵

- 本机：py_compile 三文件通过；vitest zoteroClient 8/8 通过（junction + 即摘协议）。
- CI：Backend (Python) 跑 test_zotero_routes + test_settings_repo 全量回归；
  Frontend (TypeScript) 类型检查 + vitest。

## win7 对齐

- Zotero 功能仅存在于 main（#1367 未 cherry 到 release/win7），本修复不回移。

## 风险

- `setup_test_db` autouse fixture 提供临时 DB，`SettingsRepository()` 真实构造
  在测试内安全（get 未配置 key 返回 None，不触发外部 IO）。
