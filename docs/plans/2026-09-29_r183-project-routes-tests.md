# R183 — `backend/api/project_routes.py` 单元测试（837 行 25 路由，此前零覆盖）

## 背景

projects 注册表的全部 HTTP 面（登记/更新/allowed-paths/资料/answer 保存/
删除/open/sessions/类型检测/约束/里程碑/类型配置/git-status）没有任何
单元测试。本轮补齐，不改生产代码。

## 方案

- DB 隔离：`SAGE_DB_PATH` 指向 tmp 文件 + 重置 `database._db` 单例 →
  `get_database()` 用真实 schema 建 tmp 库，全链路真实 SQL，无 mock。
- TestClient + `include_router(project_routes.router)`。
- git-status 用例用 `git init -b main` 真实仓库（同 r162 惯例）；
  save-answer 走 register → open 建立真实 workspace 绑定后插入消息。
- py38 约束：不使用 3.10+ API（上轮 hazard 扫描教训），写文件一律
  `write_bytes`。

## 验证

- `pytest tests/unit/api/test_project_routes.py`
- 仓库根 `ruff check` + `ruff format`
- `backend/tools/py38_hazard_scan.py backend/tests/unit/api/test_project_routes.py`

纯测试新增，无生产代码改动，不需要 win7 cherry-pick。
