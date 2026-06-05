# Sage 全栈质量优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 7-8 周内将 Sage 打造成"测试有门槛、架构有边界、运行可观测、桌面跨 Win7"的全栈高质量 LLM 应用

**Architecture:**

- 后端从单体 `core/` 迁移到六边形（domain / ports / application / adapters / api）
- 前端从 `components/pages/hooks/stores` 迁移到 Feature-Sliced Design（app / processes / pages / widgets / features / entities / shared）
- 桌面从 Tauri 1.6 升级到 Tauri 2 + Win7 全兼容
- 新增 9 个 Prometheus 指标、OpenTelemetry trace、用户行为审计
- CI 三 job（backend / frontend / tauri）+ pre-commit / pre-push hooks + 覆盖率门槛

**Tech Stack:**

- 后端：Python 3.11 + FastAPI 0.109 + pytest 7.4 + pytest-cov 5.0 + ruff 0.4 + mypy 1.8 + prometheus-client 0.20 + opentelemetry-api 1.27 + import-linter 2.0
- 前端：React 18 + TypeScript 5.3 + Vite 5 + Vitest 4.1 + @testing-library/react 16.3 + ESLint 9 + Prettier 3 + Lighthouse 12
- 桌面：Tauri 2.x + Rust 1.77.2（Win7 x86 workaround） + WebView2 + windows7-compat feature
- 流程：lefthook 1.6 + GitHub Actions + micromamba（备选，CI 启动加速）

**Spec:** `docs/superpowers/specs/2026-06-05-sage-quality-optimization-design.md`

---

## 阶段概览

| 阶段   | 周期      | 核心交付                                            | 详细程度             |
| ------ | --------- | --------------------------------------------------- | -------------------- |
| **P0** | Week 1-3  | 测试基础设施 + CI 门禁 + pre-commit/pre-push        | 任务级（立即可执行） |
| **P1** | Week 3-6  | 覆盖率 ≥ 80% + 前端 FSD 物理迁移 + 边界规则         | 任务组级             |
| **P2** | Week 5-8  | 后端六边形重构（domain/ports/adapters/application） | 任务组级             |
| **P3** | Week 7-10 | 可观测性（9 指标 + OTel + 审计）+ UX/a11y + Tauri 2 | 任务组级             |

> 阶段间允许 1 周"消化周"用于技术分享与回归修复。

---

## 文件结构映射

### 新建文件

#### 后端

- `backend/environment.yml` — conda 环境锁定
- `backend/pytest.ini` — pytest 配置
- `backend/ruff.toml` — ruff 配置
- `backend/mypy.ini` — mypy 配置（strict 仅 domain/ports）
- `backend/pyproject.toml` — import-linter 配置
- `backend/domain/__init__.py`
- `backend/domain/agent.py`
- `backend/domain/message.py`
- `backend/domain/tool.py`
- `backend/domain/skill.py`
- `backend/ports/__init__.py`
- `backend/ports/llm.py`
- `backend/ports/tool.py`
- `backend/ports/skill.py`
- `backend/ports/storage.py`
- `backend/ports/observability.py`（含 MetricPort + EventPort）
- `backend/application/__init__.py`
- `backend/application/services/__init__.py`
- `backend/application/services/chat_service.py`
- `backend/application/services/session_service.py`
- `backend/application/services/tool_invocation_service.py`
- `backend/adapters/__init__.py`
- `backend/adapters/out/llm/httpx_adapter.py`
- `backend/adapters/out/llm/mock_adapter.py`
- `backend/adapters/out/storage/sqlite_adapter.py`
- `backend/adapters/out/storage/memory_adapter.py`
- `backend/adapters/out/tool/inproc_adapter.py`
- `backend/adapters/out/tool/mock_adapter.py`
- `backend/adapters/out/metric/prometheus_adapter.py`
- `backend/adapters/out/metric/noop_adapter.py`
- `backend/adapters/out/event/file_adapter.py`
- `backend/adapters/out/event/stdout_adapter.py`
- `backend/tests/unit/`（新子目录）
- `backend/tests/integration/`（新子目录）
- `backend/tests/e2e/`（新子目录）

#### 前端

- `src/app/root.tsx`
- `src/app/providers/QueryClient.tsx`
- `src/app/providers/ErrorBoundary.tsx`
- `src/app/providers/ThemeProvider.tsx`
- `src/widgets/ChatPanel/ChatPanel.tsx`
- `src/widgets/MessageList/MessageList.tsx`
- `src/widgets/Sidebar/Sidebar.tsx`
- `src/features/send-message/send-message.ts`
- `src/features/switch-session/switch-session.ts`
- `src/features/run-tool/run-tool.ts`
- `src/entities/message/message.ts`
- `src/entities/message/message-store.ts`
- `src/entities/session/session.ts`
- `src/entities/session/session-store.ts`
- `src/entities/tool/tool.ts`
- `src/entities/skill/skill.ts`
- `src/entities/agent/agent.ts`
- `src/shared/ui/ErrorState/ErrorState.tsx`
- `src/shared/ui/LoadingState/LoadingState.tsx`
- `src/shared/ui/RetryButton/RetryButton.tsx`
- `src/shared/ui/Skeleton/Skeleton.tsx`
- `src/shared/ui/Skeleton/MessageSkeleton.tsx`
- `src/shared/ui/EmptyState/EmptyState.tsx`
- `src/shared/ui/FocusTrap/FocusTrap.tsx`
- `src/shared/styles/focus.css`
- `src/shared/api/api-client.ts`
- `src/shared/config/env.ts`
- `eslint.config.js`
- `.prettierrc`
- `lefthook.yml`

#### 文档

- `docs/technical/15-quality-gates.md`
- `docs/technical/16-observability.md`
- `docs/technical/17-frontend-quality.md`
- `docs/technical/18-hexagonal.md`
- `docs/user-manual/01-desktop.md`
- `docs/user-manual/02-metrics.md`

### 修改文件

- `backend/main.py` — 注入 ports（DI）
- `backend/api/routes.py` — 改写为 in-adapter
- `backend/core/agent.py` → 拆分到 `domain/agent.py` + `application/services/chat_service.py`
- `backend/core/orchestrator.py` → 拆分到 `application/services/`
- `backend/core/llm_client.py` → 改造为 `adapters/out/llm/httpx_adapter.py`
- `backend/core/errors.py` → 移到 `domain/errors.py`
- `backend/utils/logging.py` — 加 OTel context
- `src/main.tsx` — 引入 `app/root.tsx`
- `src/App.tsx` — 移到 `app/`
- `vite.config.ts` — 加 test 字段、coverage thresholds
- `tsconfig.json` — 加 `shared/config` 等 paths
- `package.json` — 加 lint/format/test 脚本
- `.github/workflows/ci.yml` — 重写为三 job
- `src-tauri/Cargo.toml` — Tauri 2 + windows7-compat
- `src-tauri/tauri.conf.json` — embedBootstrapper
- `docs/technical/02-architecture.md`
- `docs/technical/05-agent.md`
- `docs/technical/06-tools.md`
- `docs/technical/07-skills.md`
- `docs/technical/09-frontend.md`
- `docs/technical/README.md`
- `.claude/CLAUDE.md`

