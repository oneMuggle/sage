# Web Fallback 打包落地（SageWeb 安装版启动器）

> 日期：2026-11-22
> 分支：`feat/web-fallback-packaging`（基于 `main` @ `fe2b1a54e`）
> 状态：进行中

## 1. 背景与目标

Web Fallback（PR #3042 / win7 #3050）当初只落地了**源码级**链路：

- 后端 web 模式：`backend/main.py` 在 `SAGE_WEB_MODE=1` 时把 `dist-web/` 挂到 `/`；
  `backend/api/local_auth.py` 支持 `?token=` 鉴权 + 静态路径免鉴权。
- 前端 web 构建：`npm run build:web` → `dist-web/`（vite `--mode web`）。
- 启动脚本：`scripts/sage-web.bat`。

但这个 `sage-web.bat` 是**面向源码目录**的：它 `where python` 找系统 Python、要求
当前目录有 `backend\main.py`、缺 `dist-web` 时 `call npm run build:web`。安装包里
没有 Python on PATH、没有 node/npm、没有源码，`dist-web/` 与脚本本身也没进
`electron-builder` 的 `extraFiles/extraResources`。因此 **alpha.84 的 win7 安装包没有任何
可用的浏览器模式入口**——后端能力在包里，但前端产物和启动器缺失。

**目标**：让安装包（main + release/win7）自带"Electron 被安全软件拦截时用浏览器打开"的
可用降级入口：

1. 打包含 web 前端产物 `dist-web/`。
2. 提供使用**内置 Python** 的安装版启动器（不依赖系统 Python / node / curl）。
3. 安装后在开始菜单出现「Sage 网页模式」快捷方式。
4. 让开发/源码路径与安装版共用同一套启动逻辑，消除重复与 Win7 无 curl 的隐患。

## 2. 涉及的文件与模块

| 文件 | 变更 |
| --- | --- |
| `backend/cli/web.py` | **新增**。跨平台 web 启动器逻辑（mint token / 选端口 / 起 uvicorn / 健康后开浏览器）。 |
| `backend/tests/test_cli_web.py` | **新增**。纯函数单测（端口选择、URL 构造、环境准备、dist 缺失快速失败）。 |
| `resources/SageWeb.cmd` | **新增**（安装根目录，`extraFiles`）。薄封装，复用 `SageDoctor.cmd` 的打包态 env 约定。 |
| `electron-builder.yml` | `extraFiles` 加 `SageWeb.cmd`；`extraResources` 加 `dist-web → dist-web`。 |
| `build/installer.nsh` | `customInstall` 建「Sage 网页模式」快捷方式；`customUnInstall` 清理。 |
| `.github/workflows/release-win7.yml` | 打包前新增 `npm run build:web`。 |
| `.github/workflows/release.yml` | 同上（main 的 linux/win 打包同一 job）。 |
| `.github/workflows/ci.yml` | 前端 job 增加 `npm run build:web` 防回归。 |
| `scripts/sage-web.bat` | 改为调用 `python -m backend.cli.web`（去 curl / `--web-mode` 无效参数），dev 与安装版共用逻辑。 |
| `docs/technical/152-web-fallback-mode.md` | 补「安装版启动器 / 打包布局 / 端口回退」。 |
| `docs/user-manual/49-web-fallback.md` | 「双击 `scripts\\sage-web.bat`」改为「开始菜单 → Sage 网页模式 / 双击安装目录 `SageWeb.cmd`」。 |

## 3. 技术方案

### 3.1 打包布局

```
<install>/
├─ Sage.exe
├─ SageDoctor.cmd
├─ SageWeb.cmd                      # extraFiles，新增
└─ resources/
   ├─ python/python.exe             # 内置运行时（已有）
   ├─ backend/                      # 已有（保护构建下为 .pyc，main.py 除外）
   │  └─ cli/web.pyc                # 新增模块（-b 模式编译为同目录 .pyc）
   ├─ dist-web/                     # extraResources，新增（index.html + assets）
   ├─ models/  docs/                # 已有
   └─ ...
```

后端 `_WEB_DIST_PATH` 默认解析为 `Path(backend/main.py).parent.parent / "dist-web"`
即 `<install>/resources/dist-web`，与 `extraResources: to: "dist-web"` 天然对齐；
启动器额外显式设 `SAGE_WEB_DIST_PATH=%ROOT%resources\dist-web` 作为双保险。

### 3.2 启动器分层

