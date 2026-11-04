# Rich Preview 渲染增强实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保持现有安全基线的前提下，让 Mermaid 图表可交互（平移/缩放/源图切换/错误详情），让 HTML 预览可观测（错误桥接、刷新、全屏、停止、下载），并把 Electron 默认权限收紧为"拒绝未授权请求"。

**Architecture:** 抽离两个可复用组件：`HtmlPreviewHost`（统一 HTML iframe 宿主，带错误桥接与工具条）与增强后的 `MermaidDiagram`（在现有 `MermaidBlock` 上扩展平移/缩放/源图切换/错误详情）。Electron 侧新增 `permissionPolicy.ts`，在 app ready 时为所有 webContents 注入默认拒绝的 `setPermissionRequestHandler`，仅对剪贴板等白名单功能放行。

**Tech Stack:** Electron 21.4.4, React 18 + TypeScript, Vite, mermaid 11.17.2, lucide-react, vitest + @testing-library/react, Playwright（E2E 可选）.

**Spec:** 本文档即 spec；配套现状分析见 2026-11-04 会话报告（已口头确认）。

## Global Constraints

- **Python 环境**：后端只用 `/home/fz/anaconda3/envs/sage-backend`，不在 worktree 内 `pip install` 到共享环境。
- **Node**：nvm 下的 v25.9.0；`npm install` 在 worktree 内执行。
- **端口**：worktree 已写入 `.env.local`：`PYTHON_BACKEND_PORT=8872`, `VITE_DEV_PORT=1527`。
- **安全**：iframe 沙盒只允许 `allow-scripts`，**禁止** `allow-same-origin`；srcdoc 继承父 CSP，生产构建通过 `vite.config.ts` 注入 CSP。
- **Electron**：contextIsolation=true, nodeIntegration=false, sandbox=!NEEDS_NO_SANDBOX（Win7 关）。
- **架构行数棘轮**：`scripts/architecture-check.mjs` 不放松；新文件不计入 baseline 仅当超过阈值。
- **字体大小检查**：`scripts/check-font-scale.mjs` 必须绿。
- **双分支**：本次只改 `main`；后续 cherry-pick 到 `release/win7`。

---

## 文件结构

| 路径 | 职责 |
|---|---|
| `src/widgets/chat/preview/HtmlPreviewHost.tsx` | 新建。统一 HTML iframe 宿主：错误桥接、工具条（刷新/全屏/停止/复制源码/下载）、fullscreen portal。 |
| `src/widgets/chat/preview/HtmlPreviewHost.test.tsx` | 新建。HtmlPreviewHost 单测。 |
| `src/widgets/chat/preview/FileContentRenderer.tsx` | 修改。HTML 分支改用 HtmlPreviewHost。 |
| `src/widgets/chat/HtmlCodeBlock.tsx` | 修改。预览模式改用 HtmlPreviewHost。 |
| `src/widgets/chat/artifacts/ArtifactViewer.tsx` | 修改。HTML 分支改用 HtmlPreviewHost（保留 htmlReloadKey 透传）。 |
| `src/widgets/chat/MermaidBlock.tsx` | 重构为 `MermaidDiagram` + `MermaidBlock` 薄包装。 |
| `src/widgets/chat/MermaidDiagram.tsx` | 新建。核心渲染 + 平移/缩放/源图切换/错误详情/SVG 下载。 |
| `src/widgets/chat/MermaidDiagram.test.tsx` | 新建。MermaidDiagram 交互单测。 |
| `src/widgets/chat/MermaidBlock.tsx` | 改为薄包装：调用 MermaidDiagram，保留现有 audit 函数签名。 |
| `electron/permissionPolicy.ts` | 新建。默认拒绝 + 白名单放行。 |
| `electron/permissionPolicy.test.ts` | 新建。permissionPolicy 单测。 |
| `electron/main.ts` | 修改。app ready 时调用 `installPermissionPolicy()`。 |
| `docs/technical/124-markdown-renderer.md` | 修改。补充 Mermaid 交互章节。 |
| `docs/technical/38-artifacts-panel.md` | 修改。补充 HTML 预览工具条章节。 |

---

## 实施步骤

### Task 1: Electron 默认权限策略（P0 安全基线）

**Files:**
- Create: `electron/permissionPolicy.ts`
- Create: `electron/permissionPolicy.test.ts`
- Modify: `electron/main.ts` (在 `app.whenReady()` 后调用 `installPermissionPolicy()`)

