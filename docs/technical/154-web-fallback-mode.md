# Web Fallback Mode（网页回退模式）

> Win7 用户在 Electron 21 无法升级时，可通过浏览器访问 Sage 核心功能。

---

## 1. 设计目标

| 项         | 值                                                                              |
| ---------- | ------------------------------------------------------------------------------- |
| 触发场景   | Win7 SP1 用户 Electron 21 CVE 无法修复时的降级通道                              |
| 技术栈     | 后端 FastAPI + 前端 Vite build（`dist-web/`）                                   |
| 认证方式   | `SAGE_LOCAL_AUTH_TOKEN`（与桌面端相同）；Web 支持 URL param `?token=xxx`        |
| 浏览器要求 | Chrome 109+ / Firefox ESR 102+（Win7 最后支持的版本）                           |
| 范围       | Phase 1 MVP：聊天/会话核心功能；桌面端专属功能（文件选择器、Office 导入等）降级 |

## 2. 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                        Browser                               │
│  http://127.0.0.1:8765/?token=<random-token>                │
│  token → localStorage['sage_auth_token']（index.html 引导）    │
└────────────────────┬────────────────────────────────────────┘
                     │ 同源 HTTP：Authorization: Bearer <token>
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                   FastAPI Backend                             │
│                                                              │
│  ┌──────────────────┐    ┌───────────────────────────────┐  │
│  │  StaticFiles     │    │  /api/v1/* (REST endpoints)   │  │
│  │  mount "/"       │    │  require_local_auth           │  │
│  │  dist-web/       │    │  (Bearer or ?token=)          │  │
│  └──────────────────┘    └───────────────────────────────┘  │
│                                                              │
│  LocalAuthMiddleware:                                        │
│    - 非 /api/ 路径（dist-web 产物 + SPA 路由）→ public        │
│    - /api/*、/health/ready、/docs 等 → require token          │
└─────────────────────────────────────────────────────────────┘

前端传输层（无 window.electronAPI 时自动启用，见 §4）：
  invoke(cmd)        → COMMAND_ROUTES（electron/commands.ts）→ 同源 fetch
  backendRequest()   → 同源 fetch（json/text/arraybuffer/timeout）
  listen(chat-stream-*) → GET /api/v1/chat/stream/{id} NDJSON 直读
```

## 3. 后端实现

### 3.1 配置（Task 1）

`backend/config/__init__.py`:

```python
def is_web_mode() -> bool:
    return os.getenv("SAGE_WEB_MODE") == "1"
```

### 3.2 静态文件服务（Task 2）

`backend/main.py` 模块级挂载：

```python
_WEB_DIST_PATH = Path(
    os.environ.get("SAGE_WEB_DIST_PATH", str(Path(__file__).parent.parent / "dist-web"))
)

if is_web_mode():
    if _WEB_DIST_PATH.exists():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(_WEB_DIST_PATH), html=True), name="web")
```

- 环境变量 `SAGE_WEB_DIST_PATH` 可覆盖默认路径（用于测试）
- `html=True` 启用 SPA fallback（未知路径返回 index.html）

### 3.3 认证扩展（Task 3）

`backend/api/local_auth.py` 扩展：

```python
# Web mode: accept ?token=<value> as Bearer-equivalent
if is_web_mode():
    url_token = request.query_params.get("token")
    if url_token and hmac.compare_digest(url_token, expected):
        return True
```

公开路径扩展：

```python
if is_web_mode():
    if path == "/" or path.startswith("/assets/") or path == "/favicon.ico":
        return True
```

### 3.4 公开路径（Web Mode）

| 路径                                                                               | 认证要求                                       |
| ---------------------------------------------------------------------------------- | ---------------------------------------------- |
| `/health`、`/health/proof`                                                         | 无                                             |
| 所有非 `/api/` 路径（`/`、`/assets/*`、`/sage.svg`、`/pet.html`、字体、SPA 路由…） | 无（Web mode 下，dist-web 产物本身无用户数据） |
| `/health/ready`                                                                    | 需要 token（body 含逐模块错误详情）            |
| `/docs`、`/redoc`、`/openapi.json`                                                 | 需要 token                                     |
| `/api/v1/*`                                                                        | 需要 token                                     |

> 2026-11-24：此前白名单只有 `/`、`/assets/*`、`/favicon.ico`，导致页面根目录静态资源
> （如 `/sage.svg` Logo/favicon）在网页模式返回 401。现改为"非 `/api/` 全部公开 +
> 敏感非 API 路径显式保护"。

## 4. 前端实现

### 4.1 浏览器传输层（2026-11-24 补齐）

早期版本只提供了 `platform.ts` 适配层，但主应用的 API 调用实际走
`desktopInvoke` / `desktopEvent` / `backendRequest` 三条 Electron IPC 通道，
浏览器里全部 fail-closed —— 页面能渲染，但会话/聊天/设置全部报"后端服务不可用"。

现在三条通道在 `window.electronAPI` 缺失时自动回退到同源 HTTP
（`src/shared/api/webTransport.ts`）：

| 通道                  | 浏览器实现                                                                                                           |
| --------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `invoke(cmd, args)`   | 查 `COMMAND_ROUTES`（`electron/commands.ts`，纯模块，与主进程同一份路由表）→ fetch；请求体 camelCase→snake_case      |
| `backendRequest(req)` | 直接 fetch 指定 path，支持 json/text/arraybuffer 与 timeout                                                          |
| `listen(event)`       | `chat-stream-{id}` → `GET /api/v1/chat/stream/{id}`、`shell-stream-{id}` → NDJSON 逐行回调；主进程专属事件静默 no-op |

不在路由表中的通道是 Electron 专属功能（PTY、窗口管理、浏览器面板等），
浏览器调用会得到"The X 仅在 Sage 桌面端可用"的可读错误，UI 按已有降级逻辑提示。

### 4.2 Token 引导（index.html，ES5 内联脚本）

`backend.cli.web` 打开 `http://127.0.0.1:<port>/?token=…`。首页在模块 bundle
之前用一段纯 ES5 内联脚本：

1. 读取 `?token=` 并写入 `localStorage['sage_auth_token']`；
2. 通过 `history.replaceState` 从地址栏移除 token（保留其余 query 与 hash 路由）；
3. 存储失败也不阻断页面加载。

这样所有后续请求（`webTransport.ts`、`webAccessClient`、附件上传等直连 fetch）
都能带上本地凭据，与 Electron 主进程注入的能力凭据同口径。具体用哪个 header
取决于请求路径 —— 见 4.3。

### 4.3 请求头分工：`Authorization` vs `X-Sage-Local-Authorization`

浏览器传输层必须区分两种身份，**不能都塞进 `Authorization`**：

| Header                       | 承载内容                 | 出现场景                     |
| ---------------------------- | ------------------------ | ---------------------------- |
| `Authorization`              | 上游服务商 API Key       | LLM 代理（`/api/v1/llm/**`） |
| `X-Sage-Local-Authorization` | 本地能力凭据（后端鉴权） | 所有需要本地鉴权的请求       |

**为什么**：LLM 代理请求本身就要带 `Authorization: Bearer <上游 API Key>`。
若把本地能力也写进 `Authorization`，两者必然互相覆盖 —— 上游 key 被本地 token
顶掉时后端会 401（"本地授权凭据无效或缺失"），上游 key 被顶掉时上游会 401
（"API Key 无效"）。后者正是网页模式下配置端点时的报错来源：用户填的 key 是对的，
却收到"上游返回 401：API Key 无效或已过期"。

**实现**（`src/shared/api/webTransport.ts`）：

- `getWebCapabilityHeaders()` 返回 `X-Sage-Local-Authorization: Bearer <token>`；
- `backendRequestViaHttp()` 用 `Headers` 对象合并调用方 header（大小写不敏感，
  避免 `authorization` / `Authorization` 产生两份、最终发送哪份不确定），
  再叠加调用方自带的 header —— 调用方的 `Authorization` 优先，不被覆盖；
- 与 Electron 主进程中继（`electron/main.ts` `sage:backend-request`）语义一致。

**后端侧**（`backend/api/local_auth.py` / `backend/api/llm_proxy_routes.py`）：

- `is_local_auth_valid()` 在 `/api/v1/llm/`（及旧 `/api/v1/llm-proxy/`）路径上
  以 `x-sage-local-authorization` 为准，不去读上游 key；
- `_filter_request_headers()` 在转发给上游前丢弃 `x-llm-provider-url` 与
  `x-sage-local-authorization`（内部头），本地能力**不会泄漏给第三方服务商**；
- 仅当 `authorization` 等于本地能力本身时才丢弃，否则原样透传给上游。

### 4.4 平台适配层（platform.ts）

`ElectronPlatform` / `WebPlatform` 保留用于 `usePlatform()`（`DesktopOnlyTooltip`
等桌面端专属功能提示）。`WebPlatform` 也会读 URL token 并落 localStorage，
但主链路不依赖它 —— 上面的 4.2 是权威引导。

### 4.5 老浏览器兜底

Win7 自带 IE 不支持 `<script type="module">`，此前表现为永久白屏。首页
8 秒内检测 `#root` 仍为空时，用 ES5 渲染一段中文提示：网页模式需要
Chrome 109+ / Firefox ESR 102+ / Edge 109+。

## 5. 启动方式

安装版与源码目录共用 `backend/cli/web.py` 的启动逻辑：

1. 选定端口：从 `8765` 起最多尝试 10 个端口，跳过被占用者；
2. 生成（或复用）`SAGE_LOCAL_AUTH_TOKEN`；
3. 等待 `/health` 就绪（默认 30 秒，使用 urllib 轮询，Win7 无 curl 亦可）；
4. 用默认浏览器打开 `http://127.0.0.1:<port>/?token=<token>`；
5. 前台运行 `uvicorn`，`Ctrl+C` 停止。

### 5.1 安装版（Windows）

安装包在 `resources/dist-web` 内置前端产物，并提供开始菜单入口：

- **开始菜单 → Sage 网页模式**（`SageWeb.cmd`，快捷方式由 `build/installer.nsh` 创建）
- 或直接双击安装目录下的 `SageWeb.cmd`

`SageWeb.cmd` 使用内置 Python（`resources/python/python.exe`）运行
`python -m backend.cli.web`，无需系统 Python / Node / curl。若 `8765` 被占用，
会自动顺延到下一个空闲端口，浏览器地址随之变化。

### 5.2 源码目录（scripts/sage-web.bat）

```batch
scripts\sage-web.bat
```

要求已激活后端环境（`conda activate sage-backend-py38`）。若 `dist-web/index.html`
不存在会先执行 `npm run build:web`，随后调用 `python -m backend.cli.web`。

### 5.3 Linux/macOS（手动）

```bash
npm run build:web
SAGE_WEB_MODE=1 python -m backend.cli.web
```

### 5.4 打包结构

| 来源                    | 打包位置                        | 机制                                    |
| ----------------------- | ------------------------------- | --------------------------------------- |
| `dist-web/`             | `resources/dist-web`            | `electron-builder.yml` `extraResources` |
| `resources/SageWeb.cmd` | 安装根目录 `SageWeb.cmd`        | `electron-builder.yml` `extraFiles`     |
| 开始菜单快捷方式        | `$SMPROGRAMS\Sage 网页模式.lnk` | `build/installer.nsh` `customInstall`   |

`release.yml` / `release-win7.yml` 在 electron-builder 打包前执行
`npm run build:web`，`ci.yml` 亦执行以提前拦截构建失败，确保安装包不会缺失
`resources/dist-web`。

## 6. 功能降级

| 功能类别    | 桌面端 | Web 模式 | 说明                 |
| ----------- | ------ | -------- | -------------------- |
| 聊天/会话   | ✅     | ✅       | 核心功能，完整可用   |
| Wiki        | ✅     | ✅       | 通过 API 访问        |
| 文件选择器  | ✅     | ❌       | 需要 Electron IPC    |
| Office 导入 | ✅     | ❌       | 需要本地文件系统访问 |
| 桌面控制    | ✅     | ❌       | 窗口管理、托盘等     |
| MCP 服务器  | ✅     | ⚠️       | 部分功能可用         |

`DesktopOnlyTooltip` 组件在 Web 模式下显示提示并禁用按钮。

## 7. 测试

### 7.1 单元测试

| 测试文件                                              | 覆盖范围                                                                              |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `backend/tests/test_web_config.py`                    | `is_web_mode()` 配置                                                                  |
| `backend/tests/test_web_serve.py`                     | 静态文件挂载                                                                          |
| `backend/tests/test_web_auth.py`                      | Token 认证扩展 + Web 静态路径公开规则                                                 |
| `backend/tests/test_cli_web.py`                       | 启动器（选端口 / token / 等待就绪 / URL 编码 / 缺失产物退出码）                       |
| `src/shared/api/__tests__/webTransport.test.ts`       | 浏览器传输层：路由映射 / snake_case / 204 / 错误状态码 / NDJSON 中继                  |
| `src/shared/api/__tests__/backendRequest.test.ts`     | Web 回退走同源 fetch；本地能力放 `X-Sage-Local-Authorization`、不占用 `Authorization` |
| `src/features/manage-endpoints/__tests__/api.test.ts` | 端点连通测试：上游 401 与本地 401 的错误文案区分（4.3）                               |

### 7.2 集成测试

`backend/tests/test_web_integration.py` 覆盖完整流程：

- 有效 token 通过 URL param 加载应用
- 有效 token 通过 Bearer header 加载应用
- 无 token 返回 401
- 无效 token 返回 401
- 静态资源无需认证
- 健康端点公开
- HTML 不依赖 electronAPI
- JS 使用 optional chaining

运行测试：

```bash
pytest backend/tests/test_web_integration.py -v
```

## 8. 环境变量

| 变量                    | 说明                      | 默认值                  |
| ----------------------- | ------------------------- | ----------------------- |
| `SAGE_WEB_MODE`         | 启用 Web 模式（设为 `1`） | 未设置                  |
| `SAGE_WEB_DIST_PATH`    | 前端构建产物路径          | `./dist-web`            |
| `SAGE_LOCAL_AUTH_TOKEN` | 认证 token（必填）        | 自动生成                |
| `PYTHON_BACKEND_PORT`   | 后端起始端口              | `8765`                  |
| `BACKEND_URL`           | 启动器写入的实际后端地址  | `http://127.0.0.1:8765` |

> 端口被占用时，启动器在 `PYTHON_BACKEND_PORT` 起的 10 个端口内顺延，并把实际端口
> 写回 `PYTHON_BACKEND_PORT` / `BACKEND_URL`。

## 9. 安全考虑

1. **Token 传输**：URL param 会出现在浏览器历史和服务器日志中；建议本地使用（`127.0.0.1`）
2. **CSP**：Web 模式不注入 CSP（`dist-web` 构建跳过 Electron 的 CSP meta 注入）；Electron 产物仍按 index.html 内联脚本自动计算 `sha256-*`。后续如需收紧可在 FastAPI 加安全响应头
3. **同源直连**：浏览器传输层只允许同源请求，token 仅存于该源的 localStorage；能力凭据与 Electron 主进程相同，均由 `backend.cli.web` 每次启动随机生成
4. **HTTPS**：生产部署应使用反向代理（nginx/caddy）启用 HTTPS

## 10. 与桌面端的关系

| 维度     | 桌面端                    | Web 模式            |
| -------- | ------------------------- | ------------------- |
| 启动方式 | Electron                  | 浏览器              |
| 认证     | Bearer header（IPC 注入） | URL param 或 Bearer |
| 文件系统 | 完整访问                  | 无（纯 API）        |
| 更新     | Electron 自动更新         | 刷新浏览器          |
| 平台支持 | Win7+ / macOS / Linux     | 任何现代浏览器      |

Web 模式是桌面端的**降级通道**，而非替代品。桌面端功能完整，Web 模式保留核心功能。

## 11. 未来扩展

- Phase 2：包装更多原生组件（PetSettings 等 115 个功能）
- Phase 3：PWA 支持（离线缓存、安装到桌面）
- 远程部署：Docker 镜像 + HTTPS 反向代理
