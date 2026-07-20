# Win7 Python 3.8 注解兼容与 CI 锁定 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除 `release/win7` 的 5 个已证实 Python 3.8 注解 blocker，并让 backend-py38 CI 真正使用锁定依赖和 hex mode。

**Architecture:** 用 `typing.Optional` 替换仅有的 5 个运行时 blocker，不扩展成全仓注解重写；在 CI 边界删除会覆盖 py38 lock 的二次依赖安装，增加精确版本断言，并显式传入 `API_MODE=hex`。本地使用独立 conda Python 3.8 环境执行真实 import、定向集成测试和全量 coverage。

**Tech Stack:** Python 3.8、FastAPI 0.85.0、Pydantic 1.10.13、pytest 7.4.4、Ruff 0.4.4、GitHub Actions、conda

## Global Constraints

- 仅修改 `release/win7`；不得修改 main 或 `backend/requirements.txt`。
- Python 测试和依赖安装只能使用 conda 环境 `sage-backend-py38`（Python 3.8）。
- 不把 PR #189 的 commit 混入本分支。
- 源码范围限于 5 个已证实 blocker；不清扫其余 postponed annotations。
- API 行为、响应结构和业务逻辑必须保持不变。
- backend-py38 必须锁定 FastAPI `0.85.0`、Pydantic `1.10.13`。
- backend-py38 必须显式运行 `API_MODE=hex`，coverage 门禁保持 `>=80%`。
- 每完成一个步骤，就将本计划对应 checkbox 改为 `[x]`。
- 合并顺序：F1 PR 先合；随后更新并合 PR #189；最终 `release/win7` push 必须全绿。

---

## File Map

| File | Responsibility | Planned change |
| --- | --- | --- |
| `backend/api/hex_routes.py` | FastAPI hex endpoints | 1 个返回注解改为 `Optional[dict]` |
| `backend/wiki/graph.py` | Wiki graph 构建与 wikilink 解析 | 1 个返回注解改为 `Optional[GraphNode]` |
| `backend/orchestration/router.py` | Agent 路由选择 | 3 个返回注解改为 `Optional[Agent]` |
| `backend/wiki/llm_context.py` | Wiki LLM context 流式调用 | 第 72 行 parenthesised `async with (a, b):` 拆为 `async with a, b:` |
| `backend/requirements-py38.txt` | Win7 py38 锁定依赖 | 新增 `python-multipart==0.0.9` 与 main 对齐 |
| `.github/workflows/ci.yml` | Win7 py38 CI | 删除覆盖 lock 的安装；增加版本断言；显式 hex mode |
| `docs/superpowers/specs/2026-07-19-win7-py38-eager-annotations-design.md` | 已批准设计与最终状态 | 修正合并顺序；扩展范围；完成后更新状态 |
| `docs/plans/2026-07-19_win7-py38-eager-annotations.md` | 进行中实施记录 | 执行时更新 checkbox；功能完成后删除 |

---

### Task 1: 创建 Python 3.8 环境并捕获 RED

**Files:**
- Read: `backend/requirements-py38.txt`
- Read: `backend/main.py`
- No repository file changes

**Interfaces:**
- Consumes: conda 环境管理器、`backend/requirements-py38.txt`
- Produces: 可重复使用的 `sage-backend-py38` 环境和运行时 RED 证据

- [ ] **Step 1: 确认分支和环境前置状态**

```bash
git status --short --branch
conda env list
```

Expected: 当前分支为 `fix/win7-py38-eager-annotations`；若环境已存在，`conda run -n sage-backend-py38 python --version` 必须输出 Python 3.8.x。

- [ ] **Step 2: 创建专用 conda 环境**

```bash
conda create -n sage-backend-py38 python=3.8 -y
conda run -n sage-backend-py38 python --version
```

Expected: `Python 3.8.x`。失败时停止；不得改用 base、系统 Python 或 `sage-backend`。

- [ ] **Step 3: 安装 Win7 锁定依赖**

```bash
conda run -n sage-backend-py38 pip install -r backend/requirements-py38.txt
```

Expected: exit 0。不得安装 `backend/requirements-dev.txt`。

