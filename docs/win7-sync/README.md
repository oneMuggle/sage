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

# 5. 本地复现 CI backend-py38（真 Python 3.8）：见下方「py38 运行时门禁」
```

## py38 运行时门禁（`check_py38_compat.py` 第二层）

CI `backend-py38` 在 **真实 Python 3.8** 上跑 `backend/tests`，所以光管住 PEP 604/585 注解不够——
以下 API 在 3.11 上 `ast.parse` 正常、在 3.8 上直接炸（首轮 PR #850 CI 暴露了 82 例失败 + 1 例
xdist worker 崩溃，全部属于这些类别）。`check_py38_compat.py` 现在对 **backend + packages/sage-core
含 tests** 做正则守门；`py38_compat_rewrite.py` 自动改写其中的 `with (` 形态：

| 3.9+/3.10+/3.11+ API | 3.8 表现 | 替代 |
|---|---|---|
| `asyncio.to_thread` (3.9) | `AttributeError` —— 68 例 | `backend/compat/win7/asyncio_compat.py` 在 `backend/__init__` 注入（源码保持 main 原样） |
| `with (a as x, b as y):` (PEP 617) | **SyntaxError，整个测试模块无法 collect** | `py38_compat_rewrite.py` → 嵌套 `with`；ruff 关闭 SIM117 |
| `str.removesuffix/removeprefix` (3.9) | `AttributeError` | `endswith` + 切片 |
| `Path.is_relative_to` (3.9) / `Path.hardlink_to` (3.10) | `AttributeError` | `backend.office.path_safety.is_within` / `os.link` |
| 非交互 `sys.stderr` 全缓冲（3.9 起才行缓冲） | 子进程被 kill 前 `print` 输出丢失 | `execute_code_tool` bootstrap：`reconfigure(line_buffering=True)` + done 前 flush |
| `Path.write_text(newline=)` / `Path.stat(follow_symlinks=)` (3.10) | `TypeError` | `path.open(newline="")` / `os.lstat` |
| `isinstance(x, A \| B)` (3.10) | `TypeError: unsupported operand` | tuple |
| `except TimeoutError` 包 `asyncio.wait_for` (3.11 起才是同一个类) | 超时**不被捕获** | `except (TimeoutError, asyncio.TimeoutError)` (`# noqa: UP041`) |
| `datetime.UTC` (3.11) | `ImportError` | `timezone.utc` (`# noqa: UP017`) |
| `asyncio.Queue()` 在运行中的 loop 之外构造 (3.8/3.9 绑定 `get_event_loop()`) | worker 拿到别的 loop 的 Future | 惰性创建（`memory/async_extractor.py`） |

刻意保留、且已用 `try/except` 兜底的调用点，在同一行加注释 `py38: guarded` 即可跳过。

本地复现（Windows，conda）：
```powershell
conda create -n sage-backend-py38 python=3.8 -y
# py3.8 conda 自带 OpenSSL 在代理环境下 pip 可能 TLS 握手失败 —— 用 3.11 的 pip 代下 wheel：
python -m pip download -d wheels38 --python-version 3.8 --platform win_amd64 --implementation cp --abi cp38 --only-binary=:all: -r backend/requirements-py38.txt   # 剔除 jieba/hnswlib（无 wheel）
conda run -n sage-backend-py38 pip install --no-index --find-links wheels38 -r backend/requirements-py38.txt
conda run -n sage-backend-py38 pip install -r backend/requirements-dev.txt    # 与 CI 一致：会把 pydantic 升到 2.5.0
cd backend; conda run -n sage-backend-py38 pytest -n 4 --dist loadfile --ignore=tests/integration/test_event_loop_blocking.py
```

## 脚本一览（`scripts/win7/`）

| 脚本 | 作用 | CI 里谁在用 |
|------|------|-------------|
| `classify_diff.py` | 把异动文件分 A/B/C/D 四类；**D 类 = 发布/打包冻结件**，`auto_sync` 冲突时自动取 win7 侧 | `parity_report` / `auto_sync` 内部 import |
| `parity_report.py` | 生成 `parity-auto.md`：残差分级 typing-only / frozen / intentional / win7-only / main-only / real；`--fail-on` 守门；`--write-allow` 登记 | `win7-sync.yml` → job `parity` |
| `auto_sync.py` | `git merge --no-ff origin/main` → D 类 ours → `py38_compat_rewrite`（注解 + `with (` 改写）→ ruff --fix → `check_py38_compat`（注解 + 运行时 API 两层）→ `ruff check backend/` → 提交；冲突时输出分类报告 exit 2 | `win7-sync.yml` → job `sync` |
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
