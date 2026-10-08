# R185 — `backend/data/orchestration_repo.py` + `backend/data/agent_repo.py`
# 单元测试（369 + 202 行，此前零覆盖）

## 背景

多智能体编排的 Task/Team 持久层与 AgentProfile 持久层没有任何测试。
本轮补齐，并顺带修复扫测中发现的 `get_ready_tasks` 依赖判定缺陷。

## 生产修复（需 win7 cherry-pick）

`TaskRepository.get_ready_tasks` 原实现只把 CREATED 任务载入
`all_tasks`，再判 `dep_id in all_tasks and status == COMPLETED` ——
已完成依赖永远不在集合里，带依赖的任务**永远 ready 不了**（已用真实
库复现：dep=COMPLETED + main CREATED blocked_by=[dep] → 返回 []）。
修复为对全量任务求依赖状态；`team_id` 过滤后置。当前无运行时调用方
（仅 task_registry 透传），属公开 API 契约修复。

## 方案

- conftest autouse `setup_test_db` 真实临时库，不 mock SQL。
- TaskRepository：create/get/update/delete、INSERT OR REPLACE 幂等、
  list 过滤（status/team_id/limit/offset/priority 排序）、packet 往返
  （含 recovery/escalation policy）、get_ready_tasks 全分支。
- TeamRepository：CRUD + status 过滤 + 缺失 404 语义。
- AgentRepository：list_all/get/count、upsert 默认值与 enabled 序列化、
  set_enabled 行数语义、update 部分字段（JSON 字段序列化、id 不可改、
  空字段集回退存在性判断）、seed_defaults_if_empty 幂等。

## 验证

- `pytest tests/unit/data_repo/test_orchestration_repo.py
  tests/unit/data_repo/test_agent_repo.py`
- 仓库根 ruff check + format；py38 hazard 扫描
