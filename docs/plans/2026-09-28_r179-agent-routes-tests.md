# R179：legacy_agent_routes（Agent API 路由组）单测补齐（2026-09-28）

- **上游文档**：parity-loop-sop；C2e Agent API 路由组（7 端点拆出）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`api/legacy_agent_routes.py`（248 行，最后一个未测试的中型模块）——
7 个 /agents* 端点的路由组。本轮补齐 ~15 例。

## 覆盖矩阵

1. list_agents 返回列表；2. get_agent_by_id 命中/未命中 404；
3. update_agent role 白名单 422；4. update_agent max_iterations
范围 422；5. update_agent 不存在 404；6. update_agent 成功（partial
update 语义）；7. toggle 成功；8. toggle 不存在 404；9. create 成功
+ id 冲突 409。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
