# Sage Web Fallback 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Sage 网页 fallback 功能，当 Electron 在 Win7 被管控软件拦截时，通过独立启动脚本启动后端并以浏览器访问。

**Architecture:** 后端以 web mode 运行，挂载 `dist-web/` 静态文件，通过 URL token 认证。前端使用平台适配层将 91 个 electronAPI 调用转为 REST API，桌面专属功能通过 DesktopOnlyTooltip 组件禁用。

**Tech Stack:** FastAPI (Python 3.10/3.8), React 18, Vite, TypeScript, Playwright

**Spec:** `docs/superpowers/specs/2026-11-13-web-fallback-design.md`

## Global Constraints

- **单端口**: 8765 同时服务 API 和静态文件
- **Token**: 每次启动通过 `secrets.token_urlsafe(32)` 生成，经 URL 参数传递，存 localStorage
- **监听**: 仅 `127.0.0.1`（localhost 回环）
- **Python**: 3.10 (main) / 3.8 (release/win7)，pydantic 2.x / 1.x
- **Node**: v25.9.0 (nvm)

---

## Task 1: 后端 - Web Mode 配置

**Files:**
- Modify: `backend/config.py:1-50`
- Create: `backend/tests/test_web_config.py`

**Interfaces:**
- Consumes: 环境变量 `SAGE_WEB_MODE`
- Produces: `is_web_mode() -> bool` 函数

- [ ] **Step 1: 编写失败测试**

```python
# backend/tests/test_web_config.py
import os
import pytest
from backend.config import is_web_mode

def test_is_web_mode_returns_false_by_default(monkeypatch):
    monkeypatch.delenv("SAGE_WEB_MODE", raising=False)
    assert is_web_mode() is False

def test_is_web_mode_returns_true_when_env_set(monkeypatch):
    monkeypatch.setenv("SAGE_WEB_MODE", "1")
    assert is_web_mode() is True
```

- [ ] **Step 2: 运行测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/test_web_config.py -v
```

Expected: FAIL with "ImportError: cannot import name 'is_web_mode'"

- [ ] **Step 3: 实现 is_web_mode 函数**

```python
# backend/config.py - 添加到文件末尾
import os

def is_web_mode() -> bool:
    """检查是否运行在 web mode（提供静态文件服务）。"""
    return os.getenv("SAGE_WEB_MODE") == "1"
```

- [ ] **Step 4: 运行测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/test_web_config.py -v
```

Expected: PASS (2 tests)

- [ ] **Step 5: 提交**

```bash
git add backend/config.py backend/tests/test_web_config.py
git commit -m "feat(backend): add is_web_mode config function"
```

---

## Task 2: 后端 - 静态文件服务

**Files:**
- Modify: `backend/main.py:500-600`（文件末尾附近）
- Create: `backend/tests/test_web_serve.py`

**Interfaces:**
- Consumes: `is_web_mode()` from config.py
- Produces: 静态文件挂载到 `/`（web mode 下）

- [ ] **Step 1: 编写失败测试**

```python
# backend/tests/test_web_serve.py
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

def test_serves_index_html_in_web_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("SAGE_WEB_MODE", "1")
    
    # 创建临时 dist-web 目录
    dist_web = tmp_path / "dist-web"
    dist_web.mkdir()
    (dist_web / "index.html").write_text("<html><body>Sage Web</body></html>")
    
    # Mock Path 返回临时目录
    original_path = Path
    def mock_path(p):
        if "dist-web" in str(p):
            return dist_web
        return original_path(p)
    monkeypatch.setattr("backend.main.Path", mock_path)
    
    # 重新导入 app
    import importlib
    import backend.main
    importlib.reload(backend.main)
    
    client = TestClient(backend.main.app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Sage Web" in response.text
```

- [ ] **Step 2: 运行测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/test_web_serve.py -v
```

Expected: FAIL with "404 Not Found" 或类似错误

- [ ] **Step 3: 实现静态文件挂载**

```python
# backend/main.py - 在文件末尾、uvicorn.run() 之前添加
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from backend.config import is_web_mode

if is_web_mode():
    web_dist = Path(__file__).parent.parent / "dist-web"
    if web_dist.exists():
        app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="web")
        logger.info(f"Web mode: serving static files from {web_dist}")
    else:
        logger.warning(f"Web mode enabled but dist-web not found: {web_dist}")