- [ ] **Step 4: 验证锁定版本**

```bash
conda run -n sage-backend-py38 python -c "import fastapi, pydantic; print(fastapi.__version__, pydantic.VERSION); assert fastapi.__version__ == '0.85.0'; assert pydantic.VERSION == '1.10.13'"
```

Expected: `0.85.0 1.10.13`。

- [ ] **Step 5: 运行真实 import 并确认 RED**

```bash
conda run -n sage-backend-py38 python -c "from backend.main import app"
```

Expected: non-zero，`TypeError: unsupported operand type(s) for |`，优先锚定 `backend/wiki/graph.py:289`。若失败类型或路径不同，停止并回到根因调查。

---

### Task 2: 替换 5 个运行时注解 blocker

**Files:**
- Modify: `backend/api/hex_routes.py:220`
- Modify: `backend/wiki/graph.py:289`
- Modify: `backend/orchestration/router.py:134,142,170`
- Test: existing import gate `backend/tests/conftest.py:19`

**Interfaces:**
- Consumes: 已存在的 `typing.Optional` imports
- Produces: `get_settings() -> Optional[dict]`、`_resolve_wikilink(...) -> Optional[GraphNode]`、3 个 `_select_*` 方法返回 `Optional[Agent]`

- [x] **Step 1: 复核 RED 对应源码仍未变化**

```bash
grep -nE 'dict \| None|GraphNode \| None|Agent \| None' \
  backend/api/hex_routes.py backend/wiki/graph.py backend/orchestration/router.py
```

Expected: 恰好 5 个目标命中；否则停止并重新评估范围。

- [x] **Step 2: 修改 FastAPI endpoint 返回注解**

```python
@router.get("/settings")
async def get_settings() -> Optional[dict]:
```

不修改 decorator、docstring 或函数体。

- [x] **Step 3: 修改 wiki graph 返回注解**

```python
def _resolve_wikilink(wikilink: str, node_map: Dict[str, GraphNode]) -> Optional[GraphNode]:
```

不修改函数逻辑。

- [x] **Step 4: 修改 orchestration Router 的 3 个返回注解**

```python
def _select_round_robin(self, agents: List[Agent]) -> Optional[Agent]:
```

```python
def _select_by_capability(self, task: Task, agents: List[Agent]) -> Optional[Agent]:
```

```python
def _select_by_load(self, agents: List[Agent]) -> Optional[Agent]:
```

只允许格式化工具调整换行；不得改函数体。

- [x] **Step 4a: 拆解 `llm_context.py:72` 的 parenthesised `async with`**

原代码（Python 3.10+ 语法）：

```python
async with (
    httpx.AsyncClient(timeout=timeout_seconds) as client,
    client.stream(
        "POST",
        chat_url,
        headers=auth_headers,
        json={
            "model": llm_model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        },
    ) as r,
):
```

改为 Python 3.8 兼容的多上下文写法（顺序保持不变）：

```python
async with httpx.AsyncClient(timeout=timeout_seconds) as client, client.stream(
    "POST",
    chat_url,
    headers=auth_headers,
    json={
        "model": llm_model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    },
) as r:
```

仅修改 1 行 `async with` 头；不改动函数体、错误处理或 yield 逻辑。Ruff/black 必须能接受该换行。

- [ ] **Step 5: 验证 import GREEN**  _(BLOCKED — 详见 task-2-report.md；out-of-scope `collections.abc.Callable` 在 Python 3.8 不可下标，已超出本任务 scope)_

```bash
conda run -n sage-backend-py38 python -c "from backend.main import app; print(type(app).__name__)"
```

Expected: `FastAPI`。

- [x] **Step 6: 验证 endpoint 注解可被求值**

```bash
conda run -n sage-backend-py38 python -c "from typing import get_type_hints; from backend.api.hex_routes import get_settings; print(get_type_hints(get_settings)['return'])"
```

Expected: exit 0，输出 `typing.Optional[dict]` 或等价 union。

- [x] **Step 7: 提交源码修复**

