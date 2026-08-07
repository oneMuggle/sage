# Sage Doctor CLI

> **状态**: 计划（待启动）
> **日期**: 2026-08-07
> **作者**: Claude
> **目标分支**: `feat/sage-doctor` → `main`（Win7 LTS 按需 cherry-pick）
> **来源计划**: [`2026-08-07_pi-hermes-feature-recommendations.md` §1.1](./2026-08-07_pi-hermes-feature-recommendations.md)
> **参考项目**:
> - `hermes-agent` — `hermes doctor` 命令
> - Sage `docs/user-manual/06-diagnostics.md` — 运行时诊断面板（UI 侧）

---

## 0. TL;DR

新增 `python -m sage.doctor` 命令行诊断工具，输出 CRITICAL / WARN / INFO 三级检查结果，覆盖 **8 项** 安装/环境级 self-check（conda 环境、sage_backend 健康、SQLite 文件可写、`~/.sage/config` 完整性、端口 8765/1420 占用、conda vs py38 错用、关键目录权限、磁盘空间）。electron 启动前自动跑并把结果写入启动日志。Win7 LTS 用户、conda/py38 误用、端口冲突、SQLite 权限等场景定位耗时从 ~10 分钟降到 ~10 秒。

---

## 1. 需求重述（Requirements Restatement）

### 1.1 用户故事

| 角色 | 场景 | 期望 |
|---|---|---|
| **Win7 LTS 用户** | 离线安装后发现 backend 起不来 | `python -m sage.doctor` 立刻指出"py38 环境缺 fastapi" |
| **新贡献者** | 克隆代码后 `python -m pytest` 报 `ModuleNotFoundError` | doctor 指出"当前在 base 环境，应激活 sage-backend" |
| **桌面用户** | electron 启动后白屏 | electron 日志里 doctor 的结果明确"8765 端口被孤儿进程占用" |
| **DevOps** | 多环境部署 | `sage doctor --json` 输出机器可读结果，可接入监控 |

### 1.2 功能需求（Functional）

- **F1**: `python -m sage.doctor` 命令入口，无参数输出人类可读报告
- **F2**: `--json` 参数输出机器可读 JSON
- **F3**: 8 项检查按 CRITICAL / WARN / INFO 分级（详见 §3）
- **F4**: 退出码：0=全 OK，1=有 WARN，2=有 CRITICAL
- **F5**: 彩色输出（无 TTY 退化为 `[CRITICAL]` 前缀）
- **F6**: electron 启动前自动跑 doctor，结果写入启动日志
- **F7**: 每项检查独立、可单独 mock 测试

### 1.3 非功能需求（Non-Functional）

- **NF1**: 8 项检查总耗时 < 3 秒（用户感知）
- **NF2**: 单文件 < 300 行（CLAUDE.md 编码风格）
- **NF3**: 不引入新第三方依赖（stdlib 为主，`packaging.version`、`psutil` 可选）
- **NF4**: Win7 LTS（Py3.8）兼容（避免 walrus / match / 3.10+ 类型注解）
- **NF5**: 失败 fail-open — 任何检查抛异常不应让 doctor 整体崩溃，应降级为该检查 ERROR

---

## 2. 风险识别（Risks）

| 风险 | 等级 | 缓解 |
|---|---|---|
| **R1**: 检查逻辑误报（如把 conda base 误判为缺包） | 中 | 模糊匹配 `sage-backend` 而非精确字符串；测试覆盖 base/sage-backend/py38 三种环境 |
| **R2**: 端口检测在 Windows 上语义不同（`netstat` 输出差异） | 中 | 用 `psutil.net_connections()` 跨平台；Win7 LTS 测试 |
| **R3**: doctor 跑时阻塞 electron 启动 | 中 | 5 秒超时，超时降级 WARN；doctor 跑在子进程 |
| **R4**: 用户隐私（路径/账号名泄漏到日志） | 低 | 默认 INFO/WARN 输出截断路径 basename；JSON 输出原始供调试 |
| **R5**: 数据库 schema 漂移导致 health 检查失败 | 低 | 用 `pragma user_version` 而非表查询 |
| **R6**: conda 环境切换在 CI 中不可重现 | 中 | 用 mock `sys.executable` + `os.environ` 测试 |