```

- [ ] **Step 4: 运行测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/test_web_serve.py -v
```

Expected: PASS (1 test)

- [ ] **Step 5: 提交**

```bash
git add backend/main.py backend/tests/test_web_serve.py
git commit -m "feat(backend): mount static files in web mode"
```

---

## Task 3: 后端 - Token 认证中间件

**Files:**
- Create: `backend/web_auth.py`
- Modify: `backend/main.py:450-500`（中间件注册处）
- Create: `backend/tests/test_web_auth.py`

**Interfaces:**
- Consumes: `SAGE_LOCAL_AUTH_TOKEN` 环境变量, `is_web_mode()`
- Produces: `WebTokenAuthMiddleware` 类

- [ ] **Step 1: 编写失败测试**

```python
# backend/tests/test_web_auth.py
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def web_mode_client(monkeypatch):
    monkeypatch.setenv("SAGE_WEB_MODE", "1")
    monkeypatch.setenv("SAGE_LOCAL_AUTH_TOKEN", "test-token-123")
    
    import importlib
    import backend.main
    importlib.reload(backend.main)
    
    return TestClient(backend.main.app)

def test_rejects_request_without_token(web_mode_client):
    response = web_mode_client.get("/api/v1/sessions")
    assert response.status_code == 401
    assert "Invalid token" in response.json()["detail"]

def test_accepts_request_with_url_param_token(web_mode_client):
    response = web_mode_client.get("/api/v1/sessions?token=test-token-123")
    assert response.status_code in [200, 404]  # 404 表示无会话，但认证通过

def test_accepts_request_with_bearer_token(web_mode_client):
    response = web_mode_client.get(
        "/api/v1/sessions",
        headers={"Authorization": "Bearer test-token-123"}
    )
    assert response.status_code in [200, 404]

def test_skips_auth_for_health_check(web_mode_client):
    response = web_mode_client.get("/health")
    assert response.status_code == 200

def test_skips_auth_for_static_files(web_mode_client, tmp_path, monkeypatch):
    dist_web = tmp_path / "dist-web"
    dist_web.mkdir()
    (dist_web / "index.html").write_text("<html>Test</html>")
    
    original_path = type(tmp_path)
    def mock_path(p):
        if "dist-web" in str(p):
            return dist_web
        return original_path(p)
    monkeypatch.setattr("backend.main.Path", mock_path)
    
    response = web_mode_client.get("/")
    assert response.status_code == 200
```

- [ ] **Step 2: 运行测试确认失败**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/test_web_auth.py -v
```

Expected: FAIL（中间件未实现）

- [ ] **Step 3: 实现 WebTokenAuthMiddleware**

```python
# backend/web_auth.py
import os
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

class WebTokenAuthMiddleware(BaseHTTPMiddleware):
    """Web mode 下从 URL param 或 Authorization header 验证 token。"""
    
    async def dispatch(self, request: Request, call_next):
        # 跳过静态文件认证
        if request.url.path == "/" or request.url.path.startswith("/assets/"):
            return await call_next(request)
        
        # 跳过健康检查
        if request.url.path == "/health":
            return await call_next(request)
        
        # 优先读 URL param
        token = request.query_params.get("token")
        if not token:
            # 其次读 Authorization header
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                token = auth[7:]
        
        # 验证 token
        expected = os.getenv("SAGE_LOCAL_AUTH_TOKEN")
        if not token or token != expected:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        return await call_next(request)
```

- [ ] **Step 4: 在 web mode 下注册中间件**

```python
# backend/main.py - 在静态文件挂载之前添加
from backend.web_auth import WebTokenAuthMiddleware
from backend.config import is_web_mode

if is_web_mode():
    app.add_middleware(WebTokenAuthMiddleware)
```

- [ ] **Step 5: 运行测试确认通过**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/test_web_auth.py -v
```

Expected: PASS (5 tests)

- [ ] **Step 6: 提交**

```bash
git add backend/web_auth.py backend/main.py backend/tests/test_web_auth.py
git commit -m "feat(backend): add token authentication middleware for web mode"
```

---

## Task 4: 前端 - 平台适配层

**Files:**
- Create: `src/platform.ts`
- Create: `src/platform.test.ts`