```bash
git add \
  backend/api/hex_routes.py \
  backend/wiki/graph.py \
  backend/orchestration/router.py \
  backend/wiki/llm_context.py \
  docs/plans/2026-07-19_win7-py38-eager-annotations.md
git commit -m "fix(win7): replace remaining eager py38 annotations"
```

---

### Task 3: 修正 backend-py38 CI 环境

**Files:**
- Modify: `.github/workflows/ci.yml:42-56`
- Test: workflow static assertions and YAML parse

**Interfaces:**
- Consumes: `backend/requirements-py38.txt`（已包含 runtime、testing、quality dependencies）
- Produces: fail-fast 版本门禁和真实 `API_MODE=hex` pytest 命令

- [ ] **Step 1: 捕获 CI 配置 RED**

```bash
if grep -q 'pip install -r backend/requirements-dev.txt' .github/workflows/ci.yml; then
  echo 'RED: py38 lock is overwritten by requirements-dev.txt'
  exit 1
fi
```

Expected: exit 1，并输出 RED 消息。

- [ ] **Step 2: 删除覆盖 lock 的二次安装并增加版本断言**

目标 block：

```yaml
      - name: Install backend deps (py38, locked)
        shell: bash -el {0}
        run: |
          conda run -n sage-backend-py38 pip install -r backend/requirements-py38.txt
          conda run -n sage-backend-py38 python -c "import fastapi, pydantic; assert fastapi.__version__ == '0.85.0', fastapi.__version__; assert pydantic.VERSION == '1.10.13', pydantic.VERSION"
```

- [ ] **Step 3: 让 Pytest job 名称与实际 mode 一致**

目标命令：

```yaml
          conda run -n sage-backend-py38 bash -c "cd backend && API_MODE=hex pytest --cov --cov-report=xml --cov-report=term --cov-fail-under=80"
```

- [ ] **Step 4: 验证 desired config GREEN**

```bash
if grep -q 'pip install -r backend/requirements-dev.txt' .github/workflows/ci.yml; then exit 1; fi
grep -F "fastapi.__version__ == '0.85.0'" .github/workflows/ci.yml
grep -F "pydantic.VERSION == '1.10.13'" .github/workflows/ci.yml
grep -F 'API_MODE=hex pytest --cov' .github/workflows/ci.yml
```

Expected: exit 0，三个 guard 均输出对应行。

- [ ] **Step 5: 解析 workflow YAML**

```bash
node -e "const fs=require('fs'); const yaml=require('js-yaml'); yaml.load(fs.readFileSync('.github/workflows/ci.yml','utf8')); console.log('workflow YAML parsed')"
```

Expected: `workflow YAML parsed`。

- [ ] **Step 6: 运行与 CI 相同的版本断言**

```bash
conda run -n sage-backend-py38 python -c "import fastapi, pydantic; assert fastapi.__version__ == '0.85.0', fastapi.__version__; assert pydantic.VERSION == '1.10.13', pydantic.VERSION"
```

Expected: exit 0。

- [ ] **Step 7: 提交 CI 修复**

```bash
git add .github/workflows/ci.yml docs/plans/2026-07-19_win7-py38-eager-annotations.md
git commit -m "fix(ci): keep win7 backend dependencies locked"
```

---

### Task 4: 执行 Python 3.8 回归验证

**Files:**
- Test: `backend/tests/integration/test_settings_endpoint.py`
- Test: `backend/tests/integration/test_hex_routes_chat.py`
- Test: `backend/tests/integration/test_routes_sessions_hex.py`
- Verify: all `backend/tests/`

**Interfaces:**
- Consumes: Task 2 的兼容注解和 Task 3 的锁定环境
- Produces: 定向行为、lint、全量 coverage 的 fresh evidence

- [ ] **Step 1: 运行定向 hex integration tests**

```bash
conda run -n sage-backend-py38 bash -c "cd backend && API_MODE=hex pytest -q tests/integration/test_settings_endpoint.py tests/integration/test_hex_routes_chat.py tests/integration/test_routes_sessions_hex.py"
```

Expected: exit 0，0 failed；settings tests 不得因 mode 被 skip。

- [ ] **Step 2: 运行 Ruff**

```bash
conda run -n sage-backend-py38 ruff check backend/
```

Expected: exit 0。

