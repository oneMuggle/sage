# Win7 Python 3.8 注解兼容与 CI 锁定 — Design Spec

- **Date:** 2026-07-19
- **Branch:** `fix/win7-py38-eager-annotations`（基于 `release/win7`）
- **Status:** Implemented（PR #190 + PR #189 merged to release/win7 @ 4bbe7a7 / 172c7d1, Backend Python 3.8 CI 全绿，coverage ~87%）
- **Author:** Claude（与用户共同设计）

## 1. 背景与目标

### 1.1 问题

`release/win7` 的 CI run `29680290505` 在导入 FastAPI 应用时失败：

```text
backend/api/hex_routes.py:220
async def get_settings() -> dict | None:

TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'
```

`hex_routes.py` 虽然启用了 `from __future__ import annotations`，FastAPI/Pydantic 仍会在注册路由时调用 `evaluate_forwardref()`，在 Python 3.8 中重新求值字符串 `dict | None` 并失败。

全量审计 83 个 FastAPI endpoint 与 20 个 dependency callable 后，确认当前 FastAPI eager-eval 风险点只有这一处。但修复该行后，Python 3.8 还会在普通模块导入时遇到 4 个不带 future annotations 的 PEP 604 注解：

- `backend/wiki/graph.py`：1 个 `GraphNode | None`
- `backend/orchestration/router.py`：3 个 `Agent | None`

CI 还有独立的环境真实性问题：`requirements-py38.txt` 先锁定 FastAPI 0.85.0 / Pydantic 1.10.13，随后 `requirements-dev.txt` 通过 `-r requirements.txt` 又将其覆盖为 FastAPI 0.109.0 / Pydantic 2.5.0。job 名称声称运行 hex mode，但 Pytest 命令没有设置 `API_MODE=hex`。

### 1.2 目标

1. 消除 5 个已证实的 Python 3.8 import/eager-eval blocker。
2. 确保 backend-py38 job 实际使用 Win7 锁定依赖。
3. 确保 backend-py38 job 显式运行 hex mode。
4. 使用真实 Python 3.8 解释器执行 RED/GREEN 回归验证。
5. 保持 API 行为、响应结构和业务逻辑不变。

### 1.3 非目标

- 不清扫带 future annotations、当前不会被运行时反射的剩余 PEP 604/585 注解。
- 不修复或重构 `scripts/py38_compat_rewrite.py`。
- 不升级 Win7 的 Python、FastAPI、Pydantic 或其他生产依赖。
- 不把 PR #189 的 Pester action 修复混入本分支。
- 不修改 main 分支或 `backend/requirements.txt`。

## 2. 根因与范围

### 2.1 FastAPI eager-eval

调用链：

```text
backend/tests/conftest.py
  -> backend.main
  -> backend.api.hex_routes
  -> APIRoute.__init__
  -> get_typed_return_annotation
  -> evaluate_forwardref
  -> eval("dict | None")
  -> TypeError on Python 3.8
```

`Optional[dict]` 能在 Python 3.8 中由 `typing` 正确解析，且 `hex_routes.py` 已导入 `Optional`。

### 2.2 普通 Python 3.8 import blocker

没有 future annotations 时，Python 3.8 会在函数定义阶段直接计算 `GraphNode | None` / `Agent | None`，无需 FastAPI/Pydantic 介入。两个模块均已导入 `Optional`，因此只需替换注解。

### 2.3 CI 锁定依赖被覆盖

当前安装顺序：

```text
requirements-py38.txt
  -> fastapi==0.85.0, pydantic==1.10.13, pytest/ruff/mypy/...
requirements-dev.txt
  -> requirements.txt
  -> fastapi==0.109.0, pydantic==2.5.0
```

`requirements-py38.txt` 已包含全部测试和质量工具，第二次安装既冗余又破坏锁定。设计采用删除第二次安装并增加版本断言，而不是新增一份重复的 py38 dev requirements。

## 3. 技术设计

### 3.1 源码修改

| 文件 | 当前注解 | 目标注解 | 数量 |
| --- | --- | --- | ---: |
| `backend/api/hex_routes.py` | `dict \| None` | `Optional[dict]` | 1 |
| `backend/wiki/graph.py` | `GraphNode \| None` | `Optional[GraphNode]` | 1 |
| `backend/orchestration/router.py` | `Agent \| None` | `Optional[Agent]` | 3 |

