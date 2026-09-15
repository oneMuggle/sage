# P12 计划——P6 授权桥接对齐 release/win7（recents ∪ projects 注册表）

> 日期: 2026-09-15 · 基线: release/win7 `5d423534`（P11 #843 合入后）
> 分支: `feat/win7-wiki-authz-bridge` · 上游: main P6 #775
> 前置: P10 #836（win7 projects 核心）✅ / P11 #843（wiki Windows 解锁）✅

## 1. 动机

win7 上 P1 项目核心已就绪（P10）、wiki 全链路已解锁（P11），但授权仍是
"仅 recents 成员"——侧栏登记的项目不能直接做 wiki 操作。本批移植 P6 的
**授权桥接**：`authorize_registered_project`（约 24 个 wiki 端点唯一门
禁）接受 recents ∪ projects 注册表并集（fail-closed 不变），并做
wiki open/create → 侧栏清单的双登记。

## 2. 移植清单（4 文件，全部小块）

| 文件 | 改动 |
| --- | --- |
| backend/wiki/project_authorization.py | `_projects_registry_paths()`（lazy import ProjectRepository，异常 → 空列表）+ `authorize_registered_project` 并集判定（与 recents 分支同款 try/except fail-closed） |
| backend/wiki/mcp_server.py | `_authorized_project_root` 的 registered 集合并集注册表路径 |
| backend/data/project_repo.py | 新增 `register_quietly()`（容错登记，跨域写侧联动用） |
| backend/api/wiki_routes.py | open/create 两处 record_recent 后 `register_quietly` |

消费方零改动；GET /wiki/recent-projects 响应形状不变。

## 3. 测试

- `test_project_authorization.py` +3：仅注册表命中 / 注册表异常
  fail-closed / 命中但目录删除 404；
- 集成：wiki open/create 双登记进 projects 表（win7 分支 wiki/files 已
  解锁，端点级用例 Windows 可真实执行——与 main P6 不同，无需 skip）；
- 消费方回归（recent_projects / search / project routes）。

## 4. py3.8 / 对齐

全部 py3.8 兼容（lazy import + typing.List）；CI Win7 LTS 通道真实验证；
main 侧无改动。