**Interfaces:**
- `installPermissionPolicy(): void` — 在 `session.defaultSession` 上设置 `setPermissionRequestHandler` 与 `setPermissionCheckHandler`。
- 白名单：`clipboard-read`, `clipboard-sanitized-write`, `notifications`（放行），其余 `geolocation`, `camera`, `microphone`, `midi`, `mediaKeySystem`, `pointerLock` 等拒绝。
- **挂 session 而非 webContents 的原因**：webContents 级 handler 优先级高于 session 级，用 `app.on('web-contents-created')` 逐个安装会覆盖 `agentBrowserHost`（`persist:sage-agent-browser`）与 `browserPanel` 各自 partition 上已有的"全部拒绝"，反而给内置浏览器放行 clipboard/notifications。session 级只作用于 default session（主窗口/启动屏/独立 artifact 窗口及其中的 srcdoc iframe），分区浏览器策略保持原样。

**Steps:**

- [x] **Step 1: 写失败测试**

```typescript
// electron/permissionPolicy.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest';

describe('installPermissionPolicy', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('拒绝 geolocation/camera/microphone', async () => {
    const mockSession = {
      setPermissionRequestHandler: vi.fn(),
      setPermissionCheckHandler: vi.fn(),
    };
    vi.doMock('electron', () => ({ session: { defaultSession: mockSession } }));

    const { installPermissionPolicy } = await import('./permissionPolicy');
    installPermissionPolicy();

    const reqHandler = mockSession.setPermissionRequestHandler.mock.calls[0][0];
    const checkHandler = mockSession.setPermissionCheckHandler.mock.calls[0][0];

    const reqCb = vi.fn();
    reqHandler({}, 'geolocation', reqCb);
    expect(reqCb).toHaveBeenCalledWith(false);

    // setPermissionCheckHandler 直接返回 boolean（非回调形式）
    expect(checkHandler({}, 'camera', 'https://example.com')).toBe(false);
  });

  it('放行 clipboard-read/clipboard-sanitized-write/notifications', async () => {
    // ... 同上构造，对三个白名单权限断言 callback(true) 与 check 返回 true
  });
});
```

- [x] **Step 2: 运行测试验证失败**

```bash
cd /home/fz/project/sage/.worktrees/feat-rich-preview-rendering
npx vitest run electron/permissionPolicy.test.ts
```

预期：FAIL（模块不存在）。

- [x] **Step 3: 写最小实现**

```typescript
// electron/permissionPolicy.ts
import { session } from 'electron';

const ALLOWED_PERMISSIONS = new Set([
  'clipboard-read',
  'clipboard-sanitized-write',
  'notifications',
]);

export function installPermissionPolicy(): void {
  const defaultSession = session.defaultSession;
  defaultSession.setPermissionRequestHandler((_wc, permission, callback) => {
    callback(ALLOWED_PERMISSIONS.has(permission));
  });
  defaultSession.setPermissionCheckHandler((_wc, permission) => {
    return ALLOWED_PERMISSIONS.has(permission);
  });
}
```

- [x] **Step 4: 运行测试验证通过**

```bash
npx vitest run electron/permissionPolicy.test.ts
```

预期：PASS（2 passed）。

- [x] **Step 5: 在 main.ts 中调用**

```typescript
// electron/main.ts (app.whenReady() 链首部，cleanupOlderThan(7) 之后)
import { installPermissionPolicy } from './permissionPolicy';

app
  .whenReady()
  .then(async () => {
    cleanupOlderThan(7);
    // 2026-11-04: 默认拒绝权限请求 —— 必须在任何 webContents 创建之前注册
    installPermissionPolicy();
```

- [x] **Step 6: 提交**

```bash
git add electron/permissionPolicy.ts electron/permissionPolicy.test.ts electron/main.ts
git commit -m "feat(security): default-deny permission policy for default session"
```

---

### Task 2: HtmlPreviewHost 统一宿主（P1 交互）

**Files:**
- Create: `src/widgets/chat/preview/HtmlPreviewHost.tsx`
- Create: `src/widgets/chat/preview/HtmlPreviewHost.test.tsx`
- Modify: `src/widgets/chat/preview/FileContentRenderer.tsx:157-169`
- Modify: `src/widgets/chat/HtmlCodeBlock.tsx:63-69`
- Modify: `src/widgets/chat/artifacts/ArtifactViewer.tsx` (HTML 分支)

**Interfaces:**
- `HtmlPreviewHostProps`: `{ html: string; name: string; reloadKey?: number; className?: string; maxHeight?: string }`
- 内部状态：`error: string | null`, `fullscreen: boolean`, `stopped: boolean`
- 工具条按钮：刷新（`reloadKey++`）、全屏（portal overlay）、停止（卸载 iframe）、复制源码（`navigator.clipboard.writeText`）、下载（Blob URL `<a download>`）
- 错误桥接：注入 `<script>` 到 srcDoc 头部，捕获 `window.onerror` / `unhandledrejection` / `console.error`，`postMessage` 到父窗口，父窗口监听并展示错误横幅。