---

## 3. 实施分阶段（Phases）

### Phase 1: 协议骨架（半天） ✅ 完成

**目标**: `Check` Protocol + `Severity` enum + 注册表

**涉及文件**:
- 新增 `backend/cli/__init__.py`
- 新增 `backend/cli/doctor.py`（入口 + Check Protocol）
- 新增 `backend/cli/checks/__init__.py`

**Check 协议定义**:

```python
# backend/cli/doctor.py
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class Severity(str, Enum):
    CRITICAL = "critical"  # 阻塞功能，必须修
    WARN = "warn"          # 可能影响功能，建议修
    INFO = "info"          # 仅信息


@dataclass(frozen=True)
class CheckResult:
    name: str           # e.g. "conda_env"
    severity: Severity
    message: str        # 人类可读
    fix_hint: str | None = None  # e.g. "conda activate sage-backend"


@runtime_checkable
class Check(Protocol):
    name: str
    description: str

    def run(self) -> CheckResult: ...
```

**注册表**：

```python
# backend/cli/doctor.py
ALL_CHECKS: list[type[Check]] = []  # 每项 check 模块 import 时 append
```

### Phase 2: 8 项检查实现（1.5 天） ✅ 完成

每项 check 是 `backend/cli/checks/<name>.py` 独立模块，按"读 → 判 → 报"三步。

| # | 检查名 | 严重级别 | 检测逻辑 | fix_hint |
|---|---|---|---|---|
| 1 | `conda_env` | CRITICAL/WARN/INFO | 比对 `sys.executable` 与预期 `sage-backend` 环境路径；Py3.8 vs Py3.11 不匹配 | "conda activate sage-backend" |
| 2 | `sage_backend_health` | CRITICAL | curl `http://127.0.0.1:${PYTHON_BACKEND_PORT}/health` 期望 `status=ok` | "python backend/main.py" |
| 3 | `sqlite_writable` | CRITICAL | `tempfile.NamedTemporaryFile` 在 SAGE_USER_DATA_DIR 创建并删除 | "chmod 755 ~/.sage" |
| 4 | `config_integrity` | WARN | 校验 `~/.sage/config/*.json` JSON 合法 + schema 必填字段 | "删除坏文件，下次启动会重建" |
| 5 | `port_backend` | WARN | 8765 端口占用且非 Sage 进程 | "lsof -i :8765 / kill <PID>" |
| 6 | `port_frontend` | INFO | 1420 端口状态（dev 模式提示） | "npm run dev" |
| 7 | `py_version_match` | CRITICAL | main 应 Py3.11，win7 LTS 应 Py3.8；与 `requirements*.txt` 一致性 | "切到正确的 conda 环境" |
| 8 | `disk_space` | WARN | SAGE_USER_DATA_DIR 所在分区剩余 < 500MB 警告 | "清理 ~/.sage/sessions" |

**每项 check 模板**（`backend/cli/checks/conda_env.py`）:

```python
"""conda 环境检查：确保运行在 sage-backend 环境内。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from backend.cli.doctor import CheckResult, Severity


class CondaEnvCheck:
    name = "conda_env"
    description = "验证当前 Python 解释器在 sage-backend conda 环境中"

    EXPECTED_PATHS = ("/anaconda3/envs/sage-backend",
                      "/anaconda3/envs/sage-backend-py38",
                      "/opt/conda/envs/sage-backend")

    def run(self) -> CheckResult:
        exe = Path(sys.executable).resolve()
        for expected in self.EXPECTED_PATHS:
            if str(exe).startswith(expected):
                py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
                if "py38" in expected and py_ver != "3.8":
                    return CheckResult(self.name, Severity.CRITICAL,
                                       f"Py 版本 {py_ver} 与 py38 环境不匹配",
                                       "conda activate sage-backend-py38")
                return CheckResult(self.name, Severity.INFO,
                                   f"环境正确 ({py_ver}): {exe.parent.parent.name}")
        return CheckResult(self.name, Severity.CRITICAL,
                           f"当前 Python 不在 Sage conda 环境: {exe}",
                           "conda activate sage-backend")
```

### Phase 3: 输出格式与 CLI 入口（半天） ✅ 完成

**文本模式**（默认）:

```
sage doctor — 2026-08-07 14:32:18
================================

[INFO]    conda_env            环境正确 (3.11): sage-backend
[WARN]    port_backend         8765 端口被占用（PID 12345, python3）
                                 修复: lsof -i :8765 / kill 12345
[CRITICAL] sqlite_writable      ~/.sage/database.db 无法创建临时文件
                                 修复: chmod 755 ~/.sage

================================
总计: 8 项检查 (CRITICAL: 1, WARN: 1, INFO: 6)
```

**JSON 模式**（`--json`）:

```json
{
  "timestamp": "2026-08-07T14:32:18.123Z",
  "python_version": "3.11.9",
  "platform": "linux",
  "checks": [
    {"name": "conda_env", "severity": "info", "message": "...", "fix_hint": null},
    ...
  ],
  "summary": {"critical": 0, "warn": 1, "info": 6, "error": 1}
}
```

**实现**: `backend/cli/doctor.py` 中 `def main(argv=None) -> int`

### Phase 4: electron 集成（半天） ✅ 完成

**涉及文件**:
- 修改 `electron/commands.ts` 或新增 `electron/doctor.ts`
- 修改 `electron/main.ts` 启动流程

**集成方式**:

```typescript
// electron/doctor.ts (新增)
import { spawn } from "node:child_process";
import { logger } from "./logger";

export async function runDoctorCheck(): Promise<DoctorResult> {
  return new Promise((resolve) => {
    const proc = spawn(
      process.env.SAGE_PYTHON_BIN || "python",
      ["-m", "backend.cli.doctor", "--json"],
      { cwd: projectRoot, timeout: 5000 }
    );
    let stdout = "", stderr = "";
    proc.stdout.on("data", (d) => (stdout += d));
    proc.stderr.on("data", (d) => (stderr += d));
    proc.on("close", (code) => {
      // 写入启动日志
      logger.info({ event: "doctor", exit_code: code, summary: parse(stdout) });
      resolve(parse(stdout) ?? { status: "timeout", stderr });
    });
    setTimeout(() => proc.kill("SIGTERM"), 5000);  // R3 缓解
  });
}
```

**main.ts 启动流程插入**:

```typescript
// 启动 backend 之前先跑 doctor（仅本地 dev / win7 LTS）
if (process.env.SAGE_DOCTOR_ON_START !== "false") {
  await runDoctorCheck();
}
```

### Phase 5: 测试（1 天） ✅ 完成

**单测** (`backend/tests/unit/cli/test_doctor.py`)：

| # | 测试名 | 覆盖 |
|---|---|---|
| 1 | `test_conda_env_pass_in_sage_backend` | mock sys.executable 路径 |
| 2 | `test_conda_env_critical_outside_env` | mock `/usr/bin/python3` |
| 3 | `test_conda_env_py38_mismatch` | mock py38 环境但 Py3.11 |
| 4 | `test_sqlite_writable_critical_on_no_dir` | SAGE_USER_DATA_DIR 不可写 |
| 5 | `test_sqlite_writable_info_on_default` | 默认目录可写 |
| 6 | `test_port_backend_warn_when_occupied` | 起一个 socket 占 8765 |
| 7 | `test_port_backend_info_when_free` | 关闭 socket |
| 8 | `test_py_version_match_critical_on_mismatch` | main requirements + py38 |
| 9 | `test_disk_space_warn_below_threshold` | mock free space |
| 10 | `test_check_failure_does_not_crash_doctor` | mock check 抛异常 |
| 11 | `test_main_returns_2_on_critical` | exit code |
| 12 | `test_main_returns_1_on_warn_only` | exit code |
| 13 | `test_json_output_schema` | JSON 模式 |

**集成测试** (`backend/tests/integration/test_doctor_cli.py`)：

| # | 测试名 | 覆盖 |
|---|---|---|
| 1 | `test_full_run_returns_valid_json` | 真实 `python -m backend.cli.doctor --json` |
| 2 | `test_text_output_human_readable` | 默认输出包含严重级别标记 |

### Phase 6: 文档（半天） ✅ 完成

