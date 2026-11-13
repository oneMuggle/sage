# Sage 网页 Fallback 设计文档

> **日期**: 2026-11-13  
> **状态**: Draft  
> **作者**: Claude + User  
> **分支**: main / release/win7（双分支同步）

---

## 1. 背景与目标

### 1.1 问题陈述

在 Win7 企业环境中，部分管控软件会在**进程级别**拦截 Electron 应用，导致桌面版 Sage 无法启动。用户完全无法使用系统，即使后端 Python 服务可以正常运行。

### 1.2 目标

提供一个**被动降级**通道：当 Electron 启动失败时，用户可通过独立启动脚本（`sage-web.bat`）启动后端服务，并通过浏览器访问网页版 Sage，保留核心功能（聊天、会话、记忆、项目）。

### 1.3 非目标

- ❌ 主动选择"始终以网页模式启动"（无设置入口）
- ❌ Electron 内嵌 BrowserView 降级（与进程级拦截场景矛盾）
- ❌ 完整复刻所有桌面功能（桌宠、系统托盘、本地 OCR 等不可用）

---

## 2. 架构总览

### 2.1 组件关系

```
┌─────────────────────────────────────────────────────────┐
│  sage-web.bat (Win7 Fallback Launcher)                  │
│  ┌───────────────────────────────────────────────────┐  │
│  │ 1. 生成 token: secrets.token_urlsafe(32)          │  │
│  │ 2. 启动后端: python backend/main.py --web-mode    │  │
│  │    - 环境变量: SAGE_LOCAL_AUTH_TOKEN=<token>      │  │
│  │    - 环境变量: SAGE_WEB_MODE=1                    │  │
│  │ 3. 打开浏览器: http://127.0.0.1:8765/?token=xxx  │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Backend (FastAPI) - Web Mode                           │
│  ┌───────────────────────────────────────────────────┐  │
│  │ • 挂载静态文件: app.mount("/", StaticFiles(...))  │  │
│  │ • Token 验证中间件: 读 URL param → 验证           │  │
│  │ • API 路由: /api/v1/* (已有)                      │  │
│  │ • SSE 流: /chat/stream/{id} (已有)                │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Frontend (React SPA) - Platform Adaptive               │
│  ┌───────────────────────────────────────────────────┐  │
│  │ • src/platform.ts: 平台检测 + 统一 API            │  │
│  │ • 91 个 electronAPI 调用点 → platform.invoke()    │  │
│  │ • 115 个原生功能 → isElectron() 条件渲染          │  │
│  │ • 不可用功能 → disabled + tooltip                 │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

### 2.2 数据流

1. **启动阶段**：
   - `sage-web.bat` 生成 token → 设环境变量 → 启动后端 → 打开浏览器

2. **认证阶段**：
   - 浏览器加载 `/?token=xxx` → 前端读 URL → 存 localStorage → 后续请求带 `Authorization: Bearer <token>`

3. **API 调用**：
   - 前端 `platform.invoke('chat/stream', ...)` → 检测非 Electron → `fetch('/api/v1/chat/stream', ...)`
   - SSE 流式输出 → `EventSource` 原生支持

4. **功能降级**：
   - 组件渲染时 `if (!platform.isElectron()) return <Button disabled tooltip="仅桌面版可用" />`

### 2.3 关键约束

- **单端口**：8765 同时服务 API + 静态文件
- **Token 一次性**：每次后端启动重新生成，旧 token 失效
- **localhost 回环**：仅监听 `127.0.0.1`，不暴露到网络

---

## 3. 后端改造

### 3.1 新增文件与修改

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/main.py` | 修改 | 添加 `--web-mode` 参数 + 静态文件挂载 |
| `backend/web_auth.py` | 新增 | Web 模式 token 验证中间件 |
| `backend/config.py` | 修改 | 添加 `SAGE_WEB_MODE` 环境变量读取 |

### 3.2 核心实现

#### 3.2.1 Web Mode 启动参数

