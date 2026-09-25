# R129：种子 Agent 适配器 + 下载任务工具单测补齐（2026-09-25）

- **上游文档**：parity-loop-sop；编排 Router 适配器 / DL2 下载任务工具
- **范围**：后端 only，两个测试文件新增，零生产代码改动

## 0. 结论速览

`orchestration/agent_adapter.py`（65 行，种子 Agent 仓库 → Router 注册表
的薄适配：enabled 过滤 / tools JSON 字符串降级解析）与
`tools/download_status_tool.py`（94 行，download_status / download_cancel
双工具：单查/全查/未找到/仅 pending 可取消）此前零测试。

## 覆盖矩阵（约 17 例）

### `backend/tests/unit/orchestration/test_agent_adapter.py`（9 例）

1. list_agents 映射 dict profile → orchestration Agent（agent_id/name/
   status=active/capabilities/max_concurrent_tasks=2/default_permission）；
2. enabled=False 跳过；缺 enabled 键默认启用；
3. tools 为 JSON 字符串 → 解析为 capabilities；损坏 JSON → 回退
   [role]；tools 缺失 → [role]（缺 role → "general"）；
4. name 缺省回退 id；5. get_agent 命中/未命中/禁用 → Agent/None/None；
6. repo=None 时懒加载 AgentRepository（patch 构造点断言调用）。

### `backend/tests/unit/tools/test_download_status_tool.py`（8 例）

patch `download_status_tool.get_download_job_manager` 返回 fake manager：
1. schema：两工具名称、cancel 的 job_id required；2. status 带 job_id
（strip）→ 单任务；3. 不存在 → job_not_found 文案；4. 无 job_id 全查
→ jobs 列表；5. 空表 → jobs: [] + note；6. cancel ok → success 且
content 原样；7. cancel 失败（非 ok）→ error 透出；8. job_id 空白容错。

## 验证

- pytest 新文件 + 邻近用例；ruff（CI 同版本 0.4.4）。

## 明确不做

- 不测 DownloadJobManager 真实线程池（download_jobs 另有域）。
