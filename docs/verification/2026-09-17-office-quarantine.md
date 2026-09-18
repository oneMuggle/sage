# Office 暂存隔离清理手册（2026-09-17）

适用对象：需要清理 `<workspace>/office/<doc_type>/<document_id>` 遗留暂存目录的运维/开发者。
本流程**默认不删除任何用户文件**：未引用的暂存只会被搬到隔离区，可随时恢复。

## 前置

- 使用应用真实数据库（不要指向新建空库或旧备份）。
- 建议先关闭应用，避免与进行中的导入竞争；工具自身有单写者锁与目录独占句柄，但不能替代停机窗口。
- 需要 Python 3.8+（`release/win7` 同样可用）。

## 步骤

1. 只读体检：

```bash
python -m backend.office.staging_quarantine plan \
  --database "/abs/path/sage.db" --workspace "/abs/path/workspace"
```

2. 干跑（默认，不搬文件，只列出将被隔离的目录）：

```bash
python -m backend.office.staging_quarantine quarantine \
  --database "/abs/path/sage.db" --workspace "/abs/path/workspace"
```

3. 实际隔离（加 `--execute`；可加 `--doc-type word` 限定类型、`--quiet-hours 72` 收紧静默期）：

```bash
python -m backend.office.staging_quarantine quarantine \
  --database "/abs/path/sage.db" --workspace "/abs/path/workspace" --execute
```

4. 查看隔离区与保留期：

```bash
python -m backend.office.staging_quarantine report --workspace "/abs/path/workspace"
```

5. 需要还原时：

```bash
python -m backend.office.staging_quarantine restore \
  --workspace "/abs/path/workspace" --quarantine-id "<report 中的 id>"
```

## 判定口径

| 状态 | 含义 | 处理 |
| --- | --- | --- |
| `referenced` | 命中任一引用来源、位于数据库仍登记的工作区内，或存在未完成的导入 sentinel（导入租约） | 保留 |
| `fresh` | 静默期（默认 24h）内有写入 | 保留，稍后重跑 |
| `unknown` | 缺表/缺列、扫描超预算或超时、路径歧义、空目录、符号链接、读取失败、导入 sentinel 损坏/超限/token 不符 | 保留并人工确认 |
| `no_reference_found` | 本次快照与列出的来源中未查到引用 | **仅此状态**可被隔离；仍非孤儿证明 |

导入中的目录不会被隔离：Electron 暂存导入会写 `.sage-import-v1.json`，完成后写
`.sage-import-completed`。只有前者存在时视为租约生效（owner 进程已死也只降级为待复核，不清算）；
两者都存在或都不存在时，按上表其余规则判定。

隔离位置：`<workspace>/office/.quarantine/<quarantine_id>/`，清单 `<workspace>/office/.quarantine/manifest.jsonl`
（append-only，含逐文件 SHA-256、原路径、隔离时间、`eligible_for_purge_after`）。

## 永久删除（可选，默认关闭）

保留期（默认 7 天）到期后仍需人工显式确认，且必须逐字重打 id：

```bash
python -m backend.office.staging_quarantine purge \
  --workspace "/abs/path/workspace" \
  --quarantine-id "<id>" --confirm-id "<同一个 id>" \
  --allow-permanent-deletion
```

任一条件不满足都会 `refused` 并退出码 2，文件保持原样。

## 退出码

- `0`：命令完成（含 `plan` 的 `no_reference_found` 结论，不代表可删除）。
- `2`：参数无效、数据库/工作区缺失、核对不完整、恢复或清除被拒绝。

## HTTP API（应用内接入）

同一套裁决也可以通过后端 API 触发，无需登录远端主机跑 CLI。实现见
`backend/api/office_quarantine_routes.py`，注册于 `backend/main.py`。

| 端点 | 作用 | 是否改动磁盘 |
| --- | --- | --- |
| `GET /api/v1/office/quarantine/plan?workspace_path=<abs>` | 只读体检，等价 CLI `plan` | 否 |
| `POST /api/v1/office/quarantine/run` | 计划 + 可选执行隔离 | `dry_run=false` 时是 |
| `GET /api/v1/office/quarantine/report?workspace_path=<abs>` | 隔离区清单与保留期 | 否 |
| `POST /api/v1/office/quarantine/{quarantine_id}/restore` | 还原一个隔离条目 | 是（复制回原路径） |

```bash
# 只读体检
curl -s -H "X-Sage-Local-Authorization: Bearer <token>" \
  "http://127.0.0.1:<port>/api/v1/office/quarantine/plan?workspace_path=/abs/path/workspace"

# 干跑（默认 dry_run=true，不搬文件）
curl -s -X POST -H "Content-Type: application/json" \
  -H "X-Sage-Local-Authorization: Bearer <token>" \
  -d '{"workspace_path":"/abs/path/workspace"}' \
  "http://127.0.0.1:<port>/api/v1/office/quarantine/run"

# 实际隔离（显式关闭干跑）
curl -s -X POST -H "Content-Type: application/json" \
  -H "X-Sage-Local-Authorization: Bearer <token>" \
  -d '{"workspace_path":"/abs/path/workspace","dry_run":false,"doc_types":["word"]}' \
  "http://127.0.0.1:<port>/api/v1/office/quarantine/run"

# 还原
curl -s -X POST -H "Content-Type: application/json" \
  -H "X-Sage-Local-Authorization: Bearer <token>" \
  -d '{"workspace_path":"/abs/path/workspace"}' \
  "http://127.0.0.1:<port>/api/v1/office/quarantine/<quarantine_id>/restore"
```

API 层的安全约束（与 CLI 同一口径，另有路由级测试守护）：

- **没有 purge 端点**。永久删除仍只有 CLI 一条路径，且需三重门禁；
  `test_no_purge_route_is_exposed` 断言任何 quarantine 路由都不含
  `purge`/`delete`/`remove`，也不允许 `DELETE` 方法。
- `safe_to_delete` 恒为 `false`，`report` 恒返回
  `automatic_deletion=false` / `purge_requires_human_confirmation=true`。
- `dry_run` 默认 `true`；请求体 `extra="forbid"`，多传字段（例如想象中的
  `allow_permanent_deletion`）直接 422，不会被静默忽略。
- 数据库以 `mode=ro` 只读打开，API 层不写主库。
- 输入早拒绝：工作区必须绝对且存在（400/404）、SQLite 文件必须存在（503）、
  `doc_types` 必须属于 `word|ppt|excel|pdf`（400）、`quarantine_id` 必须匹配
  严格字符集（400，路径分隔符永不进入文件系统调用）。
- 候选列表按 500 条截断，`candidates_total` / `candidates_truncated` 明示。
- 业务性拒绝（未知 id、原路径被占用、校验失败等）返回 HTTP 200 +
  `status="error"` + 机器码；传输/输入错误走 legacy 信封
  `{ok:false, error, message}`（见 `backend/api/error_contract.py`）。

## 仍未覆盖

- 数据库与文件系统的共同原子快照；工具以「复制后逐文件校验 + 漂移即保留」替代。
- 非 ASCII 编码或压缩后不可见的嵌入引用、外部备份与卷影副本。
- **前端 UI 入口与自动定时清理**：已有 CLI 与 HTTP API，但渲染端还没有界面，
  也没有任何自动触发；每次执行都需人工显式发起。
- 真实 Windows 7 与安装包回滚验收（发布门禁，需对应环境）。
