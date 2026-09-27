# R162b→r166（顺延）：Hooks REST 路由单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；hooks Phase 1 内置钩子元数据 + Phase 4
  项目信任管理
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`api/hooks_routes.py`（219 行，Hooks REST 路由：builtins 元数据、历史
查询/清空、项目信任 trust/untrust/status 五端点）此前零测试。直接调
用路由函数（与 test_worktree_routes 同风格），forbidden_origin 守卫
patch 掉，信任持久化 patch SettingsRepository + project_config。

## 覆盖矩阵（约 14 例）

builtins：
1. 返回注册表四钩子列表（id 齐全）；2. origin 守卫阻断时透传响应。

project/status 与 trust：
3. 相对路径/不存在路径 → 400；4. 未信任 → trusted=False、
config_exists 按 .sage/hooks.json；5. 已信任 → hook_count 读取；
6. trust 成功 → {ok, trusted}；7. trust 持久化异常 → 500；8. untrust
成功/失败。

history：
9. list 透传 records 字段；10. 过滤参数透传（hook_id/event/since/
limit）；11. clear → {ok, deleted}。

origin 守卫：
12. forbidden_origin_response 返回非 None 时短路透传。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。