**Steps:**

- [ ] **Step 1: 写失败测试**

```typescript
// src/widgets/chat/preview/HtmlPreviewHost.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { HtmlPreviewHost } from './HtmlPreviewHost';

describe('HtmlPreviewHost', () => {
  it('渲染 iframe 并带 sandbox 属性', () => {
    render(<HtmlPreviewHost html="<h1>Hi</h1>" name="test.html" />);
    const iframe = screen.getByTestId('html-preview-frame');
    expect(iframe).toHaveAttribute('sandbox', 'allow-scripts');
    expect(iframe).toHaveAttribute('srcDoc', '<h1>Hi</h1>');
  });

  it('工具条包含刷新/全屏/停止/复制/下载按钮', () => {
    render(<HtmlPreviewHost html="<h1>Hi</h1>" name="test.html" />);
    expect(screen.getByTestId('html-host-refresh')).toBeInTheDocument();
    expect(screen.getByTestId('html-host-fullscreen')).toBeInTheDocument();
    expect(screen.getByTestId('html-host-stop')).toBeInTheDocument();
    expect(screen.getByTestId('html-host-copy')).toBeInTheDocument();
    expect(screen.getByTestId('html-host-download')).toBeInTheDocument();
  });

  it('点击停止后卸载 iframe 并显示已停止提示', () => {
    render(<HtmlPreviewHost html="<h1>Hi</h1>" name="test.html" />);
    fireEvent.click(screen.getByTestId('html-host-stop'));
    expect(screen.queryByTestId('html-preview-frame')).not.toBeInTheDocument();
    expect(screen.getByText('已停止执行脚本')).toBeInTheDocument();
  });

  it('reloadKey 变化时重新挂载 iframe', () => {
    const { rerender } = render(<HtmlPreviewHost html="<h1>Hi</h1>" name="test.html" reloadKey={0} />);
    const iframe1 = screen.getByTestId('html-preview-frame');
    rerender(<HtmlPreviewHost html="<h1>Hi</h1>" name="test.html" reloadKey={1} />);
    const iframe2 = screen.getByTestId('html-preview-frame');
    expect(iframe1).not.toBe(iframe2);
  });
});
```

- [ ] **Step 2: 运行测试验证失败**

```bash
npx vitest run src/widgets/chat/preview/HtmlPreviewHost.test.tsx
```

预期：FAIL（模块不存在）。

- [ ] **Step 3: 写最小实现**