- [ ] **Step 3: 运行完整 backend py38 coverage**

```bash
conda run -n sage-backend-py38 bash -c "cd backend && API_MODE=hex pytest --cov --cov-report=xml --cov-report=term --cov-fail-under=80"
```

Expected: exit 0，0 failed，coverage `>=80%`。

- [ ] **Step 4: 运行工作区静态核验**

```bash
git diff --check release/win7...HEAD
git status --short --branch
git log --oneline release/win7..HEAD
```

Expected: 无 whitespace errors；只有计划内文件；历史不包含 PR #189 的 `49a3ad6`。

---

### Task 5: 多维审查和修复

**Files:**
- Review: `.github/workflows/ci.yml`
- Review: `backend/api/hex_routes.py`
- Review: `backend/wiki/graph.py`
- Review: `backend/orchestration/router.py`
- Review: design spec and active plan

**Interfaces:**
- Consumes: 完整 diff 和 Task 4 fresh evidence
- Produces: 无 CRITICAL/HIGH findings 的审查结论

- [ ] **Step 1: 并行启动审查 agents**

1. `python-reviewer`：Python 3.8 typing、FastAPI/Pydantic annotation behavior。
2. `security-reviewer`：CI dependency trust、覆盖风险和 workflow 安全性。
3. `code-reviewer`：完整 diff、项目规则、最小范围和历史一致性。
4. `pr-test-analyzer`：import gate、定向测试和 coverage 的防回归能力。

Expected: 每个 agent 返回 findings 或明确“无问题”。

- [ ] **Step 2: 处理审查结果**

- CRITICAL/HIGH：必须修复并重新执行 Task 4。
- MEDIUM：若在批准范围内则修复，否则记录 follow-up。
- LOW：仅记录，不做 unrelated cleanup。

- [ ] **Step 3: 提交审查修复（仅当有实际改动）**

```bash
git add \
  .github/workflows/ci.yml \
  backend/api/hex_routes.py \
  backend/wiki/graph.py \
  backend/orchestration/router.py \
  docs/superpowers/specs/2026-07-19-win7-py38-eager-annotations-design.md \
  docs/plans/2026-07-19_win7-py38-eager-annotations.md
git commit -m "fix(win7): address py38 compatibility review"
```

无改动时不创建空 commit。

---

### Task 6: 创建 F1 PR 并验证 required checks

**Files:**
- Update: `docs/superpowers/specs/2026-07-19-win7-py38-eager-annotations-design.md`
- Keep during PR: `docs/plans/2026-07-19_win7-py38-eager-annotations.md`

**Interfaces:**
- Consumes: Task 4 verification 和 Task 5 review verdicts
- Produces: 独立 F1 PR 和 required checks 结果

- [ ] **Step 1: 更新 spec 状态**

设为：

```markdown
- **Status:** Implemented locally，pending PR CI
```

更新 spec milestones M1-M5 为 `[x]`，M6 保持 `[ ]`。

- [ ] **Step 2: 提交文档状态**

```bash
git add docs/superpowers/specs/2026-07-19-win7-py38-eager-annotations-design.md docs/plans/2026-07-19_win7-py38-eager-annotations.md
git commit -m "docs: record win7 py38 compatibility verification"
```

- [ ] **Step 3: 推送独立分支**

```bash
git push -u origin fix/win7-py38-eager-annotations
```

若已知 lefthook upstream-detection bug 再以 exit 141 中断，先确认测试证据，再按既有 workaround：

```bash
LEFTHOOK=0 git push -u origin fix/win7-py38-eager-annotations
```

必须如实记录是否绕过 hook。

- [ ] **Step 4: 创建 PR**