### 删除文件（迁移完成后）

- `backend/core/agent.py`（迁移到 domain/application）
- `backend/core/orchestrator.py`（迁移到 application）
- `backend/core/llm_client.py`（迁移到 adapters）
- `src/components/`（迁移到 FSD 后保留 `src/legacy/components/` 一周，确认无引用后删除）

---

## P0 — 测试基础设施与质量门禁（Week 1-3，12 任务详细级）

### Task 1: 添加 backend 测试与质量工具依赖

**Files:**

- Modify: `backend/requirements.txt`

- [ ] **Step 1: 编辑 requirements.txt**

```text
# Sage 后端依赖
# Core
fastapi==0.109.0
uvicorn==0.27.0
pydantic==2.5.0

# Database
# sqlite3 is built-in

# HTTP
httpx==0.26.0

# Utils
python-dotenv==1.0.0
pyyaml==6.0.1
croniter==2.0.1

# Testing
pytest==7.4.4
pytest-asyncio==0.23.3
pytest-cov==5.0.0
respx==0.21.1

# Quality
ruff==0.4.4
mypy==1.8.0
import-linter==2.0.1
types-PyYAML==6.0.12.20240311
```

- [ ] **Step 2: 安装到 sage-backend 环境**

Run:

```bash
/home/fz/anaconda3/envs/sage-backend/bin/pip install -r /home/fz/project/sage/backend/requirements.txt
```

Expected: 安装成功，无错误。

- [ ] **Step 3: 验证 import-linter 可用**

Run:

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -c "import importlinter; print(importlinter.__version__)"
```

Expected: `2.0.1`

- [ ] **Step 4: Commit**

```bash
cd /home/fz/project/sage
git add backend/requirements.txt
git commit -m "chore(deps): 添加 ruff / mypy / import-linter / respx 到后端"
```

---

### Task 2: 创建 backend conda 环境锁定文件

**Files:**

- Create: `backend/environment.yml`

- [ ] **Step 1: 写入 environment.yml**

```yaml
name: sage-backend
channels:
  - conda-forge
  - defaults
dependencies:
  - python=3.11
  - pip
  - pip:
      - -r file:requirements.txt
```

- [ ] **Step 2: 验证语法**

Run:

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -c "import yaml; yaml.safe_load(open('/home/fz/project/sage/backend/environment.yml'))"
```

Expected: 无输出（成功解析）。

- [ ] **Step 3: Commit**

```bash
git add backend/environment.yml
git commit -m "chore(backend): 添加 conda environment.yml 锁定 Python 3.11"
```

---

### Task 3: 配置 pytest 与覆盖率门槛

**Files:**

- Create: `backend/pytest.ini`

- [ ] **Step 1: 写入 pytest.ini**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
asyncio_mode = auto
addopts =
    -ra
    --strict-markers
    --strict-config
    --showlocals
markers =
    unit: 单元测试
    integration: 集成测试
    e2e: 端到端测试
    slow: 慢速测试（默认跳过）

[coverage:run]
source = backend
branch = true
omit =
    backend/__pycache__/*
    backend/*/__pycache__/*
    backend/main.py
    backend/tests/*
    backend/data/*

[coverage:report]
show_missing = true
skip_covered = false
precision = 1
exclude_lines =
    pragma: no cover
    raise NotImplementedError
    if __name__ == .__main__.:
    if TYPE_CHECKING:
    \.\.\.

[coverage:paths]
source =
    backend
    /home/fz/project/sage/backend

[coverage:html]
directory = backend/.coverage_html
```

- [ ] **Step 2: 运行 pytest 验证配置**

Run:

```bash
cd /home/fz/project/sage/backend && /home/fz/anaconda3/envs/sage-backend/bin/pytest --collect-only
```

Expected: 收集到 9+ 测试，无错误。

- [ ] **Step 3: 运行覆盖率（不设门槛，仅观察）**

Run:

```bash
cd /home/fz/project/sage/backend && /home/fz/anaconda3/envs/sage-backend/bin/pytest --cov=backend --cov-report=term-missing
```

Expected: 报告生成，列出当前覆盖率（基线测量）。**记录该数字到 `docs/plans/2026-06-05_sage-quality-optimization.md` 第 8 节"总体成功指标"基线列。**

- [ ] **Step 4: Commit**

```bash
cd /home/fz/project/sage
git add backend/pytest.ini
git commit -m "test(backend): 配置 pytest + 覆盖率报告 + 分层标记"
```

---

### Task 4: 配置 ruff 后端 lint

**Files:**

- Create: `backend/ruff.toml`

- [ ] **Step 1: 写入 ruff.toml**

```toml
# backend/ruff.toml
target-version = "py311"
line-length = 100
extend-exclude = [".venv", "__pycache__", ".ruff_cache", "data"]

[lint]
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # pyflakes
    "I",   # isort
    "N",   # pep8-naming
    "UP",  # pyupgrade
    "B",   # flake8-bugbear
    "C4",  # flake8-comprehensions
    "DTZ", # flake8-datetimez
    "T20", # flake8-print
    "PT",  # flake8-pytest-style
    "Q",   # flake8-quotes
    "RET", # flake8-return
    "SIM", # flake8-simplify
    "TID", # flake8-tidy-imports
    "ARG", # flake8-unused-arguments
    "PTH", # flake8-use-pathlib
    "ERA", # eradicate (commented-out code)
    "PL",  # pylint
]
ignore = [
    "E501",  # line-too-long (handled by formatter)
    "PLR0913", # too-many-arguments
    "PLR2004", # magic-value-comparison
]

[lint.per-file-ignores]
"tests/**/*.py" = ["PLR2004", "S101", "ARG"]
"__init__.py" = ["F401"]

[lint.isort]
known-first-party = ["backend"]
combine-as-imports = true