```typescript
// src/widgets/chat/preview/HtmlPreviewHost.tsx
import { ClipboardCopy, Download, Maximize2, RefreshCw, Square } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

interface HtmlPreviewHostProps {
  html: string;
  name: string;
  reloadKey?: number;
  className?: string;
  maxHeight?: string;
}

const ERROR_BRIDGE_SCRIPT = `
<script>
(function() {
  var errors = [];
  window.addEventListener('error', function(e) {
    errors.push({ type: 'error', msg: e.message, file: e.filename, line: e.lineno });
    parent.postMessage({ __sageHtmlError: true, errors: errors }, '*');
  });
  window.addEventListener('unhandledrejection', function(e) {
    errors.push({ type: 'rejection', msg: String(e.reason) });
    parent.postMessage({ __sageHtmlError: true, errors: errors }, '*');
  });
  var origError = console.error;
  console.error = function() {
    var args = Array.prototype.slice.call(arguments);
    errors.push({ type: 'console', msg: args.map(String).join(' ') });
    parent.postMessage({ __sageHtmlError: true, errors: errors }, '*');
    origError.apply(console, arguments);
  };
})();
</script>
`;

function injectErrorBridge(html: string): string {
  if (html.includes('</head>')) {
    return html.replace('</head>', ERROR_BRIDGE_SCRIPT + '</head>');
  }
  return ERROR_BRIDGE_SCRIPT + html;
}

export function HtmlPreviewHost({ html, name, reloadKey = 0, className = '', maxHeight = '24rem' }: HtmlPreviewHostProps) {
  const [internalReload, setInternalReload] = useState(0);
  const [stopped, setStopped] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [errors, setErrors] = useState<Array<{ type: string; msg: string }>>([]);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const effectiveReload = reloadKey + internalReload;
  const bridgedHtml = stopped ? '' : injectErrorBridge(html);

  useEffect(() => {
    function onMessage(evt: MessageEvent) {
      if (evt.source !== iframeRef.current?.contentWindow) return;
      if (evt.data?.__sageHtmlError) {
        setErrors(evt.data.errors ?? []);
      }
    }
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  const handleRefresh = useCallback(() => setInternalReload((r) => r + 1), []);
  const handleStop = useCallback(() => setStopped(true), []);
  const handleCopy = useCallback(() => {
    void navigator.clipboard?.writeText(html)?.catch(() => {});
  }, [html]);
  const handleDownload = useCallback(() => {
    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  }, [html, name]);
  const handleFullscreen = useCallback(() => setFullscreen(true), []);

  const iframe = stopped ? (
    <div className="flex items-center justify-center h-full text-sm text-muted">已停止执行脚本</div>
  ) : (
    <iframe
      ref={iframeRef}
      key={effectiveReload}
      srcDoc={bridgedHtml}
      sandbox="allow-scripts"
      referrerPolicy="no-referrer"
      title={name}
      className="w-full h-full border-0 bg-white"
      data-testid="html-preview-frame"
    />
  );

  const toolbar = (
    <div className="flex items-center gap-1 px-2 py-1 border-b border-border bg-bg-subtle">
      <button
        className="p-1.5 rounded hover:bg-bg-hover"
        title="刷新"
        data-testid="html-host-refresh"
        onClick={handleRefresh}
      >
        <RefreshCw className="w-4 h-4" />
      </button>
      <button
        className="p-1.5 rounded hover:bg-bg-hover"
        title="全屏"
        data-testid="html-host-fullscreen"
        onClick={handleFullscreen}
      >
        <Maximize2 className="w-4 h-4" />
      </button>
      <button
        className="p-1.5 rounded hover:bg-bg-hover"
        title="停止脚本"
        data-testid="html-host-stop"
        onClick={handleStop}
      >
        <Square className="w-4 h-4" />
      </button>
      <button
        className="p-1.5 rounded hover:bg-bg-hover"
        title="复制源码"
        data-testid="html-host-copy"
        onClick={handleCopy}
      >
        <ClipboardCopy className="w-4 h-4" />
      </button>
      <button
        className="p-1.5 rounded hover:bg-bg-hover"
        title="下载 HTML"
        data-testid="html-host-download"
        onClick={handleDownload}
      >
        <Download className="w-4 h-4" />
      </button>
    </div>
  );

  const errorBanner = errors.length > 0 && (
    <div className="px-2 py-1 bg-red-50 dark:bg-red-950 text-red-700 dark:text-red-300 text-xs">
      <strong>脚本错误 ({errors.length}):</strong> {errors[errors.length - 1].msg}
    </div>
  );

  const content = (
    <div className={`flex flex-col ${className}`} style={{ maxHeight }}>
      {toolbar}
      {errorBanner}
      <div className="flex-1 overflow-hidden">{iframe}</div>
    </div>
  );

  if (fullscreen) {
    return createPortal(
      <div
        className="fixed inset-0 z-50 bg-black bg-opacity-80 flex items-center justify-center"
        onClick={() => setFullscreen(false)}
      >
        <div className="w-[90vw] h-[90vh] bg-white rounded shadow-lg flex flex-col" onClick={(e) => e.stopPropagation()}>
          {toolbar}
          {errorBanner}
          <div className="flex-1 overflow-hidden">{iframe}</div>
        </div>
      </div>,
      document.body,
    );
  }

  return content;
}
```

- [ ] **Step 4: 运行测试验证通过**

```bash
npx vitest run src/widgets/chat/preview/HtmlPreviewHost.test.tsx
```

预期：PASS。

- [ ] **Step 5: 在 FileContentRenderer.tsx 中替换 HTML 分支**

```typescript
// src/widgets/chat/preview/FileContentRenderer.tsx:157-169
import { HtmlPreviewHost } from './HtmlPreviewHost';

// ... 在 FileContentRenderer 函数内
if (content.kind === 'html') {
  return (
    <HtmlPreviewHost
      html={content.content ?? ''}
      name={name}
      reloadKey={htmlReloadKey}
      className="rounded border border-border"
      maxHeight="24rem"
    />
  );
}
```

- [ ] **Step 6: 在 HtmlCodeBlock.tsx 中替换预览模式**

```typescript
// src/widgets/chat/HtmlCodeBlock.tsx (预览分支)
import { HtmlPreviewHost } from './preview/HtmlPreviewHost';

// ... 在 HtmlCodeBlock 内
if (mode === 'preview') {
  return <HtmlPreviewHost html={code} name="snippet.html" className="rounded border border-border" maxHeight="24rem" />;
}
```

