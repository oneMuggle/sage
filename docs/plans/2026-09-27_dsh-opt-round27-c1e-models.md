# DSH 对标优化·第二十七轮：C1e——legacy 请求/响应模型归位 legacy_models.py

- **状态**：批次 A 交付中（分支 `feat-dshopt-r27-c1e-models`，基线 origin/main 含 R26）

## 0. 结论速览

legacy_routes.py 顶部的 13 个 Pydantic DTO（SessionCreate/Update、
ChatRequest、MessageResponse、ChatErrorInfo/Response、EvolutionLogResponse、
AgentToggle/Update/Create、InterruptRequest、SteerRequest、LearnRequest，
约 295 行）迁出至 `backend/api/legacy_models.py` 唯一归属。

行为常量（_PLAN_MODE_DIRECTIVE / _VALID_AGENT_ROLES / _STEER_MAX_CHARS）
留在 legacy_routes（路由语义的一部分，且为既有测试导入面）。

legacy_routes **再导出全部 13 名**——20 个测试文件的既有 import 路径
零变更；FastAPI 注解按真实定义模块解析，无影响。
legacy_routes 3977 → 3327 行。

## 验证

- 后端 unit 全量 9321 passed / 565 skipped（0 失败）
- 再导出身份冒烟（is 同一对象）；ruff + py38 AST 兼容