**Interfaces:**
- Consumes: `window.electronAPI`（如存在）
- Produces: `platform` 单例，提供 `isElectron()`, `invoke()`, `on()`, `getAuthHeaders()`

- [ ] **Step 1: 编写失败测试**

```typescript
// src/platform.test.ts
import { describe, it, expect, vi, afterEach } from 'vitest';

describe('platform', () => {
  afterEach(() => {
    vi.resetModules();
    delete (window as any).electronAPI;
    localStorage.clear();
  });

  it('detects non-electron environment', async () => {
    delete (window as any).electronAPI;
    const { platform } = await import('./platform');
    expect(platform.isElectron()).toBe(false);
  });

  it('detects electron environment', async () => {
    (window as any).electronAPI = { invoke: vi.fn(), on: vi.fn(), off: vi.fn() };
    vi.resetModules();
    const { platform } = await import('./platform');
    expect(platform.isElectron()).toBe(true);
  });

  it('reads token from URL and stores in localStorage', async () => {
    delete (window as any).electronAPI;
    window.history.pushState({}, '', '/?token=test-123');
    vi.resetModules();
    await import('./platform');
    expect(localStorage.getItem('sage_auth_token')).toBe('test-123');
  });

  it('clears token from URL after reading', async () => {
    delete (window as any).electronAPI;
    window.history.pushState({}, '', '/?token=test-123');
    vi.resetModules();
    await import('./platform');
    expect(window.location.search).toBe('');
  });

  it('returns auth headers with bearer token', async () => {
    delete (window as any).electronAPI;
    localStorage.setItem('sage_auth_token', 'stored-token');
    vi.resetModules();
    const { platform } = await import('./platform');
    const headers = platform.getAuthHeaders();
    expect(headers).toEqual({ Authorization: 'Bearer stored-token' });
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

```bash
npm test src/platform.test.ts
```

Expected: FAIL with "Cannot find module './platform'"

- [ ] **Step 3: 实现平台适配层**

```typescript
// src/platform.ts
export interface PlatformAdapter {
  isElectron(): boolean;
  invoke<T>(channel: string, ...args: any[]): Promise<T>;
  on(channel: string, callback: (...args: any[]) => void): () => void;
  getAuthHeaders(): Record<string, string>;
}

class ElectronPlatform implements PlatformAdapter {
  isElectron(): boolean {
    return typeof window !== 'undefined' && 'electronAPI' in window;
  }

  async invoke<T>(channel: string, ...args: any[]): Promise<T> {
    return (window as any).electronAPI.invoke(channel, ...args);
  }

  on(channel: string, callback: (...args: any[]) => void): () => void {
    (window as any).electronAPI.on(channel, callback);
    return () => (window as any).electronAPI.off(channel, callback);
  }

  getAuthHeaders(): Record<string, string> {
    return {};
  }
}

class WebPlatform implements PlatformAdapter {
  private token: string;

  constructor() {
    const urlToken = new URL(window.location.href).searchParams.get('token');
    if (urlToken) {
      localStorage.setItem('sage_auth_token', urlToken);
      window.history.replaceState(null, '', window.location.pathname);
    }
    this.token = localStorage.getItem('sage_auth_token') || '';
  }

  isElectron(): boolean {
    return false;
  }