- **`resources/SageWeb.cmd`（安装版，薄）**
  - 仿 `SageDoctor.cmd`：`ROOT=%~dp0`、`SAGE_IS_PACKAGED=1`、`SAGE_USER_DATA_DIR`、
    `SAGE_DB_PATH`、`PYTHONPATH=%ROOT%resources\backend;%ROOT%resources\sage-core`。
  - 设 `SAGE_WEB_MODE=1`、`SAGE_WEB_DIST_PATH`、`SAGE_BUNDLED_MODELS_DIR`、`SAGE_DOCS_DIR`、
    `PYTHON_BACKEND_PORT`（沿用外部值，默认 8765）。
  - 优先 `resources\python\python.exe`；缺失时回退 PATH 上的 `python`（dev/异常安装诊断）。
  - 调用 `python -m backend.cli.web`；非 0 退出 `pause`。
- **`backend/cli/web.py`（逻辑，跨平台、可测）**
  - `prepare_runtime_env(environ)`：设 `SAGE_WEB_MODE=1`、`SAGE_LOCAL_AUTH_TOKEN`
    （缺省 `secrets.token_urlsafe(32)`）、`PYTHON_BACKEND_PORT`、`BACKEND_URL`，返回 `(port, token)`。
  - `pick_port(preferred, is_free=...)`：首选端口被占用则向后探测（默认 8765→8775），
    避免与正在运行的桌面后端撞端口。
  - `build_web_url(port, token)`：`http://127.0.0.1:<port>/?token=<token>`。
  - `resolve_dist_path()`：优先 `SAGE_WEB_DIST_PATH`，否则仓库/打包默认；**缺失即打印指引并退出 2**
    （不要起一个没有 UI 的后端）。
  - `main()`：准备 env → `from backend.main import app`（env 先在 import 前就位）→
    起 daemon 线程轮询 `/health` 后用 `webbrowser.open(url)` 打开浏览器（失败则打印 URL）→
    `uvicorn.run(app, host="127.0.0.1", port=port, log_config=None)`。
  - 用 Python `urllib` 轮询，**不依赖 curl**（Win7 原生无 curl）。

### 3.3 保护构建兼容

`scripts/bundle-python.ps1` 用 `compileall -b`（legacy 布局：`web.pyc` 与 `web.py` 同级），
随后剥离除 `main.py` 外的 `.py`。`python -m backend.cli.web` 可从 `__init__.pyc`/`web.pyc`
正常导入，无需改动打包脚本。

### 3.4 CI 打包顺序

`npm run electron:build`（=`build` + `build:electron`，输出 `dist/`）之后、`electron-builder`
之前执行 `npm run build:web`（输出 `dist-web/`），确保 `extraResources` 取到产物。

## 4. 实施步骤

- [x] M1 写失败测试：`backend/tests/test_cli_web.py`（URL/端口/env/dist 解析）。
- [x] M2 实现 `backend/cli/web.py` 至测试通过；`ruff` + `pytest` 绿。
- [x] M3 新增 `resources/SageWeb.cmd`；`electron-builder.yml` 加 `extraFiles`/`extraResources`。
- [x] M4 `build/installer.nsh` 加「Sage 网页模式」快捷方式与卸载清理。
- [x] M5 三个 workflow（`release-win7.yml` / `release.yml` / `ci.yml`）加 `npm run build:web`。
- [x] M6 重构 `scripts/sage-web.bat` 复用 `backend.cli.web`。
- [x] M7 更新技术文档 152 / 用户手册 49。
- [x] M8 本地验证：`pytest test_cli_web`、`npm run build:web`、`npm run lint`/`typecheck`、
      `node scripts/architecture-check.mjs`、`npx vitest run tests/packaging/`（如产物在）。
- [ ] M9（后续 PR）cherry-pick 到 `release/win7`，按 win7 文档编号（技术 154）适配并重跑 py38 检查。

## 5. 风险评估与依赖

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 安装包 +~10MB（`dist-web` 与 `dist` 近似） | 体积增大 | 可接受；`dist-web` 无 sourcemap。bundle 门禁只测 `dist/assets`，不受影响。 |
| 端口 8765 被占用 | 启动失败 | `pick_port` 自动回退到空闲端口，URL 用实际端口。 |
| Win7 无 curl | 健康探测失败 | 用内置 Python `urllib` 轮询。 |
| `webbrowser.open` 在嵌入运行时打不开 | 用户看不到页面 | 失败时打印可复制 URL；用户可手动粘贴。 |
| 浏览器模式仍受安全软件限制 | 降级失败 | 本质是绕过 Electron 二进制拦截；python.exe 通常放行。文档说明。 |
| 保护构建 `.pyc` 导致 `-m` 失败 | 安装版无法启动 | 已确认 `compileall -b` legacy 布局 + `-m` 可导入；本地用 pyc-only 冒烟验证。 |
| win7 分支持久化 | 功能不对齐 | M9 单独 cherry-pick PR，`electron-builder.yml`/workflow 需按分支适配。 |

依赖：`dist-web` 构建依赖既有 `vite.config.ts --mode web`（已上线）；无新增三方依赖。
