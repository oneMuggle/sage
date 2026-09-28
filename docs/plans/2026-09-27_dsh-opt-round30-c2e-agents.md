# DSH 对标优化·第三十轮：C2e——Agent API 路由组迁出 legacy_agent_routes

- **状态**：批次 A 交付中（分支 `feat-dshopt-r30-c2e-agents`，基线 origin/main 含 R29）

## 0. 结论速览

7 个 /agents* 端点（list/get/patch/toggle/create/import-files/export，
约 227 行）迁出至 `backend/api/legacy_agent_routes.py`。路径/行为零
变更，与 C1a/b/c/d 同款 include 模式。

- `_VALID_AGENT_ROLES` 白名单随迁（唯一使用方），legacy_routes 再导出
  保持测试导入路径；
- 模型直接从 legacy_models.py 导入（不再绕 legacy_routes）；
- skills/settings 两个既有 include 块位置保持在 legacy_routes。

legacy_routes 2956 → 2734 行。

## 验证

- /agents* 五路径注册冒烟；_VALID_AGENT_ROLES 再导出身份（is）一致
- tests/api 226 passed（4 个 orchestration_decision 失败系未提交改动
  触发 dirty-main 守卫，提交后即消失——与 clean main 基线对照实证）
- ruff 通过；py38 AST 3.8 兼容；baseline 无需更新（缩行）