- [ ] **Step 7: 在 ArtifactViewer.tsx 中替换 HTML 分支**

```typescript
// src/widgets/chat/artifacts/ArtifactViewer.tsx (HTML 分支)
import { HtmlPreviewHost } from '../preview/HtmlPreviewHost';

// ... 在 ArtifactViewer 内
if (content.kind === 'html') {
  return (
    <HtmlPreviewHost
      html={content.content ?? ''}
      name={name}
      reloadKey={htmlReloadKey}
      className="h-full"
      maxHeight="100%"
    />
  );
}
```

- [ ] **Step 8: 运行全量测试验证无回归**

```bash
npx vitest run src/widgets/chat/
```

预期：PASS，无新增失败。

- [ ] **Step 9: 提交**

```bash
git add src/widgets/chat/preview/HtmlPreviewHost.tsx src/widgets/chat/preview/HtmlPreviewHost.test.tsx
git add src/widgets/chat/preview/FileContentRenderer.tsx src/widgets/chat/HtmlCodeBlock.tsx
git add src/widgets/chat/artifacts/ArtifactViewer.tsx
git commit -m "feat(preview): unified HtmlPreviewHost with error bridge, toolbar, fullscreen"
```

---

### Task 3: MermaidDiagram 交互增强（P1 图表）

**Files:**
- Create: `src/widgets/chat/MermaidDiagram.tsx`
- Create: `src/widgets/chat/MermaidDiagram.test.tsx`
- Modify: `src/widgets/chat/MermaidBlock.tsx` (薄包装)

**Interfaces:**
- `MermaidDiagramProps`: `{ code: string; theme: 'default' | 'dark' }`
- 新增交互：拖拽平移（`pointerdown` → `pointermove` → `pointerup`）、Ctrl+滚轮缩放（0.4–3.0, step 1.25）、双击恢复 fit/100%、源图切换（textarea）、SVG 下载、错误详情（`mermaid.parse` 捕获）。
- 工具条：缩放 +/-、适应屏幕、实际大小、源图切换、下载 PNG、下载 SVG、复制源码、全屏。

**Steps:**

- [ ] **Step 1: 写失败测试**

```typescript
// src/widgets/chat/MermaidDiagram.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const renderMock = vi.fn();
const parseMock = vi.fn();
vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    render: (...args: unknown[]) => renderMock(...args),
    parse: (...args: unknown[]) => parseMock(...args),
  },
}));

import { MermaidDiagram } from './MermaidDiagram';

describe('MermaidDiagram', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    renderMock.mockResolvedValue({ svg: '<svg></svg>', bindFunctions: () => {} });
    parseMock.mockResolvedValue(true);
  });

  it('工具条包含平移/缩放/源图切换/下载 SVG 按钮', () => {
    render(<MermaidDiagram code="graph TD; A-->B" theme="default" />);
    expect(screen.getByTestId('mermaid-zoom-in')).toBeInTheDocument();
    expect(screen.getByTestId('mermaid-zoom-out')).toBeInTheDocument();
    expect(screen.getByTestId('mermaid-fit')).toBeInTheDocument();
    expect(screen.getByTestId('mermaid-actual-size')).toBeInTheDocument();
    expect(screen.getByTestId('mermaid-toggle-source')).toBeInTheDocument();
    expect(screen.getByTestId('mermaid-download-svg')).toBeInTheDocument();
  });

  it('点击源图切换后显示 textarea', () => {
    render(<MermaidDiagram code="graph TD; A-->B" theme="default" />);
    fireEvent.click(screen.getByTestId('mermaid-toggle-source'));
    expect(screen.getByTestId('mermaid-source-textarea')).toBeInTheDocument();
  });

  it('解析失败时显示错误详情', async () => {
    parseMock.mockRejectedValue(new Error('Syntax error at line 3'));
    render(<MermaidDiagram code="invalid" theme="default" />);
    await vi.waitFor(() => {
      expect(screen.getByText(/Syntax error at line 3/)).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 2: 运行测试验证失败**

```bash
npx vitest run src/widgets/chat/MermaidDiagram.test.tsx
```

预期：FAIL（模块不存在）。

- [ ] **Step 3: 写最小实现**

```typescript
// src/widgets/chat/MermaidDiagram.tsx
import { Copy, Download, Edit3, Expand, Maximize2, Minus, Plus, RotateCcw } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { ShikiCodeBlock } from './ShikiCodeBlock';

interface MermaidDiagramProps {
  code: string;
  theme: 'default' | 'dark';
}

type MermaidApi = {
  initialize: (config: unknown) => void;
  render: (id: string, text: string) => Promise<{ svg: string; bindFunctions?: (el: Element) => void }>;
  parse: (text: string) => Promise<unknown>;
};