所有目标文件已导入 `Optional`，不新增 import，不修改函数实现。

### 3.2 CI 修改

`backend-py38` job：

1. 只安装 `backend/requirements-py38.txt`。
2. 安装后立即断言：
   - `fastapi.__version__ == "0.85.0"`
   - `pydantic.VERSION == "1.10.13"`
3. Pytest 命令显式设置 `API_MODE=hex`。
4. 保留 Ruff、coverage ≥80%、Codecov 上传等现有门禁。

版本断言是 fail-fast guard：依赖被覆盖时，在测试收集前给出明确错误。

### 3.3 分支与合并顺序

- F1 分支：`fix/win7-py38-eager-annotations`
- Base：`release/win7`
- PR #189 保持独立。
- 推荐先合并 PR #189，再合并 F1 PR；否则 F1 合并后的 `release/win7` push CI 仍会被旧 Pester action 阻塞。

## 4. RED/GREEN 验证

### 4.1 本地环境

按项目约定创建：

```bash
conda create -n sage-backend-py38 python=3.8 -y
conda run -n sage-backend-py38 pip install -r backend/requirements-py38.txt
```

不得使用 base、系统 Python 或 Python 3.10 的 `sage-backend` 环境。

### 4.2 RED

在修改源码前运行：

```bash
conda run -n sage-backend-py38 python -c "from backend.main import app"
```

预期在现有 PEP 604 blocker 处失败。远程 run `29680290505` 作为 FastAPI eager-eval 的既有 RED 证据。

### 4.3 GREEN

按顺序执行：

1. 锁定版本断言。
2. `from backend.main import app` 导入成功。
3. `API_MODE=hex` 定向运行：
   - `tests/integration/test_settings_endpoint.py`
   - `tests/integration/test_hex_routes_chat.py`
   - `tests/integration/test_routes_sessions_hex.py`
4. Ruff：`ruff check backend/`。
5. backend 全量 pytest + coverage ≥80%。
6. workflow YAML 解析、`git diff --check`。
7. Python reviewer、security reviewer、general code reviewer。
8. PR CI 全部通过。

现有 `backend/tests/conftest.py` 已将 `backend.main` import 作为所有 pytest 的 collection gate；`test_settings_endpoint.py` 已覆盖 `/settings` 的 null 与持久化响应。本修复不新增重复测试文件。

## 5. 实施里程碑

- [x] M1：创建 `sage-backend-py38`，安装锁定依赖并捕获 RED。
- [x] M2：替换 5 个注解，完成 import GREEN。
- [x] M3：修正 backend-py38 CI 的依赖安装、版本断言和 hex mode。
- [x] M4：运行定向测试、Ruff、全量 coverage。
- [x] M5：完成多维代码审查并修复高优先级问题。
- [x] M6：提交、推送、创建独立 PR，监控 CI。

## 6. 风险与依赖

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 修复后出现新的 py38 import blocker | CI 继续红 | 只增加运行时证实的最小修复；三次后停止并重新评估全仓清扫 |
| PyPI/conda 中 Python 3.8 包不可安装 | 本地 RED/GREEN 被阻塞 | 记录具体包与错误，优先使用项目锁定版本；不污染其他环境 |
| CI 依赖再次被间接覆盖 | job 名实不符 | 安装后执行 FastAPI/Pydantic 精确版本断言 |
| PR #189 未先合并 | release/win7 push 仍因 Pester action 红 | 明确合并顺序，F1 PR 描述中标注依赖 |
| `API_MODE=hex` 暴露真实的历史测试失败 | F1 PR CI 红 | 按 STOP-at-failure 原则调查，不以取消 hex mode 掩盖问题 |

## 7. 验收标准

- 5 个目标注解均为 Python 3.8 可解析的 `Optional[...]`。
- backend-py38 环境保留 FastAPI 0.85.0 / Pydantic 1.10.13。
- `backend.main` 在 Python 3.8 中可导入。
- `/settings`、hex chat、hex sessions 定向测试通过。
- py38 全量 backend pytest coverage ≥80%。
- PR CI 全绿；若受 PR #189 合并顺序影响，需明确区分 Pester 与 F1 结果。