```python
# backend/main.py
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--web-mode", action="store_true", help="Enable web mode (serve static files)")
args = parser.parse_args()

if args.web_mode or os.getenv("SAGE_WEB_MODE") == "1":
    # 挂载前端构建产物
    from fastapi.staticfiles import StaticFiles
    web_dist = Path(__file__).parent.parent / "dist-web"
    if web_dist.exists():
        app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="web")
    else:
        logger.warning(f"Web dist not found: {web_dist}")
```

#### 3.2.2 Token 验证中间件

```python
# backend/web_auth.py
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

class WebTokenAuthMiddleware(BaseHTTPMiddleware):
    """Web 模式下从 URL param 或 Authorization header 验证 token"""
    
    async def dispatch(self, request: Request, call_next):
        # 静态文件不需要认证（由 StaticFiles 处理）
        if request.url.path == "/" or request.url.path.startswith("/assets/"):
            return await call_next(request)
        
        # 优先读 URL param（首次加载）
        token = request.query_params.get("token")
        if not token:
            # 其次读 Authorization header（后续请求）
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                token = auth[7:]
        
        # 验证 token
        expected = os.getenv("SAGE_LOCAL_AUTH_TOKEN")
        if not token or token != expected:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        return await call_next(request)

# 仅在 web-mode 下启用
if is_web_mode():
    app.add_middleware(WebTokenAuthMiddleware)
```

#### 3.2.3 CORS 调整

```python
# backend/main.py - web mode 下允许 localhost 来源
if is_web_mode():
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:8765", "http://localhost:8765"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
```

### 3.3 静态文件构建产物

- **目录**：`dist-web/`（与 Electron 的 `dist/` 区分）
- **构建命令**：`npm run build:web` → `vite build --mode web`
- **Vite 配置**：`base: '/'`（绝对路径，非相对路径）

---

## 4. 前端改造

### 4.1 新增文件与修改

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/platform.ts` | 新增 | 平台检测 + 统一 API 适配层 |
| `src/hooks/usePlatform.ts` | 新增 | React hook 封装 |
| `src/components/DesktopOnlyTooltip.tsx` | 新增 | 功能降级组件 |
| `vite.config.ts` | 修改 | 添加 `web` mode 构建配置 |
| 91 个 electronAPI 调用点 | 修改 | 改用 `platform.invoke()` |
| 115 个原生功能组件 | 修改 | 条件渲染 + disabled tooltip |

### 4.2 核心实现

#### 4.2.1 平台适配层 `src/platform.ts`

```typescript
// src/platform.ts

export interface PlatformAdapter {
  isElectron(): boolean;
  invoke<T>(channel: string, ...args: any[]): Promise<T>;
  on(channel: string, callback: (...args: any[]) => void): () => void;
  getAuthHeaders(): Record<string, string>;
}

class ElectronPlatform implements PlatformAdapter {
  isElectron() {
    return typeof window !== 'undefined' && 'electronAPI' in window;
  }

  async invoke<T>(channel: string, ...args: any[]): Promise<T> {
    return window.electronAPI.invoke(channel, ...args);
  }

  on(channel: string, callback: (...args: any[]) => void) {
    window.electronAPI.on(channel, callback);
    return () => window.electronAPI.off(channel, callback);
  }

  getAuthHeaders() {
    return {}; // Electron 内部通信，不需要 Authorization
  }
}

class WebPlatform implements PlatformAdapter {
  private token: string;

  constructor() {
    // 从 URL param 读取 token 并存入 localStorage
    const urlToken = new URL(window.location.href).searchParams.get('token');
    if (urlToken) {
      localStorage.setItem('sage_auth_token', urlToken);
      // 清除 URL 中的 token（防止浏览器历史泄露）
      window.history.replaceState(null, '', window.location.pathname);
    }
    this.token = localStorage.getItem('sage_auth_token') || '';
  }

  isElectron() {
    return false;
  }