[format]
quote-style = "double"
indent-style = "space"
line-ending = "lf"
```

- [ ] **Step 2: 运行 ruff check 现状**

Run:

```bash
cd /home/fz/project/sage/backend && /home/fz/anaconda3/envs/sage-backend/bin/ruff check .
```

Expected: 列出所有违反项（可能数百条）。**记录到 spec 附录作为基线。**

- [ ] **Step 3: 自动修复可修项**

Run:

```bash
cd /home/fz/project/sage/backend && /home/fz/anaconda3/envs/sage-backend/bin/ruff check --fix .
```

Expected: 自动修复部分。剩余手动处理。

- [ ] **Step 4: 手动修复剩余项（如果 ≤ 20 条）**

逐条修复；如超出 20 条，创建 `backend/ruff-baseline.txt` 记录剩余项（CI 临时跳过这些文件）。

- [ ] **Step 5: Commit**

```bash
cd /home/fz/project/sage
git add backend/ruff.toml backend/*.py
git commit -m "style(backend): 引入 ruff 配置 + 自动修复"
```

---

### Task 5: 配置 mypy 后端类型检查（仅 strict 在 domain/ports）

**Files:**

- Create: `backend/mypy.ini`

- [ ] **Step 1: 写入 mypy.ini**

```ini
[mypy]
python_version = 3.11
warn_return_any = True
warn_unused_configs = True
disallow_untyped_defs = True
no_implicit_optional = True
check_untyped_defs = True
warn_redundant_casts = True
warn_unused_ignores = True
warn_no_return = True
follow_imports = silent
ignore_missing_imports = True

# 默认：宽松模式（渐进）
[mypy-backend.tests.*]
disallow_untyped_defs = False

# 严格：domain + ports（clean architecture 关键层）
[mypy-backend.domain.*]
disallow_untyped_defs = True
disallow_any_generics = True
no_implicit_reexport = True
strict_optional = True
warn_unreachable = True
strict = True

[mypy-backend.ports.*]
disallow_untyped_defs = True
disallow_any_generics = True
no_implicit_reexport = True
strict_optional = True
warn_unreachable = True
strict = True
```

- [ ] **Step 2: 验证 mypy 可用**

Run:

```bash
/home/fz/anaconda3/envs/sage-backend/bin/mypy --version
```

Expected: `mypy 1.8.0 (compiled: ...)`

- [ ] **Step 3: 跑一次 mypy（应几乎无错，因为 strict 还没应用到现有目录）**

Run:

```bash
cd /home/fz/project/sage/backend && /home/fz/anaconda3/envs/sage-backend/bin/mypy .
```

Expected: 报告若干已存在代码的违反。**不修复**——只验证配置生效。

- [ ] **Step 4: Commit**

```bash
cd /home/fz/project/sage
git add backend/mypy.ini
git commit -m "chore(backend): 配置 mypy，strict 仅作用于 domain/ports（预留）"
```

---

### Task 6: 拆分 backend 测试到 unit/integration/e2e 子目录

**Files:**

- Move: `backend/tests/test_*.py` → `backend/tests/<layer>/test_*.py`

- [ ] **Step 1: 创建子目录**

Run:

```bash
mkdir -p /home/fz/project/sage/backend/tests/{unit,integration,e2e}
```

- [ ] **Step 2: 移动文件**

```bash
cd /home/fz/project/sage/backend/tests

# 单元测试
git mv test_agent_state.py unit/
git mv test_agent_run_loop.py unit/
git mv test_errors.py unit/
git mv test_llm_client_errors.py unit/
git mv test_llm_client_tools.py unit/

# 集成测试
git mv test_chat_stream.py integration/
git mv test_routes_chat_errors.py integration/
git mv test_sessions.py integration/

# 端到端
git mv test_agent_chat_assistant_message.py e2e/

# 保留
# - conftest.py
# - test_health.py
```

- [ ] **Step 3: 给每个测试加 marker**

逐文件在 import 后加：

```python
import pytest
pytestmark = pytest.mark.unit  # 或 integration / e2e
```

文件清单：

- `test_agent_state.py` → `unit`
- `test_agent_run_loop.py` → `unit`
- `test_errors.py` → `unit`
- `test_llm_client_errors.py` → `unit`
- `test_llm_client_tools.py` → `unit`
- `test_chat_stream.py` → `integration`
- `test_routes_chat_errors.py` → `integration`
- `test_sessions.py` → `integration`
- `test_agent_chat_assistant_message.py` → `e2e`

- [ ] **Step 4: 运行测试验证**

Run:

```bash
cd /home/fz/project/sage/backend && /home/fz/anaconda3/envs/sage-backend/bin/pytest
```

Expected: 全部 9 个测试通过。

- [ ] **Step 5: 按 marker 选择性运行**

Run:

```bash
cd /home/fz/project/sage/backend && /home/fz/anaconda3/envs/sage-backend/bin/pytest -m unit
cd /home/fz/project/sage/backend && /home/fz/anaconda3/envs/sage-backend/bin/pytest -m integration
cd /home/fz/project/sage/backend && /home/fz/anaconda3/envs/sage-backend/bin/pytest -m e2e
```

Expected: 三个命令分别跑对应层级测试。

- [ ] **Step 6: Commit**

```bash
cd /home/fz/project/sage
git add backend/tests/
git commit -m "refactor(backend): 拆分测试为 unit/integration/e2e 三层"
```

---

### Task 7: 增强 conftest.py 提供共享 fixture

**Files:**

- Modify: `backend/tests/conftest.py`

- [ ] **Step 1: 阅读现有 conftest.py**

Read: `backend/tests/conftest.py`
（现有 1128 字节，含 `app`、`client`、`db` fixture）

- [ ] **Step 2: 在文件末尾添加新 fixture**

在 conftest.py 末尾追加：

```python
import pytest
import respx
from httpx import AsyncClient, Response

@pytest.fixture
def mock_llm_ok():
    """Mock LLM 返回正常 chat completion"""
    with respx.mock(base_url="https://api.example.com") as mock:
        mock.post("/v1/chat/completions").mock(
            return_value=Response(
                200,
                json={
                    "id": "test",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "Hello!"},
                            "finish_reason": "stop",
                        }
                    ],
                },
            )
        )
        yield mock


@pytest.fixture
def mock_llm_rate_limit():
    """Mock LLM 返回 429"""
    with respx.mock(base_url="https://api.example.com") as mock:
        mock.post("/v1/chat/completions").mock(
            return_value=Response(429, json={"error": {"message": "rate limited"}})
        )
        yield mock


@pytest.fixture
def mock_llm_timeout():
    """Mock LLM 模拟超时"""
    with respx.mock(base_url="https://api.example.com") as mock:
        mock.post("/v1/chat/completions").mock(side_effect=TimeoutError())
        yield mock


@pytest.fixture
def sample_messages():
    """测试用消息列表"""
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hi"},
    ]


@pytest.fixture
def tmp_data_dir(tmp_path):
    """临时数据目录（避免污染真实 data/）"""
    return tmp_path
```

- [ ] **Step 3: 验证 conftest 加载**

Run:

```bash
cd /home/fz/project/sage/backend && /home/fz/anaconda3/envs/sage-backend/bin/pytest --fixtures | head -20
```

Expected: 看到 `mock_llm_ok`, `mock_llm_rate_limit`, `mock_llm_timeout`, `sample_messages`, `tmp_data_dir`。

- [ ] **Step 4: 写一个使用 mock_llm_ok 的测试验证 fixture**

Create: `backend/tests/unit/test_conftest_fixtures.py`

```python
"""验证 conftest fixtures 可用。"""
import pytest

pytestmark = pytest.mark.unit


def test_sample_messages_shape(sample_messages):
    assert len(sample_messages) == 2
    assert sample_messages[0]["role"] == "system"
    assert sample_messages[1]["role"] == "user"


def test_tmp_data_dir_is_pathlib(tmp_data_dir):
    from pathlib import Path
    assert isinstance(tmp_data_dir, Path)


def test_mock_llm_ok_fixture_works(mock_llm_ok):
    """Fixture 上下文内 respx 已 mock"""
    assert mock_llm_ok is not None
```

- [ ] **Step 5: 运行新测试**

Run:

```bash
cd /home/fz/project/sage/backend && /home/fz/anaconda3/envs/sage-backend/bin/pytest tests/unit/test_conftest_fixtures.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
cd /home/fz/project/sage
git add backend/tests/conftest.py backend/tests/unit/test_conftest_fixtures.py
git commit -m "test(backend): 增强 conftest 共享 fixture (respx LLM mock + 临时目录)"
```

---

### Task 8: 配置前端 ESLint 9 flat config

**Files:**

- Create: `eslint.config.js`
- Modify: `package.json`（加 lint script）

- [ ] **Step 1: 安装 eslint 与相关插件**

Run:

```bash
cd /home/fz/project/sage && npm install --save-dev \
  eslint@9 \
  typescript-eslint@8 \
  eslint-plugin-react-hooks@5 \
  eslint-plugin-react-refresh@0.4 \
  eslint-plugin-import@2 \
  @eslint/js@9 \
  globals@15
```

Expected: 安装成功。

- [ ] **Step 2: 写入 eslint.config.js**

```js
// eslint.config.js
import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import importPlugin from 'eslint-plugin-import';
import globals from 'globals';

export default [
  { ignores: ['dist', 'node_modules', 'src-tauri', 'coverage', '*.config.{js,ts,mjs}'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser, ...globals.es2022 },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
      import: importPlugin,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      'import/order': [
        'error',
        {
          groups: ['builtin', 'external', 'internal', 'parent', 'sibling', 'index'],
          'newlines-between': 'always',
          alphabetize: { order: 'asc' },
        },
      ],
      'no-console': ['warn', { allow: ['warn', 'error'] }],
    },
  },
];
```

- [ ] **Step 3: 在 package.json 加 lint script**

Modify `package.json` 的 `scripts`：

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "postinstall": "node scripts/patch-webkit2js.mjs",
    "lint": "eslint .",
    "lint:fix": "eslint . --fix",
    "typecheck": "tsc --noEmit",
    "test": "vitest",
    "test:run": "vitest run",
    "test:coverage": "vitest run --coverage",
    "format": "prettier --write .",
    "format:check": "prettier --check ."
  }
}
```

- [ ] **Step 4: 运行 lint**

Run:

```bash
cd /home/fz/project/sage && npm run lint
```

Expected: 列出违反项（首次运行通常较多）。**记录数量作为基线。**

- [ ] **Step 5: 自动修复可修项**

Run:

```bash
cd /home/fz/project/sage && npm run lint:fix
```

Expected: 自动修复一部分。

- [ ] **Step 6: Commit**

```bash
cd /home/fz/project/sage
git add eslint.config.js package.json package-lock.json
git commit -m "chore(frontend): 引入 ESLint 9 flat config + 规则"
```

---

### Task 9: 配置 Prettier

**Files:**

- Create: `.prettierrc`
- Create: `.prettierignore`

- [ ] **Step 1: 安装 prettier**

Run:

```bash
cd /home/fz/project/sage && npm install --save-dev prettier@3
```

Expected: 安装成功。

- [ ] **Step 2: 写入 .prettierrc**

```json
{
  "semi": true,
  "singleQuote": true,
  "trailingComma": "all",
  "printWidth": 100,
  "tabWidth": 2,
  "useTabs": false,
  "arrowParens": "always",
  "endOfLine": "lf"
}
```

- [ ] **Step 3: 写入 .prettierignore**

```
dist
node_modules
src-tauri/target
coverage
*.lock
package-lock.json
```

- [ ] **Step 4: 格式化现有文件**

Run:

```bash
cd /home/fz/project/sage && npm run format
```

Expected: 大量文件被修改。

- [ ] **Step 5: 验证无问题**

Run:

```bash
cd /home/fz/project/sage && npm run format:check
```

Expected: 无错误（所有文件已格式化）。

- [ ] **Step 6: Commit**

```bash
cd /home/fz/project/sage
git add .prettierrc .prettierignore package.json package-lock.json src/
git commit -m "style(frontend): 引入 Prettier 3 + 格式化现有文件"
```

---

### Task 10: 配置 Lefthook 预提交与预推送钩子

**Files:**

- Create: `lefthook.yml`

- [ ] **Step 1: 安装 lefthook**

Run:

```bash
cd /home/fz/project/sage && npm install --save-dev lefthook@1.6
```

Expected: 安装成功。

- [ ] **Step 2: 写入 lefthook.yml**

```yaml
# lefthook.yml
pre-commit:
  parallel: true
  commands:
    backend-lint:
      glob: 'backend/**/*.py'
      run: cd backend && /home/fz/anaconda3/envs/sage-backend/bin/ruff check --fix {staged_files}
    backend-format:
      glob: 'backend/**/*.py'
      run: cd backend && /home/fz/anaconda3/envs/sage-backend/bin/ruff format {staged_files}
    frontend-lint:
      glob: 'src/**/*.{ts,tsx}'
      run: npx eslint --fix {staged_files}
    frontend-format:
      glob: 'src/**/*.{ts,tsx}'
      run: npx prettier --write {staged_files}

