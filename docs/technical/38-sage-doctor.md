# 38. sage doctor — 安装/环境级 self-check CLI

> **最后更新**: 2026-08-08
> **适用版本**: Sage release/win7（本章为 main 41-sage-doctor.md 的 win7 变体，章节号随 win7 文档序列顺延）
> **关联章节**: [20 Electron 21 桌面壳](./20-electron.md)、[29 Electron 桌面日志](./29-electron-logging.md)
> **互补文档**: [`../user-manual/10-sage-doctor.md`](../user-manual/10-sage-doctor.md)（用户视角）；[`../user-manual/06-diagnostics.md`](../user-manual/06-diagnostics.md)（运行时 UI 诊断面板，本章是其 CLI 前置对应物）

---

## 38.1 背景与目标

### 问题

Sage 安装/部署路径上有 8 类"启动失败"反复出现：

1. 用户在 conda **base** 环境跑 `python -m pytest`，报 `ModuleNotFoundError: No module named 'fastapi'`
2. Win7 LTS 用户安装到 `C:\Program Files\Sage\` 后 4-5 秒崩（`PermissionError [WinError 5]`）
3. electron 启动后白屏 — 实际是 8765 端口被上一次崩溃遗留的孤儿 backend 进程占用
4. `SAGE_USER_DATA_DIR` 指向只读目录（系统盘 Program Files 下）导致 SQLite 写不进去
5. `~/.sage/config/*.json` 被人手动编辑坏掉，下次启动 schema 校验失败
6. Win7 LTS 误装了 main 分支的 `requirements.txt`（Py3.11 + pydantic v2），py38 + pydantic v1 跑不起来
7. 磁盘剩余 < 500MB，session 历史写入失败但没人察觉
8. dev 模式下 1420 端口被其他进程占用，Vite 启动失败但不报错原因

这些场景定位耗时 ~10 分钟/次，doctor CLI 把它们压缩到 ~10 秒。

### 目标

- 一个 stdlib-only 的 Python CLI：`python -m backend.cli.doctor`
- 8 项检查按 **CRITICAL / WARN / INFO** 三级分级
- 双输出模式：人类可读文本 + `--json` 机器可读
- 退出码 0/1/2 直接对接 shell / CI / 监控告警
- electron 启动前自动跑，结果写入 NDJSON 启动日志（**fail-open**，永不阻塞启动）

---

## 38.2 架构

### 38.2.1 模块结构

```
backend/cli/
├── __init__.py
├── doctor.py             # 协议骨架 + CLI 入口 + 文本/JSON 格式化
└── checks/
    ├── __init__.py
    ├── conda_env.py       # 检查 1
    ├── backend_health.py  # 检查 2
    ├── sqlite_writable.py # 检查 3
    ├── config_integrity.py# 检查 4
    ├── port_backend.py    # 检查 5
    ├── port_frontend.py   # 检查 6
    ├── py_version_match.py# 检查 7
    └── disk_space.py      # 检查 8
```

### 38.2.2 Check Protocol

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
    name: str
    severity: Severity
    message: str
    fix_hint: Optional[str] = None


@runtime_checkable
class Check(Protocol):
    name: str
    description: str

    def run(self) -> CheckResult: ...


ALL_CHECKS: list = []


def register(cls: type) -> type:
    """类装饰器：把 Check 类加入 ALL_CHECKS。"""
    ALL_CHECKS.append(cls)
    return cls
```

**关键设计**：

- `@runtime_checkable` Protocol：单测里可用 `isinstance(obj, Check)` 验证鸭子类型
- `frozen=True` dataclass：不可变结果，避免下游误改
- `Severity(str, Enum)`：str 混合让 `json.dumps` 直接序列化为字符串
- `@register` 装饰器：每项 check 模块 import 时自动注册到 `ALL_CHECKS`，避免硬编码列表
- `main()` 用 `importlib.import_module` 动态导入子模块，触发注册（避免静态 import 循环依赖）

### 38.2.3 Fail-open 兜底

```python
# backend/cli/doctor.py
def _run_one(check_cls: type) -> CheckResult:
    instance = check_cls()
    try:
        return instance.run()
    except Exception as exc:
        return CheckResult(
            name=getattr(instance, "name", check_cls.__name__),
            severity=Severity.WARN,
            message="check 自身异常: {}: {}".format(exc.__class__.__name__, exc),
            fix_hint="请检查该 check 实现,或上报 issue",
        )
```

任意 check 抛异常 → 降级为该 check 的 WARN + "check 自身异常" 提示，doctor 整体继续跑。

### 38.2.4 退出码

| 退出码 | 含义 | 触发条件 |
|---|---|---|
| 0 | OK | 所有 check 都是 INFO / 无问题 |
| 1 | WARN | 至少一项 WARN，无 CRITICAL |
| 2 | CRITICAL | 至少一项 CRITICAL |

实现：

```python
def _exit_code(results: list) -> int:
    has_critical = any(r.severity == Severity.CRITICAL for r in results)
    if has_critical:
        return 2
    has_warn = any(r.severity == Severity.WARN for r in results)
    if has_warn:
        return 1
    return 0
```

---

## 38.3 8 项检查详解

### 38.3.1 `conda_env` — 当前 Python 是否在 Sage conda 环境

**严重级别**: CRITICAL（路径不匹配）/ INFO（匹配）/ CRITICAL（py38 环境装错 Python）

**检测逻辑**:

- 读 `sys.executable`，resolve 成绝对路径
- 与白名单路径前缀比对（**长路径在前**避免被短路径先匹配）：
  - `/anaconda3/envs/sage-backend-py38`（Win7 LTS）
  - `/anaconda3/envs/sage-backend`（main）
  - `/opt/conda/envs/sage-backend`（Linux conda 默认安装路径）
- 匹配到 `sage-backend-py38` 时校验 Python 版本必须是 3.8（防 main 用户误装 py38 环境）

**fix_hint**:

- 路径不在白名单 → `conda activate sage-backend`
- py38 环境装错 Python → `conda activate sage-backend-py38`

### 38.3.2 `backend_health` — FastAPI /health 端点连通性

**严重级别**: WARN（端点不通或非 200）

**检测逻辑**:

- 读 `PYTHON_BACKEND_PORT` env（默认 8765），curl `http://127.0.0.1:${port}/health`（1 秒超时）
- 期望返回 JSON `{"status": "ok"}`
- 任何异常（连接拒绝、超时、HTTP 错误、非 200、非 JSON、status ≠ ok）→ WARN

**fix_hint**: `python backend/main.py`

**注意**: 这是 **CRITICAL→WARN** 的设计 — backend 没起不应该让 doctor 退出码变成 2（因为用户可能就是要 doctor 帮忙"诊断为什么 backend 起不来"）。CRITICAL 会留给真正需要修的环境问题（conda 错配、磁盘满）。

### 38.3.3 `sqlite_writable` — `SAGE_USER_DATA_DIR` 目录可写性

**严重级别**: CRITICAL（不存在 / 不是目录 / 不可写）/ INFO（可写）

**检测逻辑**:

- 解析路径：`SAGE_USER_DATA_DIR` env → 否则 `~/.sage`
- 不存在 → CRITICAL
- 存在但不是目录 → CRITICAL
- 存在但是用 `tempfile.NamedTemporaryFile(dir=path)` 创建+关闭临时文件测可写性
  - `PermissionError` → CRITICAL
  - `OSError` → CRITICAL
  - 成功 → INFO

**fix_hint**: `mkdir -p <path>` 或 `chmod 755 <path>`

**Win7 LTS 关键性**: 这是 NSIS 安装到 `C:\Program Files\Sage\` 的核心防线 — 若 backend 写 `themes/` / `scheduled_tasks.json` / `audit/audit.jsonl` / `logs/` 到程序目录（非系统管理员）必失败。

### 38.3.4 `config_integrity` — `~/.sage/config/*.json` JSON 合法 + 必填字段

**严重级别**: WARN（损坏或缺字段）/ INFO（无配置文件或全合法）

**检测逻辑**:

- 扫描 `<user_data_dir>/config/*.json`
- 每文件：`json.load` + 校验必填字段 `["version"]`
- 任意文件 `JSONDecodeError` / `OSError` / 缺字段 → 列入 broken 列表
- broken 非空 → WARN 报告所有坏文件 + 原因

**fix_hint**: `删除该文件，下次启动会重建`

### 38.3.5 `port_backend` — 8765 端口占用（孤儿 backend）

**严重级别**: WARN（占用）/ INFO（空闲）

**检测逻辑**:

- `socket.bind(("127.0.0.1", 8765))` 试探
- `OSError`（端口已被占用）→ WARN
- 成功 → INFO（绑后立刻 close）

**fix_hint**: `lsof -i :8765 && kill <PID>`

**典型场景**: electron 崩溃但 python 子进程未被回收，下次启动时 backend 进程因 8765 占用而起不来 → 白屏。

### 38.3.6 `port_frontend` — 1420 端口占用（Vite dev server）

**严重级别**: INFO（无论占用或空闲）

**检测逻辑**: 同上，端口 = 1420。

**注意**: 这是 **INFO 级别**，不是 WARN — dev 模式启动失败用户能立刻看到（Vite 终端输出），不需要 doctor 报警。

### 38.3.7 `py_version_match` — Python 版本 vs `backend/requirements.txt`

**严重级别**: CRITICAL（不满足约束）/ INFO（未声明或满足）

**检测逻辑**:

- 解析 `backend/requirements-py38.txt`（win7 分支优先；不存在则回退 `requirements.txt`），正则匹配 `python(>=|<=|==|~=|!=|>|<)<version>`
- 与当前 `(sys.version_info.major, sys.version_info.minor)` 比较
- 算符支持：`>=` / `<=` / `==` / `~=` / `!=` / `>` / `<`
- 未声明约束 → INFO（"未声明 python 版本约束"）
- 满足 → INFO（"Python X.Y 满足 ... 约束"）
- 不满足 → CRITICAL

**fix_hint**: `切到正确的 conda 环境`

**Win7 LTS 关键性**: py38 环境是 win7 分支的契约——若 py38 环境被装进 Py3.11 解释器，此 check 在声明约束后立即暴露。当前 win7 的 `requirements-py38.txt` 尚未声明 python 约束（pip 会把裸 `python==3.8` 当 PyPI 包解析，故不能写进 requirements 文件），返回 INFO 属预期。

### 38.3.8 `disk_space` — `SAGE_USER_DATA_DIR` 所在分区剩余空间

**严重级别**: WARN（< 500MB）/ INFO（充足）

**检测逻辑**:

- `shutil.disk_usage(<user_data_dir>)` 读分区用量
- 路径不存在时退到 `path.parent`
- 阈值：`WARN_THRESHOLD_BYTES = 500 * 1024 * 1024`（500 MB）
- 低于阈值 → WARN
- 充足 → INFO（输出人类可读字节数，如 "剩余空间 497.0 GB: /home/fz/.sage"）

**fix_hint**: `清理 <path> 或扩展磁盘`

---

## 38.4 输出格式

### 38.4.1 文本模式（默认）

```
sage doctor - 2026-08-07 01:17:44
============================================================
[CRITICAL] conda_env              当前 Python 不在 Sage conda 环境: /home/fz/anaconda3/envs/sage-backend/bin/python3.10
             fix: conda activate sage-backend
[    WARN] backend_health         backend 未启动或健康检查失败 (port 8765)
             fix: python backend/main.py
[CRITICAL] sqlite_writable        目录不存在: /home/fz/.sage
             fix: mkdir -p /home/fz/.sage
[    INFO] config_integrity       尚无配置文件（首次安装）
[    INFO] port_backend           8765 端口空闲
[    INFO] port_frontend          1420 端口空闲（启动 npm run dev 会监听此端口）
[    INFO] py_version_match       backend/requirements.txt 未声明 python 版本约束
[    INFO] disk_space             剩余空间 497.0 GB: /home/fz/.sage
============================================================
总计: 8 项检查 (CRITICAL: 2, WARN: 1, INFO: 5)
```

### 38.4.2 JSON 模式（`--json`）

```json
{
  "timestamp": "2026-08-07T01:17:47.235078+00:00",
  "python_version": "3.10.20",
  "platform": "linux",
  "checks": [
    {
      "name": "conda_env",
      "severity": "critical",
      "message": "当前 Python 不在 Sage conda 环境: /home/fz/anaconda3/envs/sage-backend/bin/python3.10",
      "fix_hint": "conda activate sage-backend"
    }
  ],
  "summary": {"critical": 2, "warn": 1, "info": 5}
}
```

字段语义：

| 字段 | 含义 |
|---|---|
| `timestamp` | UTC ISO 8601 |
| `python_version` | `major.minor.micro` |
| `platform` | `sys.platform` 小写（`linux` / `darwin` / `win32`） |
| `checks[].name` | check 注册名（snake_case） |
| `checks[].severity` | `critical` / `warn` / `info` |
| `checks[].message` | 人类可读 |
| `checks[].fix_hint` | 可选，修复建议 |
| `summary` | 严重度分布计数 |

---

## 38.5 Electron 集成

### 38.5.1 入口：`electron/doctor.ts`

```typescript
// electron/doctor.ts (核心片段)
export async function runDoctorCheck(
  pythonBin: string,
  projectRoot: string,
  timeoutMs: number = 5000,
): Promise<DoctorSummary> {
  const proc = spawn(pythonBin, ['-m', 'backend.cli.doctor', '--json'], {
    cwd: projectRoot,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });

  // 收集 stdout / stderr
  let stdout = '';
  let stderr = '';
  proc.stdout?.on('data', (b: Buffer) => { stdout += b.toString('utf-8'); });
  proc.stderr?.on('data', (b: Buffer) => { stderr += b.toString('utf-8'); });

  // 5 秒硬超时：SIGTERM → 500ms 后 SIGKILL
  const killTimer = setTimeout(() => {
    try { proc.kill('SIGTERM'); } catch { /* ignore */ }
    setTimeout(() => {
      try { proc.kill('SIGKILL'); } catch { /* ignore */ }
    }, 500).unref();
  }, timeoutMs);
  killTimer.unref();

  // 映射 Python exit code → DoctorStatus
  // 0=ok / 1=warn / 2=critical / 其他=error
  // 超时 → status: 'timeout'
  // spawn 错误 → status: 'error'
}
```

**关键设计**:

- 永远不抛异常 — 所有失败模式（spawn 错、超时、非零退出码、JSON 解析失败）折叠成 `DoctorSummary.status` 字段
- 5 秒硬超时（健康环境 doctor < 200ms，超时只在 broken-installer 场景触发）
- SIGTERM → 500ms grace → SIGKILL 双保险（Win7 上 SIGTERM 可被忽略）
- `killTimer.unref()` 保证不阻止 Node 进程退出

### 38.5.2 启动流程注入：`electron/main.ts`

```typescript
// electron/main.ts (line 812-834)
app.whenReady().then(async () => {
  cleanupOlderThan(7);
  // Phase 4: pre-launch self-check (skippable via SAGE_DOCTOR_ON_START=false for CI).
  // fail-open by design: doctor never blocks the app from launching
  if (process.env.SAGE_DOCTOR_ON_START !== 'false') {
    try {
      const doctorSummary = await runDoctorCheck(
        process.env.SAGE_PYTHON ?? 'python',
        process.cwd(),
      );
      logger.info('main: doctor check complete', doctorSummary);
      if (doctorSummary.status === 'critical') {
        logger.warn('main: doctor reported CRITICAL — user may see degraded experience', {
          summary: doctorSummary.summary,
        });
      }
    } catch (err) {
      logger.warn('main: doctor check threw', { error: String(err) });
    }
  }
  registerIpcHandlers();
  // ...
});
```

**Fail-open 三层**:

1. `runDoctorCheck` 内部 try/catch 全部 → 永不抛异常
2. `main.ts` 外层 try/catch 兜底（理论上不可达）
3. **doctor 永远不阻塞启动** — 即使 CRITICAL 也只是 `logger.warn`，不弹窗、不退出

**环境变量**:

| 变量 | 作用 |
|---|---|
| `SAGE_DOCTOR_ON_START=false` | 跳过 doctor（CI / 轻量 smoke 用） |
| `SAGE_PYTHON=<bin>` | 自定义 Python 解释器（默认 `python`） |

### 38.5.3 用户如何查看 doctor 结果

doctor 跑完后通过 `logger.info('main: doctor check complete', doctorSummary)` 写入 NDJSON 启动日志（详见 [29 Electron 桌面日志](./29-electron-logging.md)）。

用户路径：

1. 启动失败 / 白屏 → 「打开日志目录」（[06 诊断与日志](../user-manual/06-diagnostics.md) §6.2）
2. 打开当天 `.ndjson` 文件
3. `grep '"main: doctor check complete"'` 找到 doctor 结果
4. 对照 [§41.3 8 项检查详解](#413-8-项检查详解) 找到 root cause

---

## 38.6 测试覆盖

### 38.6.1 单测

| 文件 | 覆盖项 |
|---|---|
| `backend/tests/unit/cli/test_doctor.py` | Protocol 注册 / Severity 序列化 / 文本格式化 / JSON 格式化 / 退出码 / `_run_one` 异常兜底 / `--json` CLI 参数 |
| `backend/tests/unit/cli/checks/test_conda_env.py` | sage-backend 路径 / py38 路径 / base 环境 / py38 误装 Py3.11 / Linux conda 路径 |
| `backend/tests/unit/cli/checks/test_backend_health.py` | 200 + status=ok / 200 + status≠ok / 503 / 连接拒绝 / 超时 / 非 JSON |
| `backend/tests/unit/cli/checks/test_sqlite_writable.py` | 默认目录可写 / 目录不存在 / 非目录 / PermissionError / OSError |
| `backend/tests/unit/cli/checks/test_config_integrity.py` | 无 config 目录 / 空目录 / 单文件合法 / 单文件缺字段 / JSON 损坏 |
| `backend/tests/unit/cli/checks/test_port_backend.py` | 端口空闲 / 端口占用 |
| `backend/tests/unit/cli/checks/test_port_frontend.py` | 同上 |
| `backend/tests/unit/cli/checks/test_py_version_match.py` | 未声明 / `>=` 满足 / `>=` 不满足 / `==` / `~=` / 多版本号 / 注释行 / `OSError` |
| `backend/tests/unit/cli/checks/test_disk_space.py` | 充足 / < 500MB / 路径不存在 / `OSError` |

**总计**: **120 个测试全绿**（unit + integration）

### 38.6.2 集成测试

`backend/tests/integration/test_doctor_cli.py`:

- `test_full_run_returns_valid_json` — 子进程跑 `python -m backend.cli.doctor --json`，断言 schema
- `test_text_output_human_readable` — 默认输出含严重级别标记与 fix 行

---

## 38.7 Win7 LTS 兼容

`backend/cli/doctor.py` 与 8 个 check 模块都对 Py3.8 友好：

- ✅ 所有模块顶层 `from __future__ import annotations`（PEP 563 惰性求值）
- ✅ 避免 walrus `:=` 在模块顶层（仅函数内部使用）
- ✅ 避免 `match/case`（3.10+ 语法）
- ✅ 字符串格式化用 `.format()` 而非 f-string（在某些 Py3.8 + linter 组合下更稳）
- ✅ JSON schema 在 Py3.8 / Py3.11 输出完全一致 — `electron/doctor.ts` 不分支判断 Python 版本

`release/win7` 移植时做了 **2 处适配**（main 版本在这两点上在 Windows 有误报/失准风险）：

1. **`conda_env` 跨平台路径匹配** — main 版硬编码 `/anaconda3/envs/...` 前缀，在 Windows 上永远不会匹配 `C:\Users\x\anaconda3\envs\sage-backend-py38\python.exe`，会把合法安装误报为 CRITICAL。win7 版改为按 `envs/<name>` 路径段识别（`_conda_env_name`），Linux/Windows 均正确。新增 2 个 Windows 路径单测（`test_conda_env.py`）。
2. **`py_version_match` 优先 `requirements-py38.txt`** — main 版固定读 `requirements.txt`；win7 的生效依赖规范是 `requirements-py38.txt`。win7 版优先读 `-py38` 变体（不存在时回退 `requirements.txt`）。新增 `test_prefers_requirements_py38` 单测。

`electron/main.ts` 的 doctor 注入（Phase 4）与 main 版逻辑一致（`SAGE_DOCTOR_ON_START=false` 跳过、5s 硬超时、fail-open），无适配差异。

---

## 38.8 与 `docs/user-manual/06-diagnostics.md` 的关系

| 维度 | sage doctor（本章节） | 06 诊断面板（运行时 UI） |
|---|---|---|
| **运行时机** | 启动前 / 手动 CLI | 应用运行中 |
| **触发方式** | `python -m backend.cli.doctor` 或 electron 自动 | 设置页 → 诊断与日志 卡片 |
| **覆盖** | 8 项 安装/环境级 self-check | 日志查看 / 清理 / 反馈 |
| **输出** | 退出码 + 文本/JSON | 按钮 + 资源管理器 |
| **用户场景** | 装好启动不了 / 装错环境 / 端口冲突 | 应用运行中想看日志 |

**两者互补**: doctor 诊断"装好能不能跑起来"，06 章节诊断"跑起来后日志在哪"。

---

## 38.9 相关文件

| 文件 | 角色 |
|---|---|
| `backend/cli/doctor.py` | 协议骨架 + CLI 入口（229 行） |
| `backend/cli/checks/*.py` | 8 项检查实现（共 8 文件 ~450 行） |
| `backend/tests/unit/cli/` | 单测（120 passed） |
| `backend/tests/integration/test_doctor_cli.py` | 集成测试 |
| `electron/doctor.ts` | Electron 启动前调用器（184 行） |
| `electron/main.ts` app.whenReady() 内 Phase 4 块 | 启动流程注入点（win7 行号随分支演进，约在 cleanupOlderThan 之后） |

---

## 38.10 后续可考虑（非本次范围）

- 加 `port_mcp` check：检测 MCP server pool 的端口（[34 MCP 多服务器管理](./34-mcp-multi-server.md)）
- 加 `data_migration` check：检测 `pragma user_version` 与最新 schema 的差
- doctor 集成到 CI 烟测阶段（`SAGE_DOCTOR_ON_START=false` 已留口子）
- Win7 LTS 真机烟测：手动跑 `python -m backend.cli.doctor` 在打包安装后的机器上