  async invoke<T>(channel: string, ...args: any[]): Promise<T> {
    // 将 IPC channel 映射为 REST API
    const endpoint = this.mapChannelToEndpoint(channel);
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.token}`,
      },
      body: JSON.stringify({ args }),
    });
    
    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }
    
    return response.json();
  }

  on(channel: string, callback: (...args: any[]) => void) {
    // Web 模式不支持 IPC 事件，返回空函数
    console.warn(`Web mode does not support IPC: ${channel}`);
    return () => {};
  }

  getAuthHeaders() {
    return { 'Authorization': `Bearer ${this.token}` };
  }

  private mapChannelToEndpoint(channel: string): string {
    // IPC channel → REST API 映射
    const mapping: Record<string, string> = {
      'chat:send': '/api/v1/chat/send',
      'session:list': '/api/v1/sessions',
      'memory:list': '/api/v1/memory/list',
      // ... 其他映射
    };
    return mapping[channel] || `/api/v1/${channel}`;
  }
}

// 单例导出
export const platform: PlatformAdapter = 
  typeof window !== 'undefined' && 'electronAPI' in window
    ? new ElectronPlatform()
    : new WebPlatform();
```

#### 4.2.2 React Hook `src/hooks/usePlatform.ts`

```typescript
// src/hooks/usePlatform.ts
import { platform } from '../platform';

export function usePlatform() {
  return {
    isElectron: platform.isElectron(),
    invoke: platform.invoke.bind(platform),
    on: platform.on.bind(platform),
    authHeaders: platform.getAuthHeaders(),
  };
}
```

#### 4.2.3 功能降级组件

```typescript
// src/components/DesktopOnlyTooltip.tsx
import { Tooltip } from './ui/tooltip';
import { usePlatform } from '../hooks/usePlatform';

interface Props {
  children: React.ReactNode;
  featureName: string;
}

export function DesktopOnlyTooltip({ children, featureName }: Props) {
  const { isElectron } = usePlatform();

  if (isElectron) {
    return <>{children}</>;
  }

  // Web 模式：禁用 + tooltip
  return (
    <Tooltip content={`${featureName} 仅在桌面版可用`}>
      <div style={{ opacity: 0.5, pointerEvents: 'none' }}>
        {children}
      </div>
    </Tooltip>
  );
}
```

#### 4.2.4 SSE 流式输出适配

```typescript
// src/api/chat.ts
import { platform } from '../platform';

export async function* streamChat(message: string) {
  if (platform.isElectron()) {
    // Electron: 使用 IPC
    yield* platform.invoke('chat:stream', message);
  } else {
    // Web: 使用 EventSource
    const token = localStorage.getItem('sage_auth_token');
    const response = await fetch('/api/v1/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({ message }),
    });

    const reader = response.body?.getReader();
    const decoder = new TextDecoder();
    
    while (true) {
      const { done, value } = await reader!.read();
      if (done) break;
      
      const chunk = decoder.decode(value);
      // 解析 SSE 格式: "data: {...}\n\n"
      const lines = chunk.split('\n').filter(l => l.startsWith('data: '));
      for (const line of lines) {
        const data = JSON.parse(line.slice(6));
        yield data;
      }
    }
  }
}
```

#### 4.2.5 Vite 构建配置

```typescript
// vite.config.ts
export default defineConfig(({ mode }) => {
  const isWeb = mode === 'web';
  
  return {
    base: isWeb ? '/' : './', // Web 模式用绝对路径
    build: {
      outDir: isWeb ? 'dist-web' : 'dist',
      // ... 其他配置
    },
  };
});
```

```json
// package.json
{
  "scripts": {
    "build:web": "vite build --mode web",
    "build:electron": "tsc -p electron/tsconfig.json"
  }
}
```

### 4.3 降级功能清单

| 功能 | 文件数 | Web 模式处理 |
|------|--------|-------------|
| 桌宠窗口 | ~15 | disabled + tooltip "桌宠仅在桌面版可用" |
| 系统托盘 | ~10 | disabled + tooltip |
| 原生文件对话框 | ~40 | 改用 `<input type="file">`（功能受限） |
| 本地 OCR | ~25 | disabled + tooltip |
| 原生通知 | ~20 | 降级为 Web Notifications API |
| 剪贴板（native） | ~10 | 降级为 Clipboard API |
| 文件监听（chokidar） | ~15 | disabled（Web 无文件监听） |

---

## 5. 启动脚本与测试策略

### 5.1 启动脚本 `scripts/sage-web.bat`

```batch
@echo off
setlocal enabledelayedexpansion

:: ============================================
:: Sage 网页模式启动脚本 (Win7 Fallback)
:: ============================================

:: 检查 Python 环境
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请确保已安装并添加到 PATH
    pause
    exit /b 1
)

:: 检查后端构建
if not exist "backend\main.py" (
    echo [错误] 未找到后端代码，请确保在 Sage 根目录运行
    pause
    exit /b 1
)

:: 检查前端构建产物
if not exist "dist-web\index.html" (
    echo [提示] 未找到网页版构建产物，正在构建...
    call npm run build:web
    if %errorlevel% neq 0 (
        echo [错误] 前端构建失败
        pause
        exit /b 1
    )
)

:: 生成随机 token（使用 Python）
for /f %%i in ('python -c "import secrets; print(secrets.token_urlsafe(32))"') do set TOKEN=%%i

:: 设置环境变量
set SAGE_LOCAL_AUTH_TOKEN=%TOKEN%
set SAGE_WEB_MODE=1
set PYTHON_BACKEND_PORT=8765

:: 启动后端（后台运行）
echo [1/3] 启动后端服务...
start /b python backend/main.py --web-mode

:: 等待后端就绪（健康检查，最多 30 秒）
echo [2/3] 等待后端就绪...
set /a attempts=0
:wait_loop
if !attempts! geq 30 (
    echo [错误] 后端启动超时
    pause
    exit /b 1
)
timeout /t 1 >nul
curl -s http://127.0.0.1:8765/health >nul 2>&1
if errorlevel 1 (
    set /a attempts+=1
    goto wait_loop
)

:: 打开浏览器
echo [3/3] 打开浏览器...
start http://127.0.0.1:8765/?token=%TOKEN%

echo.
echo ========================================
echo  Sage 网页模式已启动
echo  浏览器: http://127.0.0.1:8765
echo  按 Ctrl+C 停止服务
echo ========================================
echo.

:: 保持脚本运行（Ctrl+C 退出）
pause >nul

:: 清理：停止后端进程
echo 正在停止服务...
taskkill /f /im python.exe /fi "WINDOWTITLE eq Sage*" >nul 2>&1
echo 服务已停止
```

### 5.2 测试策略

#### 5.2.1 单元测试

| 测试文件 | 覆盖范围 |
|---------|---------|
| `src/platform.test.ts` | 平台检测、token 读取、API 映射 |
| `src/hooks/usePlatform.test.ts` | Hook 返回值、条件渲染 |
| `backend/test_web_auth.py` | Token 验证中间件 |

#### 5.2.2 集成测试

```bash
# 1. 启动 web mode
npm run build:web
python backend/main.py --web-mode &

# 2. 验证静态文件服务
curl http://127.0.0.1:8765/  # 应返回 index.html

# 3. 验证 token 认证
curl http://127.0.0.1:8765/api/v1/sessions  # 应 401
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/v1/sessions  # 应 200

# 4. 验证 SSE 流
curl -N http://127.0.0.1:8765/api/v1/chat/stream -d '{"message":"test"}'
```

#### 5.2.3 E2E 测试（Playwright）

```typescript
// tests/web-mode.spec.ts
import { test, expect } from '@playwright/test';

test.describe('Web Mode', () => {
  test('should load chat interface', async ({ page }) => {
    await page.goto('http://127.0.0.1:8765/?token=test-token');
    await expect(page.locator('h1')).toContainText('Sage');
  });

  test('should show disabled tooltip for desktop-only features', async ({ page }) => {
    await page.goto('http://127.0.0.1:8765/?token=test-token');
    const petButton = page.locator('[data-testid="pet-settings"]');
    await expect(petButton).toBeDisabled();
    await petButton.hover();
    await expect(page.locator('[role="tooltip"]')).toContainText('仅在桌面版可用');
  });

  test('should stream chat response', async ({ page }) => {
    await page.goto('http://127.0.0.1:8765/?token=test-token');
    await page.fill('[data-testid="chat-input"]', 'Hello');
    await page.press('[data-testid="chat-input"]', 'Enter');
    await expect(page.locator('[data-testid="chat-message"]')).toContainText('AI response');
  });
});
```

#### 5.2.4 手动验收清单

- [ ] `sage-web.bat` 能成功启动后端 + 打开浏览器
- [ ] 浏览器显示登录页（或自动登录，取决于 token）
- [ ] 聊天功能正常（流式输出）
- [ ] 会话列表加载正常
- [ ] 设置页可查看（但桌宠/OCR 等 disabled）
- [ ] 刷新页面后 token 仍有效（localStorage）
- [ ] 关闭终端后后端进程正确退出

---

## 6. 实施计划

### Phase 1: MVP（2-3 天）

1. **后端改造**（0.5 天）
   - 添加 `--web-mode` 参数
   - 实现静态文件挂载
   - 实现 token 验证中间件

2. **前端平台适配层**（1 天）
   - 创建 `src/platform.ts`
   - 创建 `usePlatform` hook
   - 改造 91 个 electronAPI 调用点

3. **功能降级**（0.5 天）
   - 创建 `DesktopOnlyTooltip` 组件
   - 包装 115 个原生功能组件

4. **构建配置**（0.5 天）
   - 修改 `vite.config.ts`
   - 添加 `build:web` 脚本

5. **启动脚本**（0.5 天）
   - 编写 `scripts/sage-web.bat`
   - 测试启动流程

### Phase 2: 体验优化（后续）

- 浏览器模式下隐藏不可用功能入口（而非仅 disabled）
- 文件操作改用 Web File System Access API（Chrome/Edge 支持）
- PWA 化（离线缓存 + 安装到桌面）
- 双分支同步（main + release/win7）

---

## 7. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 91 个 electronAPI 改造遗漏 | 中 | 高 | 全局搜索 + 编译时检查 + 运行时 fallback |
| Win7 IE11 兼容性 | 低 | 中 | 目标浏览器为 Chrome/Edge（Win7 可装），不兼容 IE |
| Token 泄露（URL 历史记录） | 低 | 低 | `history.replaceState` 清除 URL 参数 + localhost 回环 |
| 后端启动超时（>30s） | 低 | 中 | 增加重试次数 + 显示启动进度 |
| 双分支同步冲突 | 中 | 低 | 平台适配层独立于分支，仅启动脚本需适配 |

---

## 8. 验收标准

- ✅ `sage-web.bat` 一键启动，30 秒内打开浏览器
- ✅ 核心功能可用：聊天、会话、记忆、项目（CRUD）
- ✅ 不可用功能有明确提示（disabled + tooltip）
- ✅ Token 认证安全：无 token 请求返回 401
- ✅ 双分支可同步：main + release/win7 均支持

---

## 9. 附录

### 9.1 IPC Channel → REST API 映射表

| IPC Channel | REST Endpoint | 方法 |
|-------------|---------------|------|
| `chat:send` | `/api/v1/chat/send` | POST |
| `chat:stream` | `/api/v1/chat/stream` | POST (SSE) |
| `session:list` | `/api/v1/sessions` | GET |
| `session:create` | `/api/v1/sessions` | POST |
| `memory:list` | `/api/v1/memory/list` | GET |
| `project:list` | `/api/v1/projects` | GET |
| `project:create` | `/api/v1/projects` | POST |
| ... | ... | ... |

### 9.2 相关文件清单

- `backend/main.py` - FastAPI 入口
- `backend/web_auth.py` - Web token 验证（新增）
- `src/platform.ts` - 平台适配层（新增）
- `src/hooks/usePlatform.ts` - React hook（新增）
- `src/components/DesktopOnlyTooltip.tsx` - 降级组件（新增）
- `vite.config.ts` - 构建配置
- `scripts/sage-web.bat` - 启动脚本（新增）
- `package.json` - 添加 `build:web` 脚本
