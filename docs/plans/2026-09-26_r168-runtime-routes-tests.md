# R168：runtime_routes 分派层单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；runtime_probe/exec/diagnose 的 HTTP
  路由分派层
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`api/runtime_routes.py` 的分派核心（_get_chat_service / _require_tool /
_dispatch / _dispatch_structured）此前零测试。工具失败走 200 +
success=false 的 fail-open 语义、output JSON 反序列化契约（成功与失败
路径都解析）必须钉死。

## 覆盖矩阵（约 13 例）

_get_chat_service：1. chat_service 缺失 → 503；2. 存在 → 返回。
_require_tool：3. 已注册放行；4. 未注册 → 503。
_dispatch：5. 成功 → success/output 透传；6. output None → 键省略；
7. error → 包含；8. metadata → dict 化；9. 工具失败 → 仍 200 且
success=false。
_dispatch_structured：10. output JSON 字符串 → 反序列化为 dict；
11. 非法 JSON → 保留原字符串；12. 非字符串 output 原样；13. 失败路径
的 output JSON 也反序列化（前端可读 error/timed_out）。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