```bash
PR_BODY=$(mktemp)
trap 'rm -f "$PR_BODY"' EXIT
cat >"$PR_BODY" <<'EOF'
## Summary

- replace five runtime-evaluated PEP 604 annotations with Python 3.8-compatible `Optional[...]`
- keep the backend-py38 environment on FastAPI 0.85.0 and Pydantic 1.10.13
- run the Win7 backend test job explicitly with `API_MODE=hex`

## Root cause

Run `29680290505` showed FastAPI/Pydantic evaluating `dict | None` on Python 3.8. The py38 CI job also installed `requirements-dev.txt`, which recursively installed the main `requirements.txt` and silently replaced the Win7 dependency pins.

## Test plan

- [x] Python 3.8 `backend.main` import
- [x] exact FastAPI/Pydantic version assertions
- [x] targeted hex integration tests
- [x] Ruff
- [x] full backend pytest coverage >=80%
- [x] workflow YAML parse and diff checks
- [x] Python, security, general, and test-coverage reviews

## Merge order

Merge this F1 PR first. Then update and merge PR #189. The intermediate `release/win7` push may still fail only at the old Pester action; the final push after #189 must be fully green.
EOF

gh pr create \
  --base release/win7 \
  --head fix/win7-py38-eager-annotations \
  --title "fix(win7): restore Python 3.8 backend compatibility" \
  --body-file "$PR_BODY"
```

PR body 必须包含：run `29680290505` 根因、5 个 blocker、requirements-dev 覆盖、py38 RED/GREEN、F1 优先合并顺序、Pester 在 PR refs skip。临时 body 文件不得提交。

- [ ] **Step 5: 监控 PR CI**

```bash
F1_PR=$(gh pr list \
  --state open \
  --head fix/win7-py38-eager-annotations \
  --json number \
  --jq '.[0].number')
test -n "$F1_PR"
gh pr checks "$F1_PR" --watch --interval 10
```

Expected: backend-py38、Frontend、Electron builds、Electron smoke、All Checks success；Pester 因现有条件 skip。required check 失败时立即停止并读取 failed logs。

- [ ] **Step 6: 请求用户人工合并 F1 PR**

不自动 merge；报告 PR URL、commits、测试、review 与中间红灯预期。

---

### Task 7: 合并后收官顺序

**Files:**
- Delete after final verification: `docs/plans/2026-07-19_win7-py38-eager-annotations.md`
- Update: design spec and `docs/technical/21-win7-lts.md`

**Interfaces:**
- Consumes: F1 merge、PR #189 状态、两个 release/win7 push runs
- Produces: 最终全绿 release/win7 和已归档文档

- [ ] **Step 1: 验证 F1 merge 后的中间 push**

Expected: backend-py38 success；Pester 因旧 action failure。若 backend-py38 失败，F1 不合格，立即停止。

- [ ] **Step 2: 更新 PR #189 到新的 base**

优先 rebase + `--force-with-lease`；执行前确认用户授权。不得 merge feature branches，只纳入新 base 历史。

- [ ] **Step 3: 监控并请求用户合并 PR #189**

PR #189 required checks 必须全绿；用户人工合并后监控最终 push。

- [ ] **Step 4: 最终 release/win7 验证**

Expected: backend-py38、Pester、Frontend、Electron builds、Electron smoke、All Checks 全部 success。

- [ ] **Step 5: 归档实施文档**

1. design spec 状态改为 `Implemented and verified`，记录 F1 PR、PR #189 和最终 run URL。
2. 长期结论并入 `docs/technical/21-win7-lts.md`。
3. 删除本计划，因为 `docs/plans/` 仅保留进行中计划。
4. 提交文档归档。

---

## Final Verification Checklist

- [ ] 本地解释器为 Python 3.8.x，不是 base/system/Python 3.10。
- [ ] FastAPI `0.85.0`、Pydantic `1.10.13` 断言通过。
- [ ] `from backend.main import app` 成功。
- [ ] 5 个目标注解全部使用 `Optional[...]`。
- [ ] CI 不再安装 `backend/requirements-dev.txt` 到 py38 env。
- [ ] CI Pytest 命令包含 `API_MODE=hex`。
- [ ] 定向 hex tests、Ruff、全量 coverage `>=80%` 通过。
- [ ] Python/security/general/test coverage reviews 无 CRITICAL/HIGH。
- [ ] F1 PR required checks 全绿并由用户人工合并。
- [ ] PR #189 更新后 required checks 全绿并由用户人工合并。
- [ ] 最终 `release/win7` push 全绿。
- [ ] 完成后删除本计划并更新 technical/spec 文档。