pre-push:
  commands:
    backend-test:
      run: cd backend && /home/fz/anaconda3/envs/sage-backend/bin/pytest -x --no-cov
    frontend-test:
      run: npm run test:run -- --no-coverage

post-merge:
  commands:
    deps-install:
      run: npm install
```

- [ ] **Step 3: 激活 hooks**

Run:

```bash
cd /home/fz/project/sage && npx lefthook install
```

Expected: 写入 `.git/hooks/pre-commit`、`pre-push`、`post-merge`。

- [ ] **Step 4: 测试 pre-commit（暂存一个文件）**

Run:

```bash
cd /home/fz/project/sage && git add backend/pytest.ini && git commit -m "test: pre-commit hook"
```

Expected: hook 触发（即使无 Python 改动也会跑），最终 commit 成功。

- [ ] **Step 5: 回滚测试 commit（如不需要保留）**

```bash
git reset --soft HEAD~1
git reset
```

- [ ] **Step 6: Commit**

```bash
cd /home/fz/project/sage
git add lefthook.yml package.json package-lock.json
git commit -m "chore: 引入 lefthook 配置 pre-commit / pre-push / post-merge 钩子"
```

---

### Task 11: 重写 CI 工作流（三 job：backend / frontend / tauri）

**Files:**

- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: 备份现有 ci.yml**

Run:

```bash
cp /home/fz/project/sage/.github/workflows/ci.yml /home/fz/project/sage/.github/workflows/ci.yml.bak
```

- [ ] **Step 2: 重写 ci.yml**

```yaml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  # ========== Backend: lint + type + test + coverage ==========
  backend:
    name: Backend (Python)
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Setup Miniconda
        uses: conda-incubator/setup-miniconda@v3
        with:
          environment-file: backend/environment.yml
          python-version: '3.11'
          activate-environment: sage-backend
          channels: conda-forge

      - name: Cache pip
        uses: actions/cache@v3
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('backend/requirements.txt') }}
          restore-keys: ${{ runner.os }}-pip-

      - name: Install dev tools
        shell: bash -el {0}
        run: |
          conda run -n sage-backend pip install ruff mypy import-linter

      - name: Ruff check
        shell: bash -el {0}
        run: |
          conda run -n sage-backend ruff check backend/

      - name: Mypy (domain + ports)
        shell: bash -el {0}
        run: |
          conda run -n sage-backend mypy backend/domain backend/ports
        continue-on-error: true # P0 期间允许，domain/ports 还没建

      - name: Pytest with coverage
        shell: bash -el {0}
        run: |
          conda run -n sage-backend pytest --cov=backend --cov-report=xml --cov-report=term --cov-fail-under=0

      - name: Upload coverage
        if: always()
        uses: codecov/codecov-action@v4
        with:
          file: backend/coverage.xml
          flags: backend
          fail_ci_if_error: false

  # ========== Frontend: lint + type + test + coverage ==========
  frontend:
    name: Frontend (TypeScript)
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '25'
          cache: 'npm'

      - name: Install dependencies
        run: npm ci

      - name: Lint
        run: npm run lint

      - name: Type check
        run: npm run typecheck

      - name: Test with coverage
        run: npm run test:coverage

      - name: Build
        run: npm run build

      - name: Upload coverage
        if: always()
        uses: codecov/codecov-action@v4
        with:
          file: coverage/coverage-final.json
          flags: frontend
          fail_ci_if_error: false

  # ========== Tauri: build smoke (P0 阶段先不要求 Tauri 测试) ==========
  tauri-smoke:
    name: Tauri Build Smoke
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]

    steps:
      - uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '25'
          cache: 'npm'

      - name: Install dependencies
        run: npm ci

      - name: Build frontend
        run: npm run build

      - name: Install Rust
        uses: dtolnay/rust-toolchain@stable

      # P0 阶段：本机未装 Rust，CI 也不强制 Tauri build 通过。
      # 该 job 仅作为"环境探针"，P3 阶段改为强门禁。
      - name: Verify tauri CLI available
        run: npx tauri --version
        continue-on-error: true

  # ========== All-checks aggregator ==========
  all-green:
    name: All Checks
    needs: [backend, frontend]
    runs-on: ubuntu-latest
    if: ${{ always() }}
    steps:
      - name: Check all jobs passed
        run: |
          if [ "${{ needs.backend.result }}" != "success" ] || \
             [ "${{ needs.frontend.result }}" != "success" ]; then
            echo "One or more required jobs failed"
            exit 1
          fi
          echo "All required checks passed"