let mermaidPromise: Promise<MermaidApi> | null = null;

function getMermaid(): Promise<MermaidApi> {
  mermaidPromise ??= import('mermaid').then((mod) => {
    const api = (mod.default ?? mod) as MermaidApi;
    api.initialize({ startOnLoad: false, securityLevel: 'strict', maxTextSize: 50000, maxEdges: 500 });
    return api;
  });
  return mermaidPromise;
}

const ZOOM_MIN = 0.4;
const ZOOM_MAX = 3.0;
const ZOOM_STEP = 1.25;

let renderCounter = 0;

export function MermaidDiagram({ code, theme }: MermaidDiagramProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgWrapperRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [showSource, setShowSource] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const renderId = `mermaid-${++renderCounter}`;
    getMermaid()
      .then(async (api) => {
        api.initialize({ startOnLoad: false, securityLevel: 'strict', theme, maxTextSize: 50000, maxEdges: 500 });
        const { svg } = await api.render(renderId, code);
        if (!cancelled) {
          setSvg(svg);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [code, theme]);

  const handleZoomIn = useCallback(() => setZoom((z) => Math.min(ZOOM_MAX, z * ZOOM_STEP)), []);
  const handleZoomOut = useCallback(() => setZoom((z) => Math.max(ZOOM_MIN, z / ZOOM_STEP)), []);
  const handleFit = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, []);
  const handleActualSize = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, []);
  const handleWheel = useCallback((e: React.WheelEvent) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    setZoom((z) => {
      const next = e.deltaY < 0 ? z * ZOOM_STEP : z / ZOOM_STEP;
      return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, next));
    });
  }, []);

  const [dragging, setDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0 });
  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    setDragging(true);
    dragStart.current = { x: e.clientX, y: e.clientY };
  }, []);
  const handlePointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!dragging) return;
      setPan((p) => ({ x: p.x + e.clientX - dragStart.current.x, y: p.y + e.clientY - dragStart.current.y }));
      dragStart.current = { x: e.clientX, y: e.clientY };
    },
    [dragging],
  );
  const handlePointerUp = useCallback(() => setDragging(false), []);

  const handleDownloadSvg = useCallback(() => {
    const blob = new Blob([svg], { type: 'image/svg+xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'mermaid-diagram.svg';
    a.click();
    URL.revokeObjectURL(url);
  }, [svg]);

  const handleDownloadPng = useCallback(() => {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    const img = new Image();
    img.onload = () => {
      canvas.width = img.width * 2;
      canvas.height = img.height * 2;
      ctx?.drawImage(img, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((blob) => {
        if (!blob) return;
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'mermaid-diagram.png';
        a.click();
        URL.revokeObjectURL(url);
      });
    };
    img.src = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svg)));
  }, [svg]);

  const handleCopySource = useCallback(() => {
    void navigator.clipboard?.writeText(code)?.catch(() => {});
  }, [code]);

  const toolbar = (
    <div className="flex items-center gap-1 px-2 py-1 border-b border-border bg-bg-subtle">
      <button className="p-1.5 rounded hover:bg-bg-hover" title="放大" data-testid="mermaid-zoom-in" onClick={handleZoomIn}>
        <Plus className="w-4 h-4" />
      </button>
      <button className="p-1.5 rounded hover:bg-bg-hover" title="缩小" data-testid="mermaid-zoom-out" onClick={handleZoomOut}>
        <Minus className="w-4 h-4" />
      </button>
      <button className="p-1.5 rounded hover:bg-bg-hover" title="适应屏幕" data-testid="mermaid-fit" onClick={handleFit}>
        <Maximize2 className="w-4 h-4" />
      </button>
      <button className="p-1.5 rounded hover:bg-bg-hover" title="实际大小" data-testid="mermaid-actual-size" onClick={handleActualSize}>
        <RotateCcw className="w-4 h-4" />
      </button>
      <button
        className="p-1.5 rounded hover:bg-bg-hover"
        title={showSource ? '显示图表' : '显示源码'}
        data-testid="mermaid-toggle-source"
        onClick={() => setShowSource((s) => !s)}
      >
        <Edit3 className="w-4 h-4" />
      </button>
      <button className="p-1.5 rounded hover:bg-bg-hover" title="下载 PNG" data-testid="mermaid-download-png" onClick={handleDownloadPng}>
        <Download className="w-4 h-4" />
      </button>
      <button className="p-1.5 rounded hover:bg-bg-hover" title="下载 SVG" data-testid="mermaid-download-svg" onClick={handleDownloadSvg}>
        <Download className="w-4 h-4" />
      </button>
      <button className="p-1.5 rounded hover:bg-bg-hover" title="复制源码" data-testid="mermaid-copy-source" onClick={handleCopySource}>
        <Copy className="w-4 h-4" />
      </button>
      <button className="p-1.5 rounded hover:bg-bg-hover" title="全屏" data-testid="mermaid-fullscreen" onClick={() => setFullscreen(true)}>
        <Expand className="w-4 h-4" />
      </button>
    </div>
  );

  if (error) {
    return (
      <div className="rounded border border-amber-300 dark:border-amber-700">
        {toolbar}
        <div className="p-3 bg-amber-50 dark:bg-amber-950 text-amber-700 dark:text-amber-300 text-sm">
          <strong>Mermaid 解析失败:</strong> {error}
        </div>
        <ShikiCodeBlock language="mermaid">{code}</ShikiCodeBlock>
      </div>
    );
  }

  if (loading) {
    return <div className="animate-pulse bg-bg-hover h-32 rounded" />;
  }

  if (showSource) {
    return (
      <div className="rounded border border-border">
        {toolbar}
        <textarea
          className="w-full h-64 p-2 font-mono text-sm bg-bg text-text border-0"
          value={code}
          readOnly
          data-testid="mermaid-source-textarea"
        />
      </div>
    );
  }

  const diagram = (
    <div
      ref={svgWrapperRef}
      className="overflow-hidden cursor-grab active:cursor-grabbing"
      onWheel={handleWheel}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerLeave={handlePointerUp}
    >
      <div
        ref={containerRef}
        style={{
          transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
          transformOrigin: 'center center',
        }}
        dangerouslySetInnerHTML={{ __html: svg }}
      />
    </div>
  );

  const content = (
    <div className="rounded border border-border bg-white dark:bg-bg">
      {toolbar}
      {diagram}
    </div>
  );

  if (fullscreen) {
    return createPortal(
      <div
        className="fixed inset-0 z-50 bg-black bg-opacity-80 flex items-center justify-center"
        onClick={() => setFullscreen(false)}
      >
        <div className="w-[90vw] h-[90vh] bg-white dark:bg-bg rounded shadow-lg flex flex-col" onClick={(e) => e.stopPropagation()}>
          {toolbar}
          <div className="flex-1 overflow-hidden">{diagram}</div>
        </div>
      </div>,
      document.body,
    );
  }

  return content;
}
```

- [ ] **Step 4: 运行测试验证通过**

```bash
npx vitest run src/widgets/chat/MermaidDiagram.test.tsx
```

预期：PASS。

- [ ] **Step 5: 重构 MermaidBlock.tsx 为薄包装**

```typescript
// src/widgets/chat/MermaidBlock.tsx (保留现有 audit 函数，改为调用 MermaidDiagram)
import { MermaidDiagram } from './MermaidDiagram';

