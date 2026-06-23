# Sage 项目 Claude 约束

> 本文件由用户授权写入，作为项目级 Claude Code 运行约束。优先级高于全局默认。

## Python 后端环境（强制）

**项目后端 Python 依赖安装在 conda 虚拟环境 `sage-backend` 中**，
不要使用系统 `python3` / `pip` 安装或运行后端代码，否则会报
`ModuleNotFoundError: No module named 'fastapi'` 等错误。

### 环境路径

```
/home/fz/anaconda3/envs/sage-backend
```

### 激活方式（二选一）

```bash
# 方式 1：直接调用解释器（推荐，用于脚本/CI）
/home/fz/anaconda3/envs/sage-backend/bin/python ...

# 方式 2：先激活再使用（用于交互式 shell）
conda activate sage-backend
```

### 启动后端

```bash
# 端口由 backend/main.py 中 PYTHON_BACKEND_PORT 控制，默认 8765
conda activate sage-backend && cd /home/fz/project/sage && python backend/main.py

# 或前台带 reload（开发用）
conda activate sage-backend && cd /home/fz/project/sage && \
  python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8765
```

健康检查：`curl http://127.0.0.1:8765/health`

### 重新安装依赖（仅限在 sage-backend 环境中）

```bash
/home/fz/anaconda3/envs/sage-backend/bin/pip install -r /home/fz/project/sage/backend/requirements.txt
```

## 前端环境

Node.js 已通过 nvm 安装：`/home/fz/.nvm/versions/node/v25.9.0/bin/node`

```bash
# 安装依赖（如尚未安装）
cd /home/fz/project/sage && npm install

# 开发服务器（端口由 vite.config.ts 锁定为 1420，Tauri 默认）
cd /home/fz/project/sage && npm run dev   # http://localhost:1420

# 生产构建
cd /home/fz/project/sage && npm run build
```

## 端口约定

| 服务           | 端口 | 备注                                  |
| -------------- | ---- | ------------------------------------- |
| 前端 (Vite)    | 1420 | `vite.config.ts` 锁定；Tauri 默认端口 |
| 后端 (FastAPI) | 8765 | `backend/main.py` 中默认值            |
| Tauri 桌面     | —    | Rust 1.96.0+ 已装；构建命令见下      |

## Tauri 桌面构建

Rust 工具链已安装（`/home/fz/.cargo/bin/cargo` 1.96.0+；`rustc` 1.96.0+）。
Tauri 2.1.1 矩阵 + Win7 兼容 fork 详见 `docs/technical/20-win7-tauri-compat.md`。

| 命令 | 用途 |
| --- | --- |
| `npm run tauri dev` | 桌面端开发模式（自动启 Vite + 后端 Python 子进程） |
| `npm run tauri build` | 桌面端生产构建（3 OS 矩阵在 CI 跑，本机只跑当前 OS） |
| `cargo check --manifest-path src-tauri/Cargo.toml` | 桌面端快速语法/类型检查，不打产物 |

## 双分支长期共存策略（强制）

项目采用 **main + release/win7 双分支长期共存**架构,两个分支各自独立演进,**严禁删除或合并 release/win7 分支**。

### 分支定位

| 分支 | 用途 | 技术栈 | EOL |
|------|------|--------|-----|
| `main` | 主开发分支 | Electron 21.4.4 + Python 3.11 + Chromium 106 | 持续维护 |
| `release/win7` | Win7 LTS 维护分支 | Electron 21.4.4 + Python 3.8 + Chromium 106 | **2027-12-13** |

### 核心规则

1. **release/win7 分支不可删除**:此分支服务 Windows 7 SP1 用户,直到 2027-12-13 EOL 后方可归档
2. **不主动合并**:两个分支独立演进,main 的新功能不强制同步到 release/win7;release/win7 的 Win7 特定修复不合并回 main
3. **按需 cherry-pick**:安全补丁或关键 bug 修复可以 cherry-pick 到另一分支,但需手动解决冲突并测试
4. **依赖版本独立**:
   - main 使用 `backend/requirements.txt`(Python 3.11,pydantic 2.x)
   - release/win7 使用 `backend/requirements-py38.txt`(Python 3.8,pydantic 1.x)
   - **不要**将 main 的依赖升级自动同步到 release/win7
5. **CI 隔离**:
   - main 触发 `.github/workflows/ci.yml` 和 `.github/workflows/release.yml`
   - release/win7 触发 `.github/workflows/ci.yml`(py38 测试)和 `.github/workflows/release-win7.yml`
6. **标签规则**:
   - main:普通版本标签 `v*`(如 `v0.2.0`)
   - release/win7:LTS 标签 `v*-lts`(如 `v0.2.1-lts`)

### Python 3.8 环境(仅 release/win7 分支)

在 release/win7 分支上工作时,后端使用 Python 3.8 环境:

```bash
# conda 环境
conda activate sage-backend-py38

# 或直接调用
/home/fz/anaconda3/envs/sage-backend-py38/bin/python
```

**注意**:不要将 Python 3.11 的依赖安装到 py38 环境,也不要在 main 分支上使用 py38 环境。

### Claude 操作约束

- **禁止**执行 `git branch -D release/win7` 或 `git push origin --delete release/win7`
- **禁止**将 release/win7 合并到 main(`git merge release/win7`)
- **禁止**在 main 分支上修改 `backend/requirements-py38.txt`
- **禁止**在 release/win7 分支上修改 `backend/requirements.txt`
- 如需在两个分支间同步代码,**必须**使用 cherry-pick 并手动验证兼容性

## 默认任务规范

- 任何涉及后端 Python 代码的运行/调试/测试，**必须**使用 `sage-backend` conda 环境。
- 启动顺序：先启后端（`python backend/main.py`），再启前端（`npm run dev`）。
- 端口冲突时优先修改后端端口 `PYTHON_BACKEND_PORT`，不要改前端默认端口。