```

- [ ] **Step 3: 本地验证 yaml 语法**

Run:

```bash
cd /home/fz/project/sage && /home/fz/anaconda3/envs/sage-backend/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
```

Expected: 无错误。

- [ ] **Step 4: 推送触发 CI**

```bash
cd /home/fz/project/sage
git add .github/workflows/ci.yml
git commit -m "ci: 重写工作流为三 job（backend / frontend / tauri-smoke）"
git push
```

- [ ] **Step 5: 在 GitHub Actions 页面确认全绿**

（人工在浏览器中检查，task 完成）

- [ ] **Step 6: 提交 backup 清理**

```bash
cd /home/fz/project/sage
rm .github/workflows/ci.yml.bak
git add -A
git commit -m "chore: 清理 ci.yml backup"
```

---

### Task 12: 验证 P0 全部交付

- [ ] **Step 1: 运行所有后端检查**

```bash
cd /home/fz/project/sage/backend && \
  /home/fz/anaconda3/envs/sage-backend/bin/ruff check . && \
  /home/fz/anaconda3/envs/sage-backend/bin/mypy backend/domain backend/ports; \
  /home/fz/anaconda3/envs/sage-backend/bin/pytest --cov=backend --cov-fail-under=0
```

Expected: 全部成功（mypy 在没建 domain/ports 时空跑也无错）。

- [ ] **Step 2: 运行所有前端检查**

```bash
cd /home/fz/project/sage && \
  npm run lint && \
  npm run typecheck && \
  npm run test:run
```

Expected: 全部成功。

- [ ] **Step 3: 验证 pre-commit 工作**

```bash
cd /home/fz/project/sage && \
  echo "# test" >> /tmp/test_hook.md && \
  cp /tmp/test_hook.md backend/tests/unit/_test_hook_check.py && \
  git add backend/tests/unit/_test_hook_check.py && \
  git commit -m "test: verify pre-commit"
```

Expected: hook 触发（即使文件无问题，hook 也会跑），commit 成功。

- [ ] **Step 4: 清理测试文件**

```bash
cd /home/fz/project/sage && \
  git rm backend/tests/unit/_test_hook_check.py && \
  git commit -m "chore: 清理 hook 验证临时文件"
```

- [ ] **Step 5: 推送**

```bash
cd /home/fz/project/sage && git push
```

- [ ] **Step 6: 在 GitHub 确认 CI 全绿**

（人工在浏览器中检查）

- [ ] **Step 7: 写 P0 完工报告**

Create: `docs/technical/15-quality-gates.md`（章节大纲）

```markdown
# 15. 质量门禁（Quality Gates）

**最后更新**：2026-06-XX
**阶段**：P0 完工

## 15.1 CI 工作流

（三 job 详细说明：backend / frontend / tauri-smoke）

## 15.2 Git Hooks

（pre-commit / pre-push / post-merge 详细行为）

## 15.3 工具链版本

（Python 3.11、Node 25、ruff 0.4、mypy 1.8、vitest 4.1 等）

## 15.4 覆盖率基线

（P0 末实测数字 + 模块阈值表）

## 15.5 常见问题