export function MermaidBlock({ code, ...rest }: { code: string; [key: string]: unknown }) {
  // 主题检测逻辑保留
  const theme = useTheme(); // 伪代码，实际从 MermaidBlock 现有逻辑提取
  return <MermaidDiagram code={code} theme={theme} />;
}

// 保留现有 audit 函数不动
export function formatMermaidBlockAuditJson(...) { ... }
export function formatMermaidBlockAuditSnapshot(...) { ... }
```

实际重构时，需要把现有 `MermaidBlock.tsx` 的主题检测、加载状态、错误处理逻辑迁移到 `MermaidDiagram.tsx`，保留 audit 函数签名不变。

- [ ] **Step 6: 运行全量 Mermaid 测试验证无回归**

```bash
npx vitest run src/widgets/chat/MermaidBlock.test.tsx src/widgets/chat/MermaidBlock.toolbar.test.tsx src/widgets/chat/MermaidDiagram.test.tsx
```

预期：PASS。

- [ ] **Step 7: 提交**

```bash
git add src/widgets/chat/MermaidDiagram.tsx src/widgets/chat/MermaidDiagram.test.tsx src/widgets/chat/MermaidBlock.tsx
git commit -m "feat(mermaid): interactive diagram viewer with pan/zoom/source toggle/SVG export"
```

---

### Task 4: 技术文档更新（P2 归档）

**Files:**
- Modify: `docs/technical/124-markdown-renderer.md` (补充 Mermaid 交互章节)
- Modify: `docs/technical/38-artifacts-panel.md` (补充 HTML 预览工具条章节)

**Steps:**

- [ ] **Step 1: 更新 124-markdown-renderer.md**

在末尾追加：

```markdown
## Mermaid 交互图表（2026-11-04 新增）

