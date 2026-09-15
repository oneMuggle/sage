# Win7/Main 最大化对齐 — 工作区文档

> 分支：`chore/win7-main-sync` 基于 `origin/release/win7`  
> 端口：`PYTHON_BACKEND_PORT=8776` / `VITE_DEV_PORT=1431`  
> 方案：`docs/technical/99-win7-main-sync.md`；看板：`parity.md`（手工）+ `parity-auto.md`（脚本生成，不入库）

## 状态（2026-09-15）

Phase 0/1 ✅ → Phase 2 B1–B6 ✅（origin/main 全量并入，残差 226 文件全部为 win7 必要差异）→ **Phase 3 自动化 ✅**

## 快速开始

```powershell
# 1. 对齐看板：main vs 当前分支；有漏合入 / 实质差异 / 未登记 win7 独有文件时非零退出
python scripts/win7/parity_report.py --fail-on main-only,real,win7-only

# 2. 演练一次 main → win7 自动同步（不改任何分支）
python scripts/win7/auto_sync.py --dry-run

# 3. 真正同步（本地）：新建 sync/win7-main-YYYYMMDD 分支、merge、py38 回写 + 门禁、提交
python scripts/win7/auto_sync.py --commit --report sync-report.md

# 4. 单独的 py38 语法门禁 / 回写
python scripts/check_py38_compat.py
python scripts/py38_compat_rewrite.py backend packages/sage-core   # 需 py3.10+ 与 libcst
```

## 脚本一览（`scripts/win7/`）

| 脚本 | 作用 | CI 里谁在用 |
|------|------|-------------|
| `classify_diff.py` | 把异动文件分 A/B/C/D 四类；**D 类 = 发布/打包冻结件**，`auto_sync` 冲突时自动取 win7 侧 | `parity_report` / `auto_sync` 内部 import |
| `parity_report.py` | 生成 `parity-auto.md`：残差分级 typing-only / frozen / intentional / win7-only / main-only / real；`--fail-on` 守门；`--write-allow` 登记 | `win7-sync.yml` → job `parity` |
| `auto_sync.py` | `git merge --no-ff origin/main` → D 类 ours → `py38_compat_rewrite` → `check_py38_compat` → 提交；冲突时输出分类报告 exit 2 | `win7-sync.yml` → job `sync` |
| `cp.ps1` | 本地 cherry-pick 辅助（B1/B2 时期） | — |

## 残差分级怎么算

`parity_report.py` 对每个异动文件取 `git diff -U0`，把两侧改动行做归一化后比较：
`Optional[X]`⇔`X | None`、`List[`⇔`list[`、`builtins.list[`、`isinstance(x,(A,B))`⇔`isinstance(x,A|B)`、
typing import 行忽略、`from pydantic import …` 与 `from backend.compat.win7.pydantic_compat import …` 合并。
归一化后仍不同 → `real`。`real` / `win7-only` 若命中 `docs/win7-sync/parity-allow.txt` → `intentional`。

**`parity-allow.txt` 是审计台账**：B4–B6 收口时用 `--write-allow` 一次性登记了 124 项
（memory 可追溯/SSE/auto_memory、py38 conftest、win7 专属测试、compat 层、Memory 3-tab 页等，
理由见 `parity.md` B3/B4-B6 经验）。以后新增条目必须在 PR 里说明理由。

## `win7-sync.yml` 工作流

- **parity** job：main push / 每日 03:30 CST / 手动。跑 `parity_report.py --base origin/main --head origin/release/win7 --fail-on main-only,real,win7-only`，
  报告进 Step Summary + artifact `win7-parity`；出现需处理差异即 fail（提醒 owner，不阻断 main）。
- **sync** job：每日 / 手动（`do_sync`）。checkout `release/win7`，`auto_sync.py --commit`：
  - exit 0：推 `sync/win7-main-YYYYMMDD` 并开 PR → 触发 `ci.yml` 的 `backend-py38`（Python 3.8 + 锁定依赖 + 40 分钟 pytest）
  - exit 2：把冲突现场（含 `<<<<<<<` 标记）提交到同名分支并开 **draft PR**（label `needs-human`），报告里按 A/B/C 给出处理建议
  - exit 1：py38 门禁失败 → job 失败
- 需要仓库 label：`win7-sync`、`needs-human`；需要 Actions 允许创建 PR（Settings → Actions → Workflow permissions）。

## 人工接手冲突的标准动作

```powershell
git fetch origin; git checkout sync/win7-main-YYYYMMDD
# 解决冲突：main 语义为底，win7 增量嫁接（B3 经验）；B 类先看 backend/compat/win7 能否兜住
python scripts/py38_compat_rewrite.py backend packages/sage-core
python scripts/check_py38_compat.py
cd backend; pytest -n 4 -p no:cacheprovider tests/<受影响域>
git commit; git push
```

## 归档预案（EOL 2027-12-13）

禁用 `win7-sync.yml` 的 schedule，`release/win7` 打最终 `v*-win7` tag 后转为只读；
`backend/compat/win7`、`scripts/win7`、`docs/win7-sync` 随分支一起归档，main 不需要清理任何东西
（main 从未依赖这些路径）。

平台层：`backend/compat/win7/pydantic_compat.py` + `win_compat.py`
