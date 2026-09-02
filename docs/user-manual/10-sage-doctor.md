# 10. sage doctor CLI

> Sage 的安装/环境级 self-check 命令行工具。本章面向"装好 Sage 后启动有问题"的用户。
> 配合 [06 诊断与日志](./06-diagnostics.md)（运行时日志查看）一起使用。

---

## 10.1 什么是 sage doctor？

`sage doctor` 是 Sage 自带的一键环境体检命令。它运行 13 项安装/环境级检查并报告 CRITICAL / WARN / INFO 三级结果，覆盖最常见的"装好起不来"场景：

- 当前 Python 不在 Sage conda 环境
- 后端 8765 端口被占用（孤儿进程）
- 用户数据目录 (`~/.sage`) 不可写
- 配置文件损坏
- Python 版本与后端声明的 python 约束（requirements / environment.yml）不匹配
- 磁盘剩余空间 < 500MB
- ...

定位耗时从 ~10 分钟/次降到 ~10 秒。

## 10.2 何时使用？

| 场景 | 命令 |
|---|---|
| Win7 LTS 安装后 backend 起不来 | `python -m backend.cli.doctor` |
| 新机器首次跑 `pytest` 报 `ModuleNotFoundError` | `python -m backend.cli.doctor` |
| electron 启动后白屏 | 先看 [06 §6.2 日志文件在哪里](./06-diagnostics.md#62-日志文件在哪里),再跑 doctor |
| DevOps 监控多环境部署状态 | `python -m backend.cli.doctor --json` 接 Prometheus / Zabbix |
| CI 烟测阶段 | `SAGE_DOCTOR_ON_START=false` 跳过 electron 自动 doctor |

> ⚠️ 注意：sage backend 是 Python 后端服务。**所有 doctor 命令必须在 `sage-backend` conda 环境中运行**（`conda activate sage-backend`），否则 `conda_env` 检查会立刻报 CRITICAL。

## 10.3 用法

### 10.3.1 文本模式（默认）

```bash
conda activate sage-backend
cd /home/fz/project/sage   # 或你的 sage 安装目录
python -m backend.cli.doctor
```

输出示例：

```
sage doctor - 2026-08-07 01:17:44
============================================================
[CRITICAL] conda_env              当前 Python 不在 Sage conda 环境: /home/fz/anaconda3/envs/sage-backend/bin/python3.10
             fix: conda activate sage-backend
[    WARN] backend_health         backend 未启动或健康检查失败 (port 8765)
             fix: python backend/main.py
[CRITICAL] sqlite_writable        目录不存在: /home/fz/.sage
             fix: mkdir -p /home/fz/.sage
[CRITICAL] py_version_match       Python 3.10 不满足 environment.yml 约束 python==3.8
             fix: 切到正确的 conda 环境
[    INFO] config_integrity       尚无配置文件（首次安装）
[    INFO] port_backend           8765 端口空闲
[    INFO] port_frontend          1420 端口空闲（启动 npm run dev 会监听此端口）
[    INFO] disk_space             剩余空间 497.0 GB: /home/fz/.sage
============================================================
总计: 13 项检查 (CRITICAL: 3, WARN: 1, INFO: 9)
```

### 10.3.2 JSON 模式（机器可读）

```bash
python -m backend.cli.doctor --json
```

输出示例：

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

适合接入 Prometheus exporter / 监控告警 / CI 烟测。

## 10.4 退出码

| 退出码 | 含义 | 何时触发 |
|---|---|---|
| `0` | OK | 所有检查都是 INFO |
| `1` | WARN | 至少一项 WARN，无 CRITICAL |
| `2` | CRITICAL | 至少一项 CRITICAL |

shell 用法：

```bash
python -m backend.cli.doctor
if [ $? -eq 2 ]; then
    echo "doctor: 严重问题，拒绝启动后端"
    exit 1
fi
```

## 10.5 13 项检查结果速查

### 10.5.1 CRITICAL — 必须修复

| 检查 | 常见原因 | 处理 |
|---|---|---|
| `conda_env` | 当前 Python 在 conda **base** 或系统 Python | `conda activate sage-backend`（Win7 LTS: `sage-backend-py38`） |
| `conda_env` (py38 mismatch) | py38 环境装错 Python 版本 | `conda activate sage-backend-py38` 后确认 `python --version` 是 3.8.x |
| `sqlite_writable` | `~/.sage` 不存在或权限错 | `mkdir -p ~/.sage && chmod 755 ~/.sage` |
| `py_version_match` | 当前 Python 与后端声明不符（win7 为 `environment.yml` 的 `python=3.8`） | 切到正确的 conda 环境（Win7 LTS: `sage-backend-py38`） |

### 10.5.2 WARN — 建议修复

| 检查 | 常见原因 | 处理 |
|---|---|---|
| `backend_health` | backend 进程未起 / 端口不对 | 启动后端：`python backend/main.py`（dev）; 桌面端看 [01 桌面端安装与启动](./01-desktop.md) |
| `config_integrity` | `~/.sage/config/*.json` 被手动改坏 | 删除损坏文件，下次启动会重建 |
| `port_backend` | 8765 端口被孤儿 python 占用 | `lsof -i :8765` 找到 PID 后 `kill <PID>`；桌面端可重启 Electron 让它自己清理 |
| `disk_space` | 磁盘剩余 < 500MB | 清理 `~/.sage/sessions/*.jsonl` 或 `~/.sage/audit/` |

### 10.5.3 INFO — 仅信息

| 检查 | 说明 |
|---|---|
| `config_integrity` (空) | 首次安装，无配置文件 — 正常 |
| `port_backend` / `port_frontend` | 端口空闲 — 正常 |
| `py_version_match` | 满足后端声明的约束 — 正常 |
| `disk_space` | 磁盘充足 — 正常 |
| `llm_config` (部分/全部有 `apiKey`) | 设置页已配置 endpoint — 正常 |
| `mcp_servers` (无配置) | 暂未启用 MCP server — 正常 |
| `heavy_deps` | 三个重依赖均可 import — 正常 |
| `log_dir_size` (< 500MB) | 日志目录未膨胀 — 正常 |
| `frontend_dist` (dev 模式) | 未检测到 `dist/` 与 `dist-electron/` — 正常(走 vite dev server) |

## 10.6 Electron 自动 doctor

每次桌面端启动时，Electron 会在 `app.whenReady()` 之后、backend spawn 之前自动跑一次 doctor（**默认开启**）：

- 调用 `python -m backend.cli.doctor --json`
- 5 秒硬超时（健康环境 < 200ms）
- 结果写入当天 NDJSON 启动日志
- **永不阻塞启动** — 即使 doctor 报 CRITICAL，应用仍正常弹出

### 10.6.1 查看 doctor 结果

1. 打开「日志目录」（详见 [06 §6.2](./06-diagnostics.md#62-日志文件在哪里)）
2. 打开当天 `.ndjson` 文件
3. 搜索：

   ```bash
   grep '"main: doctor check complete"' ~/AppData/Roaming/sage/logs/sage-2026-08-07.ndjson
   ```

4. 对照上方 [§10.5 13 项检查结果速查](#105-13-项检查结果速查) 找 root cause

### 10.6.2 跳过自动 doctor

仅在以下场景需要跳过：

- CI 烟测（没有 sage-backend conda 环境）
- 排查 doctor 自身 bug

```bash
# canonical launch path — see .claude/skills/run-desktop/SKILL.md
# electron:dev 现在带 --no-sandbox，sandbox 环境两种方式都可以
SAGE_DOCTOR_ON_START=false npm run electron:dev
```

## 10.7 反馈问题

跑完 doctor 还是不知道怎么办？把 doctor 输出（文本或 JSON 都行）附在 GitHub issue：

1. 复现问题
2. 跑 `python -m backend.cli.doctor --json > doctor-output.json`
3. 在 issue 中描述：
   - 操作系统版本（Win7 SP1 x64 / Win11 / Ubuntu 22.04 等）
   - 你是 **conda 环境** 还是 **NSIS 安装包** 用户
   - doctor 的 CRITICAL / WARN 项
4. 把 `doctor-output.json` 附在 issue 中

详见 [06 §6.4 如何反馈问题？](./06-diagnostics.md#64-如何反馈问题)