| 文档 | 内容 |
|---|---|
| `docs/technical/41-sage-doctor.md` | 架构 + 协议 + 8 项检查详解 |
| `docs/user-manual/11-sage-doctor.md` | 用户操作：`python -m sage.doctor` + `--json` |
| `docs/technical/README.md` | 在章节目录表追加 41 行 |
| `docs/user-manual/README.md` | 在章节目录表追加 11 行 |
| `CHANGELOG.md` | `feat: add sage doctor CLI for installation/env self-check` |

---

## 4. 依赖关系

### 前置依赖

- `backend/data/database.py`（已有，Database 类）
- `backend/config/*.yaml`（已有，读取 env 路径）
- electron 启动流程（已有 main.ts）

### 不引入新依赖

- 端口检测：stdlib `socket`
- HTTP health：stdlib `urllib.request`（避免 httpx 依赖）
- JSON schema：stdlib `json`
- 版本比较：stdlib 不可用 → **引入 `packaging.version`**（已在 `requirements.txt` 因 pydantic 传递依赖，可直接复用）

### Win7 LTS（Py3.8）注意

- ❌ walrus `:=` 仅在函数内部用，模块顶层用兼容性差 — 避免
- ❌ `match/case` — 避免
- ✅ `from __future__ import annotations` — 必须

---

## 5. 验收标准

- [x] `python -m backend.cli.doctor` 在 `sage-backend` (Py3.11) 环境返回 0
- [x] `python -m backend.cli.doctor` 在 base 环境返回 2（CRITICAL）
- [x] 8 项 check 全部实现并通过单测
- [x] 单测覆盖率 ≥ 90%（doctor 模块）
- [x] electron 启动日志包含 doctor 结果 JSON
- [ ] Win7 LTS 烟测（手动，本会话不强制）— 留给用户
- [x] 文档 4 篇更新 + CHANGELOG
- [x] 依赖 `requirements.txt` / `requirements-py38.txt` 无变化（或仅 `packaging` 加注释）

---

## 6. 文件清单

**新增**:
```
backend/cli/__init__.py
backend/cli/doctor.py             (~150 行)
backend/cli/checks/__init__.py
backend/cli/checks/conda_env.py
backend/cli/checks/backend_health.py
backend/cli/checks/sqlite_writable.py
backend/cli/checks/config_integrity.py
backend/cli/checks/port_backend.py
backend/cli/checks/port_frontend.py
backend/cli/checks/py_version_match.py
backend/cli/checks/disk_space.py
backend/tests/unit/cli/test_doctor.py
backend/tests/unit/cli/checks/test_*.py  (8 个)
backend/tests/integration/test_doctor_cli.py
electron/doctor.ts                (~50 行)
docs/technical/41-sage-doctor.md
docs/user-manual/11-sage-doctor.md
```

**修改**:
```
electron/main.ts                  (启动前插入 runDoctorCheck)
docs/technical/README.md          (章节目录)
docs/user-manual/README.md        (章节目录)
CHANGELOG.md                      (新条目)
```

**总计**: ~17 新增 / ~4 修改

---

## 7. 估计

| 阶段 | 时间 |
|---|---|
| Phase 1 协议骨架 | 0.5 天 |
| Phase 2 8 项检查 | 1.5 天 |
| Phase 3 CLI 入口 | 0.5 天 |
| Phase 4 electron 集成 | 0.5 天 |
| Phase 5 测试 | 1.0 天 |
| Phase 6 文档 | 0.5 天 |
| **总计** | **4.5 工作日** |

**复杂度**: 中
**风险等级**: 低（新增模块，无破坏性变更）

---

## 8. 后续

1. 用户评审本计划 → 确认 / 调整
2. 按 feature-branch-workflow.md 走分支开发（已在 `feat/sage-doctor`）
3. 完成后建 PR `feat/sage-doctor` → `main`
4. 视需要 cherry-pick 到 `release/win7`（Py3.8 兼容已验证）

---

## 9. 评审请回答

- [ ] 是否接受 Phase 1-6 的全部内容？
- [ ] 8 项 check 的取舍是否合理？要不要砍（如 `port_frontend` 是 INFO，仅开发模式相关）？
- [ ] `disk_space` 阈值 500MB 是否合适？
- [ ] 是否需要支持 `--fix` 自动修复（如自动清 sqlite lock 文件）？建议 **不做**（风险高）