`MermaidDiagram` 组件在原有渲染基础上增加：

- **平移**：鼠标拖拽（pointerdown → pointermove → pointerup）
- **缩放**：Ctrl+滚轮（0.4–3.0, step 1.25）、工具条 +/- 按钮
- **适应屏幕**：重置 zoom=1, pan=(0,0)
- **实际大小**：同适应屏幕（语义区分，未来可接 100% DPI）
- **源图切换**：textarea 只读展示源码
- **错误详情**：mermaid.parse 捕获，展示错误信息 + 源码回退
- **下载 PNG**：2× 分辨率
- **下载 SVG**：原始矢量
- **复制源码**：navigator.clipboard.writeText
- **全屏**：portal overlay，ESC/点击背景关闭

a11y：工具条按钮带 aria-label，SVG 容器 role="img"（待补充）。
```

- [ ] **Step 2: 更新 38-artifacts-panel.md**

在 HTML 预览相关章节追加：

```markdown
## HTML 预览工具条（2026-11-04 增强）

`HtmlPreviewHost` 统一宿主提供：

- **刷新**：内部 reloadKey++，重新挂载 iframe
- **全屏**：portal overlay
- **停止脚本**：卸载 iframe，展示"已停止执行脚本"
- **复制源码**：navigator.clipboard.writeText
- **下载 HTML**：Blob URL <a download>
- **错误桥接**：注入 `<script>` 捕获 window.onerror/unhandledrejection/console.error，postMessage 到父窗口，父窗口展示错误横幅

安全：iframe sandbox="allow-scripts"（无 allow-same-origin），referrerPolicy="no-referrer"。
```

- [ ] **Step 3: 提交**

```bash
git add docs/technical/124-markdown-renderer.md docs/technical/38-artifacts-panel.md
git commit -m "docs(technical): Mermaid interactive viewer + HTML preview toolbar"
```

---

### Task 5: 运行项目门禁（最终验证）

**Steps:**

- [ ] **Step 1: TypeScript 检查**

```bash
cd /home/fz/project/sage/.worktrees/feat-rich-preview-rendering
npm run typecheck
```

预期：PASS。

- [ ] **Step 2: 全量单测**

```bash
npx vitest run
```

预期：PASS，无新增失败。

- [ ] **Step 3: 架构行数检查**

```bash
node scripts/architecture-check.mjs
```

预期：PASS（新文件不计入 baseline，仅当超过阈值）。

- [ ] **Step 4: 字体大小检查**

```bash
node scripts/check-font-scale.mjs
```

预期：PASS。

- [ ] **Step 5: 生产构建**

```bash
npm run build
```

预期：PASS。

- [ ] **Step 6: 后端测试（如后端被改动）**

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/
```

预期：PASS（本次未改后端，可跳过）。

- [ ] **Step 7: 提交最终状态**

```bash
git status
git log --oneline | head -5
```

---

## 风险与依赖

| 风险 | 影响 | 缓解 |
|---|---|---|
| mermaid 11.x API 变更（`parse` 签名） | MermaidDiagram 错误详情失败 | 测试 mock parse；实际调用时 try-catch 兜底 |
| CSP 继承阻止 srcdoc 脚本（生产构建） | HTML 预览错误桥接失效 | 已在 vite.config.ts 注入 CSP；srcdoc 继承父 CSP，理论上允许 inline script；若失败，回退到不注入错误桥接 |
| 全屏 portal 与现有 fullscreen 冲突（如 MermaidBlock 已有） | 两个 portal 叠加 | 本方案移除 MermaidBlock 原有全屏逻辑，统一到 MermaidDiagram |
| Electron permission policy 破坏现有剪贴板/通知功能 | 用户无法复制/收到通知 | 白名单包含 clipboard-read/write, notifications；测试覆盖 |
| 架构行数棘轮因新文件超限 | CI Architecture 红 | 新文件不计入 baseline 仅当超过阈值；若超，拆分组件 |

---

## 未来工作（本次不实施）

- **分离源 HTML 预览宿主**：本地静态服务器 / `sage-preview://` 自定义协议 / BrowserView，解决 CSP 继承、`base-uri 'none'` 阻止相对资源、脚本保真度。
- **minimal-tier Mermaid**：Wiki 页支持 Mermaid 渲染。
- **Mermaid 懒渲染**：IntersectionObserver，长对话性能优化。
- **生成侧 Mermaid 提示**：system prompt 引导 LLM 生成符合 mermaid 语法的图表。
- **打包构建 CSP E2E 测试**：Playwright 启动打包后应用，验证 srcdoc 脚本执行。
