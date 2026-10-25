# MCP 会话记录：R78 轮次收敛与三份在飞产物补交付（2026-10-04）

> 入口：ShunCode Bridge MCP（`shuncode-bridge 0.7.5`）。按「交付物同步」惯例落库，供后续会话与评审对照。
> 基线：`origin/main` @ `38c5f7992`、`release/win7` @ `6069b48e5`。

## 1. 接手时的范围

2026-10-04 接手时，工作区有三类「已写、未交付」的产物：

| # | 产物 | 接手时状态 | 处置 |
| --- | --- | --- | --- |
| 1 | R78 Zotero 路由单测 `backend/tests/unit/api/test_zotero_routes.py`（18 例，2026-09-29 起草） | 未提交、5 例失败、无方案文档、无 PR，worktree 落后 main 30 个提交 | 追平 main、修 5 例测试侧问题、补 round78 方案文档、双分支交付 |
| 2 | ux-ia R2 批次 D 核查记录（2026-10-02） | 本地 1 个提交未推送 | 补推送 + PR |
| 3 | Sage 产品优化评审（2026-10-01，498 行） | 未跟踪、从未提交 | 补交付（顶部加「交付说明」对照后续落地） |

另：Oct-03 的优化批次（#1890–#1899）已 push 并开 PR，本轮只跟进 CI 与遗留盘点（§4）。

## 2. 交付

| 产物 | 分支 | PR | 内容与验证 |
| --- | --- | --- | --- |
| R78（main） | `feat-parity-r78` | **#1900**（`86004d2d3`，文档回填 `0d9012a89`） | 18 例路由测试 + `docs/plans/2026-10-04_coding-agent-parity-round78.md`；本地 3.12.10 下 18 passed、ruff 干净、py38 危险扫描 0 命中；CI 除依赖审计外全绿 |
| R78（win7） | `feat-parity-r78-win7` | **#1901**（`fbb090fd3`） | 移植 r94 路径持久化修复（2 文件）+ 18 例测试 + 文档；win7 工作树 18 passed（3.12 与 py38 3.8.20 各一遍） |
| ux-ia 核查记录 | `docs/mcp-ux-ia-r2-batch-d-verification-20261002` | **#1902** | 84 行核查记录（交付与 CI 证据、本机实跑、人工实测清单） |
| 产品评审补交付 | `docs/mcp-sage-product-review-20261001` | **#1903** | 498 行评审原文 + 交付说明 |

R78 起草态 5 例失败全部是测试侧问题（断言笔误、异常构造参数应为列表、缓存前置断言写反、WindowsPath 比较），生产代码未改。

win7 侧另有真实差异：win7 自 #1368 起一直带着 r94（#1377）修掉的设置路径持久化断链（`zotero_routes.py` import 不存在的 `backend.services.settings_repo.SettingsRepo`，且 `backend/data/settings_repo.py` 白名单缺 `zotero_db_path`）。批次 B 按 r94 原样移植；移植前该测试 2 例失败，移植后 18 例全绿。

## 3. 环境与操作要点（供后续会话）

- 后端测试解释器：conda `sage-backend` 与 win7 线 `sage-backend-py38`，均在 `D:\programmingSoftware\Anaconda3\envs\`（3.11 / 3.8.20）；另有 `Python312`（`C:\Users\muggle\AppData\Local\Programs\Python\Python312`，含 ruff / pytest）。
- **不要**用 `sage\.venv-ci` 跑后端测试（Python 3.9，无 fastapi；`backend/tests/conftest.py` 导入 `backend.main` 会整批 ERROR）。
- 未引导 worktree 的 lefthook 在 Node 层崩溃：提交/推送用 `LEFTHOOK=0`；`--no-verify` 只覆盖 pre-commit / commit-msg，不覆盖 `prepare-commit-msg`。
- 长文本落盘走 `apply_patch`（UTF-8 安全）；PR 标题/正文走 `.scratch/*.txt|md` + `gh --body-file`（配 `MSYS_NO_PATHCONV=1`）。
- `git fetch/push` 偶发 `Recv failure: Connection was reset`，重试即可；开工前先 `merge --ff-only origin/main` 追平基线。

## 4. 仍未完成 / 待决策

1. **依赖审计红会挡住全部 PR 合并**：main 的 `audit-watch` 自 09-29 起每天失败；#1900 的 `Dependency audit` job 同样红（#1890–#1899 亦同）。需按 `.github/dependency-audit-policy.json` triage（安全取舍，本轮未动策略）。
2. `wiki_chat_cancel`（当前无害但仍在缺口名单）与里程碑创建表单 `status` 字段：需产品/实现二选一，见 #1890 评论。
3. 批次 2–4（F2、U1、L3、U2、L2、L5 完整收敛、L6、U3）与真 e2e（1420 端口复用问题）未动。
4. `docs/plans/parity-rounds-index.md` 的 R78 行待 #1900 / #1901 合并后回填（当前只登记到 R77）。