  async invoke<T>(channel: string, ...args: any[]): Promise<T> {
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

  on(channel: string, _callback: (...args: any[]) => void): () => void {
    console.warn(`Web mode does not support IPC: ${channel}`);
    return () => {};
  }

  getAuthHeaders(): Record<string, string> {
    return { Authorization: `Bearer ${this.token}` };
  }

  private mapChannelToEndpoint(channel: string): string {
    const mapping: Record<string, string> = {
      'chat:send': '/api/v1/chat/send',
      'chat:stream': '/api/v1/chat/stream',
      'session:list': '/api/v1/sessions',
      'session:create': '/api/v1/sessions',
      'memory:list': '/api/v1/memory/list',
      'project:list': '/api/v1/projects',
      'project:create': '/api/v1/projects',
    };
    return mapping[channel] || `/api/v1/${channel}`;
  }
}

export const platform: PlatformAdapter =
  typeof window !== 'undefined' && 'electronAPI' in window
    ? new ElectronPlatform()
    : new WebPlatform();
```

- [ ] **Step 4: 运行测试确认通过**

```bash
npm test src/platform.test.ts
```

Expected: PASS (5 tests)

- [ ] **Step 5: 提交**

```bash
git add src/platform.ts src/platform.test.ts
git commit -m "feat(frontend): add platform abstraction layer"
```

---

## Task 5: 前端 - usePlatform Hook

**Files:**
- Create: `src/hooks/usePlatform.ts`
- Create: `src/hooks/usePlatform.test.ts`

**Interfaces:**
- Consumes: `platform` 单例
- Produces: `usePlatform()` hook

- [ ] **Step 1: 编写失败测试**

```typescript
// src/hooks/usePlatform.test.ts
import { describe, it, expect, vi, afterEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { usePlatform } from './usePlatform';

describe('usePlatform', () => {
  afterEach(() => {
    vi.resetModules();
    delete (window as any).electronAPI;
    localStorage.clear();
  });

  it('returns isElectron false in web mode', async () => {
    delete (window as any).electronAPI;
    vi.resetModules();
    const { result } = renderHook(() => usePlatform());
    expect(result.current.isElectron).toBe(false);
  });

  it('returns auth headers', async () => {
    delete (window as any).electronAPI;
    localStorage.setItem('sage_auth_token', 'test-token');
    vi.resetModules();
    const { result } = renderHook(() => usePlatform());
    expect(result.current.authHeaders).toEqual({ Authorization: 'Bearer test-token' });
  });

  it('returns invoke function', async () => {
    delete (window as any).electronAPI;
    vi.resetModules();
    const { result } = renderHook(() => usePlatform());
    expect(typeof result.current.invoke).toBe('function');
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

```bash
npm test src/hooks/usePlatform.test.ts
```

Expected: FAIL

- [ ] **Step 3: 实现 usePlatform hook**

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

- [ ] **Step 4: 运行测试确认通过**

```bash
npm test src/hooks/usePlatform.test.ts
```

Expected: PASS (3 tests)

- [ ] **Step 5: 提交**

```bash
git add src/hooks/usePlatform.ts src/hooks/usePlatform.test.ts
git commit -m "feat(frontend): add usePlatform hook"
```

---

## Task 6: 前端 - DesktopOnlyTooltip 组件

**Files:**
- Create: `src/components/DesktopOnlyTooltip.tsx`
- Create: `src/components/DesktopOnlyTooltip.test.tsx`

**Interfaces:**
- Consumes: `usePlatform()` hook, `Tooltip` 组件
- Produces: 包装组件，web mode 下禁用子元素

- [ ] **Step 1: 编写失败测试**

```typescript
// src/components/DesktopOnlyTooltip.test.tsx
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { DesktopOnlyTooltip } from './DesktopOnlyTooltip';

describe('DesktopOnlyTooltip', () => {
  afterEach(() => {
    vi.resetModules();
    delete (window as any).electronAPI;
  });

  it('renders children normally in electron mode', async () => {
    (window as any).electronAPI = {};
    vi.resetModules();
    const { DesktopOnlyTooltip } = await import('./DesktopOnlyTooltip');
    
    render(
      <DesktopOnlyTooltip featureName="Test Feature">
        <button>Click me</button>
      </DesktopOnlyTooltip>
    );
    expect(screen.getByText('Click me')).not.toBeDisabled();
  });

  it('disables children in web mode', async () => {
    delete (window as any).electronAPI;
    vi.resetModules();
    const { DesktopOnlyTooltip } = await import('./DesktopOnlyTooltip');
    
    render(
      <DesktopOnlyTooltip featureName="Test Feature">
        <button>Click me</button>
      </DesktopOnlyTooltip>
    );
    const wrapper = screen.getByText('Click me').parentElement;
    expect(wrapper).toHaveStyle({ opacity: 0.5, pointerEvents: 'none' });
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

```bash
npm test src/components/DesktopOnlyTooltip.test.tsx
```

Expected: FAIL

- [ ] **Step 3: 实现 DesktopOnlyTooltip 组件**

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

  return (
    <Tooltip content={`${featureName} 仅在桌面版可用`}>
      <div style={{ opacity: 0.5, pointerEvents: 'none' }}>
        {children}
      </div>
    </Tooltip>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
npm test src/components/DesktopOnlyTooltip.test.tsx
```

Expected: PASS (2 tests)

- [ ] **Step 5: 提交**

```bash
git add src/components/DesktopOnlyTooltip.tsx src/components/DesktopOnlyTooltip.test.tsx
git commit -m "feat(frontend): add DesktopOnlyTooltip component for feature degradation"
```

---

## Task 7: 前端 - 构建配置

**Files:**
- Modify: `vite.config.ts:1-50`
- Modify: `package.json:15-25`（scripts 部分）

**Interfaces:**
- Consumes: Vite `mode` 参数
- Produces: `build:web` npm 脚本

- [ ] **Step 1: 更新 vite.config.ts**

```typescript
// vite.config.ts - 修改 defineConfig 回调
export default defineConfig(({ mode }) => {
  const isWeb = mode === 'web';
  
  return {
    base: isWeb ? '/' : './',
    build: {
      outDir: isWeb ? 'dist-web' : 'dist',
      // ... 其他现有配置保持不变
    },
    // ... 其他配置保持不变
  };
});
```

- [ ] **Step 2: 添加 build:web 脚本到 package.json**

```json
// package.json - 在 "scripts" 部分添加
{
  "scripts": {
    "build:web": "vite build --mode web",
    "build:electron": "tsc -p electron/tsconfig.json",
    "dev": "vite",
    // ... 其他脚本保持不变
  }
}
```

- [ ] **Step 3: 测试 web 构建**

```bash
npm run build:web
```

Expected: 构建成功，生成 `dist-web/index.html`

- [ ] **Step 4: 提交**

```bash
git add vite.config.ts package.json
git commit -m "feat(frontend): add web mode build configuration"
```

---

## Task 8: 启动脚本

**Files:**
- Create: `scripts/sage-web.bat`

**Interfaces:**
- Consumes: Python, Node.js, 后端代码, 前端构建产物
- Produces: 后端进程 + 浏览器窗口

- [ ] **Step 1: 创建 sage-web.bat**

```batch
@echo off
setlocal enabledelayedexpansion

:: ============================================
:: Sage 网页模式启动脚本 (Win7 Fallback)
:: ============================================

:: 检查 Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python
    pause
    exit /b 1
)

:: 检查后端代码
if not exist "backend\main.py" (
    echo [错误] 未找到后端代码
    pause
    exit /b 1
)

:: 检查前端构建
if not exist "dist-web\index.html" (
    echo [提示] 构建网页版...
    call npm run build:web
    if %errorlevel% neq 0 (
        echo [错误] 前端构建失败
        pause
        exit /b 1
    )
)

:: 生成 token
for /f %%i in ('python -c "import secrets; print(secrets.token_urlsafe(32))"') do set TOKEN=%%i

set SAGE_LOCAL_AUTH_TOKEN=%TOKEN%
set SAGE_WEB_MODE=1
set PYTHON_BACKEND_PORT=8765

echo [1/3] 启动后端...
start /b python backend/main.py --web-mode

echo [2/3] 等待后端就绪...
set /a attempts=0
:wait_loop
if !attempts! geq 30 (
    echo [错误] 启动超时
    pause
    exit /b 1
)
timeout /t 1 >nul
curl -s http://127.0.0.1:8765/health >nul 2>&1
if errorlevel 1 (
    set /a attempts+=1
    goto wait_loop
)

echo [3/3] 打开浏览器...
start http://127.0.0.1:8765/?token=%TOKEN%

echo.
echo ========================================
echo  Sage 网页模式已启动
echo  http://127.0.0.1:8765
echo  Ctrl+C 停止
echo ========================================

pause >nul
taskkill /f /im python.exe /fi "WINDOWTITLE eq Sage*" >nul 2>&1
```

- [ ] **Step 2: 提交**

```bash
git add scripts/sage-web.bat
git commit -m "feat: add sage-web.bat launcher for Win7 fallback"
```

---

## Task 9: 集成测试与文档

**Files:**
- Create: `tests/web-mode-e2e.spec.ts`
- Create: `docs/technical/48-web-fallback.md`
- Create: `docs/user-manual/47-web-fallback.md`

**Interfaces:**
- Consumes: 完整的 web mode 实现
- Produces: E2E 测试覆盖 + 用户/开发者文档

- [ ] **Step 1: 编写 E2E 测试**

```typescript
// tests/web-mode-e2e.spec.ts
import { test, expect } from '@playwright/test';

test.describe('Web Mode E2E', () => {
  test('loads chat interface with valid token', async ({ page }) => {
    const token = process.env.SAGE_LOCAL_AUTH_TOKEN || 'test-token';
    await page.goto(`http://127.0.0.1:8765/?token=${token}`);
    await expect(page.locator('h1')).toBeVisible({ timeout: 10000 });
  });

  test('rejects access without token', async ({ page }) => {
    const response = await page.goto('http://127.0.0.1:8765/api/v1/sessions');
    expect(response?.status()).toBe(401);
  });
});
```

- [ ] **Step 2: 运行 E2E 测试**

```bash
# 启动 web mode
npm run build:web
SAGE_WEB_MODE=1 SAGE_LOCAL_AUTH_TOKEN=test-token \
  /home/fz/anaconda3/envs/sage-backend/bin/python backend/main.py &

# 运行测试
npx playwright test tests/web-mode-e2e.spec.ts
```

Expected: PASS (2 tests)

- [ ] **Step 3: 编写技术文档**

```markdown
// docs/technical/48-web-fallback.md
# Web Fallback Mode

## Overview

Sage 可在浏览器中运行，作为 Electron 被管控软件拦截时的备用方案。

## Architecture

- 后端以 `--web-mode` 启动，挂载 `dist-web/` 静态文件
- URL token 认证（一次性，存 localStorage）
- 平台适配层将 electronAPI 调用转为 REST API

## Usage

```bash
scripts/sage-web.bat
```

## Limitations

- 桌面专属功能（桌宠、托盘、OCR）禁用
- 文件操作使用浏览器 File API（功能受限）
```

- [ ] **Step 4: 编写用户手册**

```markdown
// docs/user-manual/47-web-fallback.md
# 网页模式（Win7 备用方案）

如果 Electron 桌面版无法启动（被安全软件拦截），可使用网页模式。

## 使用方法

1. 双击 `sage-web.bat`
2. 等待浏览器自动打开
3. 开始使用

## 功能限制

以下功能在网页模式下不可用：
- 桌宠窗口
- 系统托盘
- 本地 OCR
```

- [ ] **Step 5: 提交**

```bash
git add tests/web-mode-e2e.spec.ts docs/technical/48-web-fallback.md docs/user-manual/47-web-fallback.md
git commit -m "test+docs: add E2E tests and documentation for web mode"
```

---

## Task 10: 最终验证与 PR

**Files:**
- 无（验证任务）

**Interfaces:**
- Consumes: 所有前置任务
- Produces: 可工作的 web mode + PR

- [ ] **Step 1: 运行所有测试**

```bash
# 后端测试
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/test_web_*.py -v

# 前端测试
npm test

# E2E 测试
npm run build:web
SAGE_WEB_MODE=1 SAGE_LOCAL_AUTH_TOKEN=test-token \
  /home/fz/anaconda3/envs/sage-backend/bin/python backend/main.py &
npx playwright test tests/web-mode-e2e.spec.ts
```

Expected: 所有测试通过

- [ ] **Step 2: 手动验收**

1. 运行 `scripts/sage-web.bat`
2. 验证浏览器打开 `http://127.0.0.1:8765`
3. 验证聊天界面加载
4. 验证桌面专属功能显示 tooltip
5. 验证刷新后认证保持

- [ ] **Step 3: 创建 PR**

```bash
git push -u origin feat/web-fallback-win7
gh pr create \
  --title "feat: web fallback for Win7 compatibility" \
  --body "$(cat <<'EOF'
## Summary

- 后端 web mode：静态文件服务 + token 认证中间件
- 前端平台适配层：91 个 electronAPI 调用转 REST API
- 功能降级：DesktopOnlyTooltip 包装桌面专属功能
- 启动脚本：sage-web.bat 一键启动

## Test plan

- [ ] 后端单元测试通过
- [ ] 前端单元测试通过
- [ ] E2E 测试通过
- [ ] 手动验收：sage-web.bat 启动 + 浏览器访问
EOF
)"
```

Expected: PR 创建成功
