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

## 仍未覆盖

- 数据库与文件系统的共同原子快照；工具以「复制后逐文件校验 + 漂移即保留」替代。
- 非 ASCII 编码或压缩后不可见的嵌入引用、外部备份与卷影副本。
- 自动定时清理与 UI 入口（当前仅 CLI + 人工触发）。
- 真实 Windows 7 与安装包回滚验收（发布门禁，需对应环境）。
