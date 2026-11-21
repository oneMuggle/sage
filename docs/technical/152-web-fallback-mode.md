# Web Fallback Mode（网页回退模式）

> Win7 用户在 Electron 21 无法升级时，可通过浏览器访问 Sage 核心功能。

---

## 1. 设计目标

| 项         | 值                                                                              |
| ---------- | ------------------------------------------------------------------------------- |
| 触发场景   | Win7 SP1 用户 Electron 21 CVE 无法修复时的降级通道                              |
| 技术栈     | 后端 FastAPI + 前端 Vite build（`dist-web/`）                                   |
| 认证方式   | `SAGE_LOCAL_AUTH_TOKEN`（与桌面端相同）；Web 支持 URL param `?token=xxx`         |
| 浏览器要求 | Chrome 109+ / Firefox ESR 102+（Win7 最后支持的版本）                           |
| 范围       | Phase 1 MVP：聊天/会话核心功能；桌面端专属功能（文件选择器、Office 导入等）降级 |

## 2. 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                        Browser                               │
│  http://127.0.0.1:8765/?token=<random-token>                │
└────────────────────┬────────────────────────────────────────┘
                     │
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
│    - /health, /, /assets/*, /favicon.ico → public (web mode) │
│    - /api/v1/* → require token                               │
└─────────────────────────────────────────────────────────────┘
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

| 路径           | 认证要求 |
| -------------- | -------- |
| `/health`      | 无       |
| `/`            | 无（Web mode 下） |
| `/assets/*`    | 无（Web mode 下） |
| `/favicon.ico` | 无（Web mode 下） |
| `/api/v1/*`    | 需要 token |

## 4. 前端实现

### 4.1 平台适配层（Task 4）

`src/platform.ts`:

```typescript
export const platform = {
  isDesktop: typeof window !== 'undefined' && !!window.electronAPI,
  isWeb: typeof window === 'undefined' || !window.electronAPI,
  name: (typeof window !== 'undefined' && !!window.electronAPI) ? 'desktop' : 'web',
  version: 'N/A',
};
```

### 4.2 usePlatform Hook（Task 5）

```typescript
export function usePlatform() {
  return platform;  // { isDesktop, isWeb, name, version }
}
```

### 4.3 DesktopOnlyTooltip 组件（Task 6）

```tsx
<DesktopOnlyTooltip title="此功能仅桌面端可用">
  <Button disabled={!platform.isDesktop}>...</Button>
</DesktopOnlyTooltip>
```

### 4.4 构建配置（Task 7）

`vite.config.ts` 函数式配置：

```typescript
export default defineConfig(({ mode }) => {
  const isWeb = mode === 'web';
  return {
    base: isWeb ? '/' : './',
    build: {
      outDir: isWeb ? 'dist-web' : 'dist',
    },
    // Web mode 跳过 cspInjectionPlugin（FastAPI 设 CSP headers）
  };
});
```

构建命令：`npm run build:web`

### 4.5 Electron API 安全性

构建产物中所有 `window.electronAPI` 引用均为 optional-chained：

```javascript
// 安全模式 - Web 下返回 undefined，不崩溃
const api = typeof window !== 'undefined' ? window.electronAPI : undefined;
window.electronAPI?.helpAPI?.getVersion();  // undefined?.helpAPI → undefined
```

共 99 处引用，全部为安全访问模式。

## 5. 启动方式

### 5.1 Windows（sage-web.bat）

```batch
scripts\sage-web.bat
```

脚本自动：
1. 检查 Python 和后端代码
2. 若 `dist-web/index.html` 不存在，运行 `npm run build:web`
3. 生成随机 token（`secrets.token_urlsafe(32)`）
4. 启动后端（`SAGE_WEB_MODE=1`）
5. 健康检查（最多 30 秒）
6. 打开浏览器到 `http://127.0.0.1:8765/?token=<token>`

### 5.2 Linux/macOS（手动）

```bash
# 构建前端
npm run build:web

# 生成 token
export SAGE_LOCAL_AUTH_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")

# 启动后端
SAGE_WEB_MODE=1 python backend/main.py &

# 等待健康检查
until curl -s http://127.0.0.1:8765/health > /dev/null; do sleep 1; done

# 打开浏览器
open "http://127.0.0.1:8765/?token=$SAGE_LOCAL_AUTH_TOKEN"
```

## 6. 功能降级

| 功能类别     | 桌面端 | Web 模式 | 说明                          |
| ------------ | ------ | -------- | ----------------------------- |
| 聊天/会话    | ✅     | ✅       | 核心功能，完整可用            |
| Wiki         | ✅     | ✅       | 通过 API 访问                 |
| 文件选择器   | ✅     | ❌       | 需要 Electron IPC             |
| Office 导入  | ✅     | ❌       | 需要本地文件系统访问          |
| 桌面控制     | ✅     | ❌       | 窗口管理、托盘等              |
| MCP 服务器   | ✅     | ⚠️       | 部分功能可用                  |

`DesktopOnlyTooltip` 组件在 Web 模式下显示提示并禁用按钮。

## 7. 测试

### 7.1 单元测试

| 测试文件                          | 覆盖范围               |
| --------------------------------- | ---------------------- |
| `backend/tests/test_web_config.py` | `is_web_mode()` 配置   |
| `backend/tests/test_web_serve.py`  | 静态文件挂载           |
| `backend/tests/test_web_auth.py`   | Token 认证扩展         |

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

| 变量                    | 说明                             | 默认值       |
| ----------------------- | -------------------------------- | ------------ |
| `SAGE_WEB_MODE`         | 启用 Web 模式（设为 `1`）        | 未设置       |
| `SAGE_WEB_DIST_PATH`    | 前端构建产物路径                 | `./dist-web` |
| `SAGE_LOCAL_AUTH_TOKEN` | 认证 token（必填）               | 自动生成     |
| `PYTHON_BACKEND_PORT`   | 后端端口                         | `8765`       |

## 9. 安全考虑

1. **Token 传输**：URL param 会出现在浏览器历史和服务器日志中；建议本地使用（`127.0.0.1`）
2. **CSP**：FastAPI 设置 CSP headers（不同于 Electron 的 meta tag）
3. **CORS**：Web 模式默认允许同源请求；跨域需额外配置
4. **HTTPS**：生产部署应使用反向代理（nginx/caddy）启用 HTTPS

## 10. 与桌面端的关系

| 维度         | 桌面端                    | Web 模式                     |
| ------------ | ------------------------- | ---------------------------- |
| 启动方式     | Electron                  | 浏览器                       |
| 认证         | Bearer header（IPC 注入） | URL param 或 Bearer          |
| 文件系统     | 完整访问                  | 无（纯 API）                 |
| 更新         | Electron 自动更新         | 刷新浏览器                   |
| 平台支持     | Win7+ / macOS / Linux     | 任何现代浏览器               |

Web 模式是桌面端的**降级通道**，而非替代品。桌面端功能完整，Web 模式保留核心功能。

## 11. 未来扩展

- Phase 2：包装更多原生组件（PetSettings 等 115 个功能）
- Phase 3：PWA 支持（离线缓存、安装到桌面）
- 远程部署：Docker 镜像 + HTTPS 反向代理