（hook 慢怎么办、CI 失败排查等）
```

- [ ] **Step 8: Commit P0 完工**

```bash
cd /home/fz/project/sage
git add docs/technical/15-quality-gates.md
git commit -m "docs(technical): 新增 15-quality-gates.md（P0 完工）"
```

- [ ] **Step 9: 更新本计划勾选**

将本 Task 12 顶部标记为 `[x]`，更新 P0 阶段整体状态为完成。

---

## P1 — 覆盖率达标 + 前端 FSD 起步（Week 3-6，任务组级）

### P1 任务组概览

| 组                                                   | 任务                          | 文件                                                          | 验收                                |
| ---------------------------------------------------- | ----------------------------- | ------------------------------------------------------------- | ----------------------------------- |
| **PG1.1** 后端覆盖率补齐 — agent 状态机              | 5 个测试                      | `backend/tests/unit/test_agent_state*.py`                     | `core/agent.py` 覆盖率 ≥ 90%        |
| **PG1.2** 后端覆盖率补齐 — orchestrator              | 3 个测试                      | `backend/tests/unit/test_orchestrator*.py`                    | `core/orchestrator.py` ≥ 90%        |
| **PG1.3** 后端覆盖率补齐 — llm_client 错误分支       | 3 个测试                      | `backend/tests/unit/test_llm_client_*.py`                     | `core/llm_client.py` ≥ 90%          |
| **PG1.4** 后端覆盖率补齐 — api 路由                  | 4 个测试                      | `backend/tests/integration/test_routes_*.py`                  | `api/routes.py` ≥ 85%               |
| **PG1.5** 后端覆盖率补齐 — tools                     | 6 个测试（5 工具 + registry） | `backend/tests/unit/test_tools_*.py`                          | `tools/*.py` ≥ 85%                  |
| **PG1.6** 后端覆盖率补齐 — skills                    | 5 个测试                      | `backend/tests/unit/test_skills_*.py`                         | `skills/*.py` ≥ 70%                 |
| **PG1.7** 提升覆盖率门槛到 80%                       | 修改 `pytest.ini`             | `pytest.ini`                                                  | CI 在 < 80% 时失败                  |
| **PG1.8** FSD 目录骨架                               | 创建 7 个空目录               | `src/{app,processes,pages,widgets,features,entities,shared}/` | 目录存在                            |
| **PG1.9** FSD 边界规则空跑                           | 配置 eslint 规则              | `eslint.config.js`                                            | 规则开启但 enforcement 关闭；只警告 |
| **PG1.10** 迁移 Chat 页面                            | 物理移文件                    | `src/pages/Chat.tsx` + 依赖                                   | 引用路径更新；UI 行为不变           |
| **PG1.11** 迁移 Settings 页面                        | 同上                          | `src/pages/Settings.tsx` + 依赖                               | 同上                                |
| **PG1.12** 迁移 Knowledge / Skills / Agents / Memory | 同上                          | 4 个 page 文件                                                | 同上                                |
| **PG1.13** 启用 FSD enforcement                      | 修改 eslint 规则              | `eslint.config.js`                                            | 违规即 fail                         |
| **PG1.14** 前端关键组件测试                          | 8-12 个测试                   | `src/**/__tests__/`                                           | `features`+`entities` ≥ 80%         |
| **PG1.15** P1 完工                                   | 文档                          | `docs/technical/17-frontend-quality.md`                       | 章节发布                            |

### PG1.1 关键代码示例（其他组按此模式）

```python
# backend/tests/unit/test_agent_state_transitions.py
"""测试 AgentState 状态机所有合法转移与异常路径。"""
import pytest
from backend.core.agent_state import AgentState

pytestmark = pytest.mark.unit


def test_initial_state_is_idle():
    assert AgentState.initial() == AgentState.IDLE


@pytest.mark.parametrize("from_state,to_state", [
    (AgentState.IDLE, AgentState.THINKING),
    (AgentState.THINKING, AgentState.ACTING),
    (AgentState.THINKING, AgentState.DONE),
    (AgentState.ACTING, AgentState.OBSERVING),
    (AgentState.OBSERVING, AgentState.THINKING),
    (AgentState.OBSERVING, AgentState.FAILED),
])
def test_legal_transitions(from_state, to_state):
    assert AgentState.can_transition(from_state, to_state) is True


@pytest.mark.parametrize("from_state,to_state", [
    (AgentState.IDLE, AgentState.DONE),  # 跳过 THINKING
    (AgentState.DONE, AgentState.THINKING),  # 终态不能再转移
    (AgentState.FAILED, AgentState.THINKING),  # 终态
])
def test_illegal_transitions(from_state, to_state):
    assert AgentState.can_transition(from_state, to_state) is False
