# DSH 对标优化·第二十五轮：C1d——settings / preferences 路由组拆分

- **状态**：批次 A 交付中（分支 `feat-dshopt-r25-c1d-settings`，基线 origin/main 含 R24）

## 0. 结论速览

将 legacy_routes.py 中 settings / preferences 四个路由
（`GET/PUT /settings`、`GET/PUT /preferences/{key}`）+ `_migrate_default_protocol`
辅助函数迁出至 `legacy_settings_routes.py`（约 -200 行）。延续 C1a/b/c
的物理拆分模式：router 无 prefix、经 legacy_router include 链挂载，
路径/行为零变更。

设置三模型（LegacySettingsRequest/Response、LegacyPreferenceItem）保持
在 legacy_skills_routes.py（C1b R15 既有格局），新模块按需导入，不搬动
模型归属。

## 变更

- 新增 `backend/api/legacy_settings_routes.py`（约 230 行）：
  with_db_lock（D3 make_with_db_lock 模式）+ 四路由 + 辅助函数
- `legacy_routes.py`：删除原块 + include（净 -200 行左右）

## 不做

- 模型归属搬移（settings_models.py 收编三模型留后续轮次）
- hex_routes 的同语义端点（两套 API 并存是既定兼容格局）

## 验证

- 既有 settings/preferences 相关测试回归（TestClient 路径级）
- ruff + py38 AST 兼容；baseline：legacy_routes 缩行无需更新，
  新文件未入基线且低于全局上限
