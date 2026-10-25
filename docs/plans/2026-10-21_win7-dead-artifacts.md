# win7 死文件清理：调试残留与无引用模块

- 日期：2026-10-21
- 分支：`chore/win7-dead-artifacts-20261021`（基于 `origin/release/win7` @ `28bde1284`）
- 依据：`docs/win7-sync/parity.md` B6 经验「win7 独有文件逐个 `git grep` importer；无引用即删，避免长期漂移」

## 1. 背景

按 parity 口径，`release/win7` 有 90 个 main 没有的非文档文件。逐个统计引用后，
其中绝大多数是**测试文件**（按文件名被 pytest / vitest 收集，本就没有文本引用）与
**win7 必要文件**（`backend/compat/win7/`、`scripts/win7/`、`resources/win7-fix/`），
真正可清理的是两类：调试残留垃圾、以及零 importer 的模块。

## 2. 判定方法

对每个 win7 独有文件，在 `release/win7` 全树 `git grep` 其 basename / 模块名：

```bash
git grep -l -F <basename> origin/release/win7 -- . ':(exclude).superpowers'
```

**不能只看计数**：测试文件恒为 0 引用，脚本类也可能只被文档引用。因此逐个用文档与动态用法复核。

## 3. 删除清单

### 3.1 调试残留（无任何引用，内容是临时产物）

| 文件 | 证据 | 判断 |
|---|---|---|
| `jobs_dump.json` | 22.9 KB，内容为 GitHub API 响应 `{"total_count":9,"jobs":[...]}`；全树 0 引用 | 误提交的调试转储，删 |
| `chg.txt` | 402 B，内容是变更文件清单；除 `parity-allow.txt` 台账与 `classify.csv` 记账外 0 引用 | 误提交的临时清单，删（同时移除台账条目） |
| `.right-panel-r5r6-pr-body.md` | 全树 0 引用，文件名即 PR 正文草稿 | 误提交，删 |

### 3.2 零 importer 模块

| 文件 | 证据 | 判断 |
|---|---|---|
| `src/widgets/todo/TodoForm.tsx` | 全树仅命中自身定义行，无任何 import | 未接线的孤立组件，删（如需保留请在本 PR 说明） |
| `src/shared/api/types-multimodal.ts` | 仅出现在 `docs/win7-sync/classify.csv` 记账中，无 import | 无消费者的类型模块，删 |

### 3.3 保留（有实际引用，不删）

| 文件 | 理由 |
|---|---|
| `scripts/check_browser_environment.py` | `docs/plans/2026-09-17_multi-browser-support.md` 记录了手动运行方式（4 处引用） |
| `scripts/win7/cp.ps1` | `docs/win7-sync/README.md` 登记为本地 cherry-pick 辅助 |
| `backend/compat/win7/*`、`scripts/win7/*.py`、`resources/win7-fix/*` | win7 平台必需 |
| `backend/tests/**`、`src/**/__tests__/**`、`electron/__tests__/**` | 测试由框架按名收集 |

## 4. 同步更新

- `docs/win7-sync/parity-allow.txt`：移除 `chg.txt` 条目（该文件已删除，留条目会让台账失真）。

## 5. 验证

- 删除后 `git grep` 复核无残留引用。
- PR 上跑 `Frontend (TypeScript)` 与 `Backend (Python)`，确认无 import 断裂。
- 不做任何代码修改，纯删除 + 台账更新。

## 6. 影响与回滚

- 影响：删除 5 个文件、台账减 1 行。不改运行逻辑。
- 回滚：`git revert` 即可恢复全部文件。