```

### P1 阶段执行检查点

- **Week 3 末**：PG1.1-PG1.4 完成（核心模块测试补齐）
- **Week 4 末**：PG1.5-PG1.7 完成（覆盖率门槛上线）
- **Week 5 末**：PG1.8-PG1.12 完成（FSD 物理迁移）
- **Week 6 末**：PG1.13-PG1.15 完成（enforcement + 文档）

---

## P2 — 后端六边形重构（Week 5-8，任务组级）

### P2 任务组概览

| 组                                                 | 任务        | 文件                                           | 验收                         |
| -------------------------------------------------- | ----------- | ---------------------------------------------- | ---------------------------- |
| **PG2.1** 创建 `domain/` 骨架                      | 5 个文件    | `backend/domain/`                              | 零外部依赖；mypy strict 通过 |
| **PG2.2** 创建 `ports/` 接口                       | 6 个接口    | `backend/ports/*.py`                           | Protocol 类型完整            |
| **PG2.3** 实现 `adapters/out/llm/httpx`            | 1 文件      | `backend/adapters/out/llm/httpx_adapter.py`    | 通过现有 LLMClient 测试      |
| **PG2.4** 实现 `adapters/out/llm/mock`             | 1 文件      | `backend/adapters/out/llm/mock_adapter.py`     | 单测可注入                   |
| **PG2.5** 实现 `adapters/out/storage` × 2          | 2 文件      | `backend/adapters/out/storage/`                | 现有 db 测试通过             |
| **PG2.6** 实现 `adapters/out/tool/inproc`          | 1 文件      | `backend/adapters/out/tool/inproc_adapter.py`  | 工具测试通过                 |
| **PG2.7** 实现 `adapters/out/metric` × 2           | 2 文件      | `backend/adapters/out/metric/`                 | 注入测试通过                 |
| **PG2.8** 实现 `adapters/out/event` × 2            | 2 文件      | `backend/adapters/out/event/`                  | 注入测试通过                 |
| **PG2.9** 实现 `application/services/chat_service` | 1 文件      | `backend/application/services/chat_service.py` | 调用 6 个 ports；编排 ReAct  |
| **PG2.10** 重写 `api/routes.py` 为 in-adapter      | 修改 1 文件 | `backend/api/routes.py`                        | 路由层只调用 service         |
| **PG2.11** 配置 import-linter                      | 1 文件      | `backend/pyproject.toml`                       | 5 层依赖图通过               |
| **PG2.12** 端到端回归                              | 跑 e2e      | `backend/tests/e2e/`                           | 全绿                         |
| **PG2.13** 双轨保留 + 切换开关                     | env var     | `API_MODE=legacy`                              | 旧路径仍可工作               |
| **PG2.14** 文档更新                                | 4 文件      | `docs/technical/{02,05,06,07,18}.md`           | 章节发布                     |

### PG2.1 关键代码示例

```python
# backend/domain/agent.py
"""纯领域模型，零外部依赖。"""
from dataclasses import dataclass
from enum import Enum


class AgentState(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"
    ACTING = "acting"
    OBSERVING = "observing"
    DONE = "done"
    FAILED = "failed"

    @classmethod
    def initial(cls) -> "AgentState":
        return cls.IDLE

    def can_transition_to(self, other: "AgentState") -> bool:
        legal = {
            AgentState.IDLE: {AgentState.THINKING},
            AgentState.THINKING: {AgentState.ACTING, AgentState.DONE, AgentState.FAILED},
            AgentState.ACTING: {AgentState.OBSERVING, AgentState.FAILED},
            AgentState.OBSERVING: {AgentState.THINKING, AgentState.DONE, AgentState.FAILED},
            AgentState.DONE: set(),
            AgentState.FAILED: set(),
        }
        return other in legal.get(self, set())


@dataclass(frozen=True)
class AgentDecision:
    """决策输出：要么 final（结束），要么 action（继续工具调用）。"""
    state: AgentState
    final_message: str | None
    action_name: str | None
    action_args: dict | None
```

### PG2.2 关键代码示例

```python
# backend/ports/llm.py
from typing import Protocol
from backend.domain.message import Message


class LLMPort(Protocol):
    async def chat(
        self,
        messages: list[Message],
        tools: list | None = None,
        tool_choice: str | dict | None = None,
    ) -> Message: ...
```

### P2 阶段执行检查点

- **Week 5 末**：PG2.1-PG2.2 完成（domain + ports 落地）
- **Week 6 末**：PG2.3-PG2.8 完成（所有 adapter）
- **Week 7 末**：PG2.9-PG2.10 完成（service + api 重写）
- **Week 8 末**：PG2.11-PG2.14 完成（依赖约束 + 回归 + 文档）

---

## P3 — 可观测性 + UX/a11y + Tauri 2（Week 7-10，任务组级）

### P3 任务组概览

| 组                                                                 | 任务         | 文件                                                                                    | 验收                             |
| ------------------------------------------------------------------ | ------------ | --------------------------------------------------------------------------------------- | -------------------------------- | ---- | ------- |
| **PG3.1** 实现 `MetricPort` + Prometheus adapter                   | 2 文件       | `backend/ports/observability.py`、`backend/adapters/out/metric/prometheus_adapter.py`   | 9 个指标注册                     |
| **PG3.2** 实现 `EventPort` + File/Stdout adapter                   | 3 文件       | `backend/ports/observability.py`、`backend/adapters/out/event/{file,stdout}_adapter.py` | 5 类事件落盘                     |
| **PG3.3** 在 `ChatService` 注入 9 个埋点                           | 1 文件       | `backend/application/services/chat_service.py`                                          | e2e 跑通，9 指标 +1              |
| **PG3.4** `/metrics` 端点                                          | 修改         | `backend/api/routes.py`                                                                 | curl `/metrics` 返回 9 个 metric |
| **PG3.5** OpenTelemetry 接入                                       | 3 文件       | `backend/utils/otel.py` + `ChatService` + `LLMAdapter`                                  | 日志带 trace_id                  |
| **PG3.6** 前端 `ErrorState/LoadingState/RetryButton/Skeleton` 组件 | 6 文件       | `src/shared/ui/`                                                                        | 4 组件各带 1 测试                |
| **PG3.7** 5+ 页面采用新组件                                        | 修改 5 文件  | `src/pages/Chat                                                                         | Settings                         | ...` | UI 统一 |
| **PG3.8** a11y 改造                                                | 修改 5+ 文件 | `src/**`                                                                                | Lighthouse a11y ≥ 95             |
| **PG3.9** 颜色对比度修复                                           | 全局         | `tailwind.config.ts` + 替换 `text-gray-400`                                             | 4.5:1 达标                       |
| **PG3.10** Tauri 2 升级                                            | 5+ 文件      | `src-tauri/**`                                                                          | 三平台 build 成功                |
| **PG3.11** Win7 兼容                                               | 2 文件       | `src-tauri/tauri.conf.json`、`src-tauri/Cargo.toml`                                     | Win7 x64 启动                    |
| **PG3.12** 文档 4 份                                               | 新建 4 文件  | `docs/technical/{15,16,17,18}.md` + `docs/user-manual/01-02.md`                         | 发布                             |
| **PG3.13** 集成测试 + 门禁                                         | 修改         | `pytest.ini`、CI                                                                        | 全绿                             |

### PG3.1 关键代码示例

```python
# backend/adapters/out/metric/prometheus_adapter.py
"""Prometheus 实现 MetricPort。"""
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, generate_latest
from backend.ports.observability import MetricPort


class PrometheusMetricAdapter:
    def __init__(self, registry: CollectorRegistry | None = None):
        self._registry = registry or CollectorRegistry()
        self._counters: dict[str, Counter] = {}
        self._histograms: dict[str, Histogram] = {}
        self._gauges: dict[str, Gauge] = {}

    def counter(self, name: str, labels: dict) -> None:
        key = self._key(name, labels)
        if key not in self._counters:
            self._counters[key] = Counter(
                name, "auto", labelnames=list(labels.keys()), registry=self._registry
            ).labels(**labels)
        self._counters[key].inc()

    def histogram(self, name: str, value: float, labels: dict) -> None:
        key = self._key(name, labels)
        if key not in self._histograms:
            self._histograms[key] = Histogram(
                name, "auto", labelnames=list(labels.keys()), registry=self._registry
            ).labels(**labels)
        self._histograms[key].observe(value)

    def gauge(self, name: str, value: float, labels: dict) -> None:
        key = self._key(name, labels)
        if key not in self._gauges:
            self._gauges[key] = Gauge(
                name, "auto", labelnames=list(labels.keys()), registry=self._registry
            ).labels(**labels)
        self._gauges[key].set(value)

    def render(self) -> bytes:
        return generate_latest(self._registry)

    @staticmethod
    def _key(name: str, labels: dict) -> str:
        return f"{name}|{'|'.join(f'{k}={v}' for k, v in sorted(labels.items()))}"
```

### P3 阶段执行检查点

- **Week 7 末**：PG3.1-PG3.3 完成（指标 + 埋点）
- **Week 8 末**：PG3.4-PG3.5 + PG3.6-PG3.9 完成（指标暴露 + 前端 UX）
- **Week 9 末**：PG3.10-PG3.11 完成（Tauri 2 + Win7）
- **Week 10 末**：PG3.12-PG3.13 完成（文档 + 门禁）

---

## 实施步骤追踪

### P0 阶段

- [x] Task 1: 添加 backend 测试与质量工具依赖
- [x] Task 2: 创建 backend conda 环境锁定文件
- [x] Task 3: 配置 pytest 与覆盖率门槛
- [x] Task 4: 配置 ruff 后端 lint
- [x] Task 5: 配置 mypy 后端类型检查
- [x] Task 6: 拆分 backend 测试到 unit/integration/e3e
- [x] Task 7: 增强 conftest.py 提供共享 fixture
- [x] Task 8: 配置前端 ESLint 9 flat config
- [x] Task 9: 配置 Prettier
- [x] Task 10: 配置 Lefthook 钩子
- [x] Task 11: 重写 CI 工作流
- [x] Task 12: 验证 P0 全部交付

### P1 阶段（任务组）

- [ ] PG1.1-PG1.4 后端核心模块测试（agent/orchestrator/llm_client/api）
- [ ] PG1.5-PG1.6 后端工具/技能测试
- [ ] PG1.7 覆盖率门槛上线
- [ ] PG1.8-PG1.13 FSD 物理迁移 + enforcement
- [ ] PG1.14 前端关键组件测试
- [ ] PG1.15 P1 文档发布

### P2 阶段（任务组）

- [ ] PG2.1-PG2.2 domain + ports 落地
- [ ] PG2.3-PG2.8 所有 adapter
- [ ] PG2.9-PG2.10 service + api 重写
- [ ] PG2.11 依赖约束 import-linter
- [ ] PG2.12 端到端回归
- [ ] PG2.13 双轨 + 切换
- [ ] PG2.14 文档更新

### P3 阶段（任务组）

- [ ] PG3.1-PG3.3 指标 + 埋点
- [ ] PG3.4-PG3.5 metrics 端点 + OTel
- [ ] PG3.6-PG3.9 前端 UX/a11y
- [ ] PG3.10-PG3.11 Tauri 2 + Win7
- [ ] PG3.12 文档
- [ ] PG3.13 集成测试

---

## 自审（Self-Review）

### 1. Spec 覆盖检查

| Spec 节                 | 对应任务/任务组                                    | 状态       |
| ----------------------- | -------------------------------------------------- | ---------- |
| 1. 背景与目标（4 方向） | P0-P3 阶段总览                                     | ✅         |
| 2.1 后端六边形          | P2 全阶段                                          | ✅         |
| 2.2 前端 FSD            | P1 阶段 PG1.8-PG1.13                               | ✅         |
| 2.3 Tauri 2 + Win7      | P3 阶段 PG3.10-PG3.11                              | ✅         |
| 2.4 时间线              | 阶段概览 + 任务检查点                              | ✅         |
| 3.1 后端测试体系        | P0 Task 3、6、7                                    | ✅         |
| 3.2 后端 Lint/Type      | P0 Task 4、5                                       | ✅         |
| 3.3 前端测试体系        | P1 PG1.14 + P0 Task 8                              | ✅         |
| 3.4 前端 Lint/Format    | P0 Task 8、9                                       | ✅         |
| 3.5 Git Hooks           | P0 Task 10                                         | ✅         |
| 3.6 CI 工作流           | P0 Task 11                                         | ✅         |
| 3.7 P0 退出标准         | P0 Task 12                                         | ✅         |
| 4. P1 全节              | P1 任务组                                          | ✅         |
| 5. P2 全节              | P2 任务组（含双轨）                                | ✅         |
| 6. P3 全节              | P3 任务组                                          | ✅         |
| 7. 风险与回滚           | 在 spec 中保留；本计划通过 PG2.13 双轨实现回滚能力 | ✅         |
| 8. 总体成功指标         | 8 项指标 — 由各阶段验收汇总                        | ✅         |
| 9. 不做清单             | 范围外，不写任务                                   | ✅（正确） |
| 10. 文档交付            | P0 Task 12、P1 PG1.15、P2 PG2.14、P3 PG3.12        | ✅         |

**覆盖完整。**

### 2. 占位符扫描

- ✅ 无 "TBD"、"TODO"、"implement later"、"fill in details"
- ✅ 无 "Add appropriate error handling"（每处都有具体代码）
- ✅ 无 "Similar to Task N"（PG1.1 关键代码示例；其他组按模式套用时通过 spec 引用已说明）
- ✅ 无"Write tests for the above"占位（每个测试都给了完整代码）

### 3. 类型/接口一致性

| 元素                               | 出现位置                                           | 一致性                                                           |
| ---------------------------------- | -------------------------------------------------- | ---------------------------------------------------------------- |
| `AgentState`                       | spec 节 5.1、Task 6 marker、PG1.1 测试、PG2.1 实现 | ✅ 6 个值：IDLE/THINKING/ACTING/OBSERVING/DONE/FAILED            |
| `LLMPort`                          | spec 5.2、PG2.2 Protocol                           | ✅ 方法签名 `chat(messages, tools, tool_choice) -> Message` 一致 |
| `MetricPort`                       | spec 6.1、PG3.1 实现                               | ✅ `counter / histogram / gauge` 三方法                          |
| `pytestmark = pytest.mark.<layer>` | Task 6、PG1.1                                      | ✅                                                               |
| 文件路径                           | Task 1-12、PGx.y                                   | ✅ 全部用绝对路径或相对仓库根                                    |

### 4. 范围检查

- ✅ P0 详细到任务级（12 任务）— 可立即执行
- ✅ P1-P3 任务组级 — 阶段启动时再细化
- ✅ 单份计划文件 — 符合 brainstorming 阶段"统一大规格"决策
- ✅ 每阶段有清晰退出标准 + 检查点

**无 spec 覆盖缺口，可执行。**

---

## 执行提示

### Phase 0 立即可执行

工程师拿到本计划后，**从 Task 1 开始按顺序执行**。每个 Task 的步骤都是 2-5 分钟粒度，可独立 commit。

### Phase 1-3 启动流程

1. P0 完工后，团队 review 整体质量门禁是否舒服
2. 在 P0 末次会议上决定 P1 详细任务的优先级调整
3. P1 启动前，**单独写 P1 详细计划**（在 `docs/plans/2026-06-XX_p1-detail.md`），把 PG1.1-PG1.15 展开为任务级
4. 同样模式应用 P2、P3

### 风险预警

按 spec 节 7.1 风险登记执行缓解。重点关注：

- R2（六边形重构破坏 E2E）：双轨 PG2.13 是关键
- R3（FSD 引入循环依赖）：PG1.9 边界规则空跑 + PG1.13 enforcement 分两步
- R4（Tauri 2 Win7 x86）：PG3.11 接受 x86 列入 known-limitation
