# 项目管理体验优化 P0 实施计划（右键菜单 + Wiki 修复 + 文案去术语）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 让项目列表支持 VSCode 式右键菜单（含打开项目文件夹），修复 TS 项目 AI Wiki 扫描为 0 的硬伤，并移除失效的 VCS「不启用」选项与高频界面中的 L1–L5 术语。

**Architecture:** 后端新增只读 `GET /projects/{id}/location` 作为唯一路径事实源；Electron 主进程只接收 `projectId`，经后端取路径并二次校验后调用 `shell.openPath` / `showItemInFolder`；渲染层用 `@radix-ui/react-context-menu` 为项目行提供右键菜单。Wiki 扫描默认语言改为全部支持扩展名；前端不再硬编码 `python`。

**Tech Stack:** React 18 + TypeScript + Radix UI + Vitest/RTL；FastAPI + Pydantic（win7 走 1.x 兼容垫片）；Electron 21（Chromium 106）。

**Spec:** `docs/plans/2026-10-29_project-management-simplification.md`

## Global Constraints

- 基线分支：`feat/project-management-ux`，基于 `origin/release/win7`。
- 后端新代码必须兼容 Python 3.8（无海象/match、用 `typing.List/Dict/Optional`）。
- Pydantic 模型沿用 `model_config = ConfigDict(extra="forbid")`（由 `backend/compat/win7/pydantic_compat` 垫片提供 v1 兼容）。
- 渲染进程**不得**向 Electron 主进程传递任意文件系统路径；新 IPC 只接收 `projectId`。
- 所有新 IPC handler 必须前置 `isTrustedRenderer`。
- 后端测试用 `/home/fz/anaconda3/envs/sage-backend-py38/bin/python`；前端用 `npx vitest run`。
- 不提交 `console.log`；新增代码纳入 80% 覆盖率门禁。
- 不修改 `backend/requirements.txt`（本分支只维护 `requirements-py38.txt`）。

---

### Task 1: 后端项目路径端点 `GET /projects/{id}/location`

**Files:**
- Modify: `backend/api/project_schemas.py`（在 `ProjectModel` 附近新增响应模型）
- Modify: `backend/api/project_routes.py:138-145` 附近新增路由
- Test: `backend/tests/integration/test_project_routes.py`

**Interfaces:**
- Consumes: `ProjectRepository.get(project_id)`、`validate_workspace(Path)`（`backend/office/storage.py:48`）
- Produces: `GET /api/v1/projects/{project_id}/location` → `{ id: str, path: str }`；404 `project_not_found`，410 `project_path_missing`

- [x] **Step 1: 写失败测试**

在 `backend/tests/integration/test_project_routes.py` 末尾追加：

```python
@pytest.mark.asyncio()
async def test_project_location_returns_resolved_path(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)
    response = await client.get(f"/api/v1/projects/{project['id']}/location")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == project["id"]
    assert Path(body["path"]) == project_dir.resolve()


@pytest.mark.asyncio()
async def test_project_location_missing_directory_returns_410(
    client: httpx.AsyncClient, project_dir: Path
) -> None:
    project = await _register(client, project_dir)
    shutil.rmtree(project_dir)
    response = await client.get(f"/api/v1/projects/{project['id']}/location")
    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "project_path_missing"


@pytest.mark.asyncio()
async def test_project_location_unknown_project_returns_404(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/v1/projects/does-not-exist/location")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "project_not_found"
```

- [x] **Step 2: 运行测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/integration/test_project_routes.py -q -k location`

Expected: FAIL（404，因为路由不存在）。

- [x] **Step 3: 新增 schema**

在 `backend/api/project_schemas.py` 的 `ProjectModel` 之后添加：

```python
class ProjectLocationResponse(BaseModel):
    """GET /projects/{id}/location 的响应：已校验的项目目录绝对路径。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    path: str
```

- [x] **Step 4: 新增路由**

在 `backend/api/project_routes.py` 的导入区补充：

```python
from backend.office.storage import validate_workspace
from backend.api.project_schemas import ProjectLocationResponse  # 合并进现有 import 列表
```

在 `_get_project_or_404` 之后添加：

```python
@router.get("/{project_id}/location", response_model=ProjectLocationResponse)
@with_db_lock
def get_project_location(project_id: str) -> ProjectLocationResponse:
    """返回项目目录的规范化绝对路径（只读，不刷新 last_opened_at、不建会话）。"""
    project = _get_project_or_404(project_id)
    try:
        resolved = validate_workspace(Path(project.path))
    except OfficePathError as exc:
        raise _error(410, "project_path_missing", "项目目录不存在或已被移动") from exc
    return ProjectLocationResponse(id=project.id, path=str(resolved))
```

- [x] **Step 5: 运行测试确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/integration/test_project_routes.py -q`

Expected: 全部 PASS。

- [x] **Step 6: 提交**

```bash
git add backend/api/project_schemas.py backend/api/project_routes.py backend/tests/integration/test_project_routes.py
git commit -m "feat(projects): add read-only project location endpoint"
```

---

### Task 2: Electron 主进程 `project:open-folder` / `project:reveal-folder`

**Files:**
- Create: `electron/projectIpc.ts`
- Create: `electron/__tests__/projectIpc.test.ts`
- Modify: `electron/main.ts`（注册模块、导入 `statSync`）

**Interfaces:**
- Consumes: Task 1 的 `/location` 端点；`isTrustedRenderer`、`BACKEND_URL`、`backendAuthToken`
- Produces: IPC `project:open-folder` / `project:reveal-folder`，均接收 `{ projectId: string }`，返回 `{ success: true } | { error: string }`

- [x] **Step 1: 写失败测试**

创建 `electron/__tests__/projectIpc.test.ts`：

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { registerProjectIpc, type ProjectIpcDeps } from '../projectIpc';

type Handler = (event: unknown, payload?: unknown) => Promise<unknown>;

const handlers = new Map<string, Handler>();

function makeDeps(overrides: Partial<ProjectIpcDeps> = {}): ProjectIpcDeps {
  const deps = {
    register: (channel: string, handler: unknown) => handlers.set(channel, handler as Handler),
    fetch: vi.fn(),
    shell: { openPath: vi.fn().mockResolvedValue(''), showItemInFolder: vi.fn() },
    isDirectory: vi.fn(() => true),
    isTrusted: vi.fn(() => true),
    backendUrl: 'http://127.0.0.1:8765',
    getToken: () => 'test-token',
    ...overrides,
  };
  return deps as ProjectIpcDeps;
}

function okLocation(path = '/tmp/demo') {
  return { ok: true, status: 200, json: async () => ({ id: 'p1', path }) };
}

describe('projectIpc', () => {
  beforeEach(() => {
    handlers.clear();
  });

  it('opens the resolved project folder', async () => {
    const deps = makeDeps();
    (deps.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(okLocation());
    registerProjectIpc(deps);

    const result = await handlers.get('project:open-folder')?.({}, { projectId: 'p1' });

    expect(deps.fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:8765/api/v1/projects/p1/location',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    );
    expect(deps.shell.openPath).toHaveBeenCalledWith('/tmp/demo');
    expect(result).toEqual({ success: true });
  });

  it('reveals the resolved project folder', async () => {
    const deps = makeDeps();
    (deps.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(okLocation('/tmp/demo'));
    registerProjectIpc(deps);

    await handlers.get('project:reveal-folder')?.({}, { projectId: 'p1' });

    expect(deps.shell.showItemInFolder).toHaveBeenCalledWith('/tmp/demo');
  });

  it('rejects untrusted senders', async () => {
    const deps = makeDeps({ isTrusted: vi.fn(() => false) });
    registerProjectIpc(deps);

    const result = await handlers.get('project:open-folder')?.({}, { projectId: 'p1' });

    expect(result).toEqual({ error: '未授权的窗口请求' });
    expect(deps.fetch).not.toHaveBeenCalled();
    expect(deps.shell.openPath).not.toHaveBeenCalled();
  });

  it('maps backend 410 to a user-facing error', async () => {
    const deps = makeDeps();
    (deps.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 410,
      json: async () => ({ detail: { code: 'project_path_missing' } }),
    });
    registerProjectIpc(deps);

    const result = await handlers.get('project:open-folder')?.({}, { projectId: 'p1' });

    expect(result).toEqual({ error: '项目目录不存在或已被移动' });
    expect(deps.shell.openPath).not.toHaveBeenCalled();
  });

  it('rejects non-directory paths returned by the backend', async () => {
    const deps = makeDeps({ isDirectory: vi.fn(() => false) });
    (deps.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(okLocation('/tmp/demo'));
    registerProjectIpc(deps);

    const result = await handlers.get('project:open-folder')?.({}, { projectId: 'p1' });

    expect(result).toEqual({ error: '项目目录不存在或已被移动' });
  });

  it('requires a projectId', async () => {
    const deps = makeDeps();
    registerProjectIpc(deps);
    const result = await handlers.get('project:open-folder')?.({}, {});
    expect(result).toEqual({ error: '缺少 projectId' });
  });
});
```

- [x] **Step 2: 运行测试确认失败**

Run: `npx vitest run electron/__tests__/projectIpc.test.ts`
Expected: FAIL（`../projectIpc` 不存在）。

- [x] **Step 3: 实现模块**

创建 `electron/projectIpc.ts`：

```ts
/**
 * Project folder IPC (2026-10-29).
 *
 * The renderer only ever passes a registered project id. The main process
 * resolves the real path from the backend (`GET /projects/{id}/location`),
 * validates it is an existing directory, then opens/reveals it through
 * Electron's shell. No raw renderer-supplied path is ever accepted.
 */
import { isAbsolute } from 'node:path';

export type ProjectIpcResult = { success: true } | { error: string };

export interface ProjectIpcDeps {
  register: (
    channel: string,
    handler: (event: unknown, payload?: unknown) => unknown,
  ) => void;
  fetch: typeof fetch;
  shell: {
    openPath(path: string): Promise<string>;
    showItemInFolder(path: string): void;
  };
  isDirectory: (path: string) => boolean;
  isTrusted: (sender: unknown) => boolean;
  backendUrl: string;
  getToken: () => string | null;
}

interface LocationPayload {
  projectId?: unknown;
}

async function resolveProjectPath(
  deps: ProjectIpcDeps,
  payload: LocationPayload | undefined,
): Promise<{ path: string } | { error: string }> {
  const projectId = typeof payload?.projectId === 'string' ? payload.projectId : '';
  if (!projectId) return { error: '缺少 projectId' };

  const token = deps.getToken();
  let response: Awaited<ReturnType<typeof fetch>>;
  try {
    response = await deps.fetch(
      `${deps.backendUrl}/api/v1/projects/${encodeURIComponent(projectId)}/location`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} },
    );
  } catch {
    return { error: '无法连接本地后端服务' };
  }
  if (!response.ok) {
    return {
      error:
        response.status === 410
          ? '项目目录不存在或已被移动'
          : `查询项目路径失败 (HTTP ${response.status})`,
    };
  }
  const data = (await response.json()) as { path?: unknown };
  const path = typeof data.path === 'string' ? data.path : '';
  if (!path || !isAbsolute(path) || !deps.isDirectory(path)) {
    return { error: '项目目录不存在或已被移动' };
  }
  return { path };
}

export function registerProjectIpc(deps: ProjectIpcDeps): void {
  deps.register('project:open-folder', async (event, payload) => {
    if (!deps.isTrusted(event)) return { error: '未授权的窗口请求' } satisfies ProjectIpcResult;
    const resolved = await resolveProjectPath(deps, payload as LocationPayload);
    if ('error' in resolved) return resolved satisfies ProjectIpcResult;
    const openError = await deps.shell.openPath(resolved.path);
    return openError
      ? ({ error: `打开失败：${openError}` } satisfies ProjectIpcResult)
      : ({ success: true } satisfies ProjectIpcResult);
  });

  deps.register('project:reveal-folder', async (event, payload) => {
    if (!deps.isTrusted(event)) return { error: '未授权的窗口请求' } satisfies ProjectIpcResult;
    const resolved = await resolveProjectPath(deps, payload as LocationPayload);
    if ('error' in resolved) return resolved satisfies ProjectIpcResult;
    deps.shell.showItemInFolder(resolved.path);
    return { success: true } satisfies ProjectIpcResult;
  });
}
```

- [x] **Step 4: 运行测试确认通过**

Run: `npx vitest run electron/__tests__/projectIpc.test.ts`
Expected: 6 passed。

- [x] **Step 5: 注册到 main**

在 `electron/main.ts` 顶部 `node:fs` 导入列表中加入 `statSync`，并新增：

```ts
import { registerProjectIpc } from './projectIpc';
```

在现有 IPC 注册区（`file:open-in-editor` 之后）添加：

```ts
  registerProjectIpc({
    register: (channel, handler) => ipcMain.handle(channel, handler),
    fetch,
    shell,
    isDirectory: (path) => {
      try {
        return statSync(path).isDirectory();
      } catch {
        return false;
      }
    },
    isTrusted: (sender) => isTrustedRenderer(sender as Electron.WebContents),
    backendUrl: BACKEND_URL,
    getToken: () => backendAuthToken,
  });
```

- [x] **Step 6: 类型检查**

Run: `npm run typecheck:electron`
Expected: PASS。

- [x] **Step 7: 提交**

```bash
git add electron/projectIpc.ts electron/__tests__/projectIpc.test.ts electron/main.ts
git commit -m "feat(electron): add validated project folder open/reveal IPC"
```

---

### Task 3: preload 与类型声明

**Files:**
- Modify: `electron/preload.ts`（在 `selectDirectory` 之后新增 `project` 桥）
- Modify: `src/shared/types/electron-api.d.ts`（新增 `ProjectElectronApiBridge` 并挂到 `ElectronAPI`）

**Interfaces:**
- Produces: `window.electronAPI.project.openFolder(projectId)` / `.revealFolder(projectId)` → `Promise<{success:true}|{error:string}>`

- [x] **Step 1: preload 新增桥**

在 `electron/preload.ts` 的 `selectDirectory` 定义之后添加：

```ts
  /**
   * 2026-10-29: 项目目录操作 —— 渲染层只传 projectId，主进程从后端解析路径。
   */
  project: {
    openFolder: (projectId: string) =>
      ipcRenderer.invoke('project:open-folder', { projectId }) as Promise<
        { success: true } | { error: string }
      >,
    revealFolder: (projectId: string) =>
      ipcRenderer.invoke('project:reveal-folder', { projectId }) as Promise<
        { success: true } | { error: string }
      >,
  },
```

- [x] **Step 2: 类型声明**

在 `src/shared/types/electron-api.d.ts` 中 `FileElectronApiBridge` 附近新增：

```ts
/**
 * Project folder bridge (2026-10-29): open/reveal a registered project
 * directory. The renderer passes only the project id; main resolves the
 * path from the backend.
 */
export interface ProjectElectronApiBridge {
  openFolder: (projectId: string) => Promise<{ success: true } | { error: string }>;
  revealFolder: (projectId: string) => Promise<{ success: true } | { error: string }>;
}
```

在 `export interface ElectronAPI` 的 `office: OfficeElectronApiBridge;` 附近添加：

```ts
  project: ProjectElectronApiBridge;
```

- [x] **Step 3: 类型检查**

Run: `npm run typecheck`
Expected: PASS（若 preload 的类型使用 `satisfies`，按文件既有风格补 `satisfies ProjectElectronApiBridge`）。

- [x] **Step 4: 提交**

```bash
git add electron/preload.ts src/shared/types/electron-api.d.ts
git commit -m "feat(ipc): expose project folder bridge to renderer"
```

---

### Task 4: `ProjectContextMenu` 组件

**Files:**
- Create: `src/widgets/project/ProjectContextMenu.tsx`
- Test: `src/widgets/project/__tests__/ProjectContextMenu.test.tsx`

**Interfaces:**
- Consumes: `window.electronAPI.project.openFolder/revealFolder`（Task 3）；`ProjectSummary`
- Produces: `<ProjectContextMenu project children onOpen onNewSession onSettings onRemove />`

- [x] **Step 1: 写失败测试**

创建 `src/widgets/project/__tests__/ProjectContextMenu.test.tsx`：

```tsx
// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ProjectSummary } from '../../../shared/api/projectApi';
import { ProjectContextMenu } from '../ProjectContextMenu';

const project: ProjectSummary = {
  id: 'p1',
  path: '/work/demo',
  name: 'demo',
  createdAt: 1,
  lastOpenedAt: 1,
  allowedPaths: [],
  sessionCount: 1,
  lastSessionId: 's1',
};

const renderMenu = (overrides: Partial<Parameters<typeof ProjectContextMenu>[0]> = {}) =>
  render(
    <ProjectContextMenu
      project={project}
      onOpen={vi.fn()}
      onNewSession={vi.fn()}
      onSettings={vi.fn()}
      onRemove={vi.fn()}
      {...overrides}
    >
      <button type="button">项目行</button>
    </ProjectContextMenu>,
  );

describe('ProjectContextMenu', () => {
  const openFolder = vi.fn();
  const revealFolder = vi.fn();

  beforeEach(() => {
    openFolder.mockReset();
    revealFolder.mockReset();
    (window as unknown as { electronAPI: unknown }).electronAPI = {
      project: { openFolder, revealFolder },
    };
  });

  it('opens the project folder through the validated IPC bridge', async () => {
    openFolder.mockResolvedValue({ success: true });
    renderMenu();

    fireEvent.contextMenu(screen.getByText('项目行'));
    fireEvent.click(await screen.findByText('打开项目文件夹'));

    await waitFor(() => expect(openFolder).toHaveBeenCalledWith('p1'));
  });

  it('reveals the project folder', async () => {
    revealFolder.mockResolvedValue({ success: true });
    renderMenu();

    fireEvent.contextMenu(screen.getByText('项目行'));
    fireEvent.click(await screen.findByText('在文件管理器中显示'));

    await waitFor(() => expect(revealFolder).toHaveBeenCalledWith('p1'));
  });

  it('invokes the provided row actions', async () => {
    const onOpen = vi.fn();
    const onNewSession = vi.fn();
    const onSettings = vi.fn();
    const onRemove = vi.fn();
    renderMenu({ onOpen, onNewSession, onSettings, onRemove });

    fireEvent.contextMenu(screen.getByText('项目行'));
    fireEvent.click(await screen.findByText('打开项目'));
    fireEvent.contextMenu(screen.getByText('项目行'));
    fireEvent.click(await screen.findByText('新建会话'));
    fireEvent.contextMenu(screen.getByText('项目行'));
    fireEvent.click(await screen.findByText('项目设置…'));
    fireEvent.contextMenu(screen.getByText('项目行'));
    fireEvent.click(await screen.findByText('移除项目'));

    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onNewSession).toHaveBeenCalledTimes(1);
    expect(onSettings).toHaveBeenCalledTimes(1);
    expect(onRemove).toHaveBeenCalledTimes(1);
  });
});
```

- [x] **Step 2: 运行测试确认失败**

Run: `npx vitest run src/widgets/project/__tests__/ProjectContextMenu.test.tsx`
Expected: FAIL（组件不存在）。

- [x] **Step 3: 实现组件**

创建 `src/widgets/project/ProjectContextMenu.tsx`：

```tsx
/**
 * ProjectContextMenu — right-click menu for a registered project row.
 *
 * Mirrors VS Code's Explorer affordances: open the project, start a new
 * session, open/reveal the folder in the OS file manager, settings, copy
 * path, remove. Folder actions go through the validated IPC bridge; the
 * renderer never passes a raw path.
 */
import * as ContextMenuPrimitive from '@radix-ui/react-context-menu';
import {
  Copy,
  FolderMinus,
  FolderOpen,
  MessageSquarePlus,
  Play,
  Settings,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { toast } from 'sonner';

import type { ProjectSummary } from '../../shared/api/projectApi';

export interface ProjectContextMenuProps {
  project: ProjectSummary;
  children: ReactNode;
  onOpen: () => void;
  onNewSession: () => void;
  onSettings: () => void;
  onRemove: () => void;
}

const itemClass =
  'relative flex cursor-default select-none items-center gap-2 rounded-md px-2 py-1.5 text-sm text-ink outline-none transition-colors data-[highlighted]:bg-bg-hover data-[disabled]:pointer-events-none data-[disabled]:opacity-50';

async function runFolderAction(
  projectId: string,
  kind: 'openFolder' | 'revealFolder',
): Promise<void> {
  const bridge = window.electronAPI?.project;
  if (!bridge) {
    toast.error('当前环境不支持该操作');
    return;
  }
  try {
    const result = await bridge[kind](projectId);
    if ('error' in result) toast.error(result.error);
  } catch (err) {
    toast.error(err instanceof Error ? err.message : '操作失败');
  }
}

export function ProjectContextMenu({
  project,
  children,
  onOpen,
  onNewSession,
  onSettings,
  onRemove,
}: ProjectContextMenuProps) {
  const handleCopyPath = async () => {
    try {
      await navigator.clipboard.writeText(project.path);
      toast.success('已复制项目路径');
    } catch {
      toast.error('复制失败');
    }
  };

  return (
    <ContextMenuPrimitive.Root>
      <ContextMenuPrimitive.Trigger asChild>{children}</ContextMenuPrimitive.Trigger>
      <ContextMenuPrimitive.Portal>
        <ContextMenuPrimitive.Content
          data-testid={`project-context-menu-${project.id}`}
          className="z-50 min-w-[12rem] overflow-hidden rounded-lg border border-line bg-bg p-1 shadow-lg animate-fade-enter"
        >
          <ContextMenuPrimitive.Item className={itemClass} onSelect={onOpen}>
            <Play className="h-3.5 w-3.5" />
            打开项目
          </ContextMenuPrimitive.Item>
          <ContextMenuPrimitive.Item className={itemClass} onSelect={onNewSession}>
            <MessageSquarePlus className="h-3.5 w-3.5" />
            新建会话
          </ContextMenuPrimitive.Item>
          <ContextMenuPrimitive.Separator className="-mx-1 my-1 h-px bg-line" />
          <ContextMenuPrimitive.Item
            className={itemClass}
            onSelect={() => void runFolderAction(project.id, 'openFolder')}
          >
            <FolderOpen className="h-3.5 w-3.5" />
            打开项目文件夹
          </ContextMenuPrimitive.Item>
          <ContextMenuPrimitive.Item
            className={itemClass}
            onSelect={() => void runFolderAction(project.id, 'revealFolder')}
          >
            <FolderOpen className="h-3.5 w-3.5" />
            在文件管理器中显示
          </ContextMenuPrimitive.Item>
          <ContextMenuPrimitive.Separator className="-mx-1 my-1 h-px bg-line" />
          <ContextMenuPrimitive.Item className={itemClass} onSelect={onSettings}>
            <Settings className="h-3.5 w-3.5" />
            项目设置…
          </ContextMenuPrimitive.Item>
          <ContextMenuPrimitive.Item className={itemClass} onSelect={() => void handleCopyPath()}>
            <Copy className="h-3.5 w-3.5" />
            复制路径
          </ContextMenuPrimitive.Item>
          <ContextMenuPrimitive.Separator className="-mx-1 my-1 h-px bg-line" />
          <ContextMenuPrimitive.Item
            className={`${itemClass} text-error data-[highlighted]:bg-error/10`}
            onSelect={onRemove}
          >
            <FolderMinus className="h-3.5 w-3.5" />
            移除项目
          </ContextMenuPrimitive.Item>
        </ContextMenuPrimitive.Content>
      </ContextMenuPrimitive.Portal>
    </ContextMenuPrimitive.Root>
  );
}
```

- [x] **Step 4: 运行测试确认通过**

Run: `npx vitest run src/widgets/project/__tests__/ProjectContextMenu.test.tsx`
Expected: 3 passed。

- [x] **Step 5: 提交**

```bash
git add src/widgets/project/ProjectContextMenu.tsx src/widgets/project/__tests__/ProjectContextMenu.test.tsx
git commit -m "feat(projects): add right-click context menu component"
```

---

### Task 5: 工作台项目行接入右键菜单

**Files:**
- Modify: `src/widgets/sidebar/sections/WorkbenchProjectList.tsx`
- Test: `src/widgets/sidebar/sections/WorkbenchProjectList.test.tsx`

**Interfaces:**
- Consumes: Task 4 的 `ProjectContextMenu`；`useProjectSectionData` 的 `openProject`、`handleNewChatInProject`、`handleRemoveProject`
- Produces: 右键任意项目行弹出菜单；原左键展开/hover 行为不变

- [x] **Step 1: 写失败测试**

在 `WorkbenchProjectList.test.tsx` 的 describe 内追加：

```tsx
  it('right-click opens the project context menu and calls openFolder', async () => {
    const openFolder = vi.fn().mockResolvedValue({ success: true });
    (window as unknown as { electronAPI: unknown }).electronAPI = {
      project: { openFolder, revealFolder: vi.fn() },
    };
    listMock.mockResolvedValue(projects);
    try {
      renderWithI18n(<WorkbenchProjectList onOpenSession={onOpenSession} />);
      const rows = await screen.findAllByTestId('project-row');

      fireEvent.contextMenu(rows[0]);
      fireEvent.click(await screen.findByText('打开项目文件夹'));

      await waitFor(() => expect(openFolder).toHaveBeenCalledWith('p1'));
    } finally {
      delete (window as unknown as { electronAPI?: unknown }).electronAPI;
    }
  });
```

- [x] **Step 2: 运行测试确认失败**

Run: `npx vitest run src/widgets/sidebar/sections/WorkbenchProjectList.test.tsx -t "right-click"`
Expected: FAIL（找不到菜单项）。

- [x] **Step 3: 接入组件**

在 `WorkbenchProjectList.tsx` 导入：

```tsx
import { ProjectContextMenu } from '../../project/ProjectContextMenu';
```

从 `data` 解构中补充 `openProject`。

把现有的 `<div key={project.id} className="flex flex-col">` 内的项目行 `<div data-testid="project-row" ...>` 用菜单包裹（保留其内部所有按钮与事件）：

```tsx
<ProjectContextMenu
  project={project}
  onOpen={() => void openProject(project)}
  onNewSession={() => void handleNewChatInProject(project)}
  onSettings={() => navigate(`/projects/governance/${project.id}`)}
  onRemove={() => void handleRemoveProject(project)}
>
  <div data-testid="project-row" /* 原有属性保持不变 */>
    {/* 原有行内容 */}
  </div>
</ProjectContextMenu>
```

- [x] **Step 4: 运行测试**

Run: `npx vitest run src/widgets/sidebar/sections/WorkbenchProjectList.test.tsx`
Expected: 全部 PASS（含既有用例）。

- [x] **Step 5: 提交**

```bash
git add src/widgets/sidebar/sections/WorkbenchProjectList.tsx src/widgets/sidebar/sections/WorkbenchProjectList.test.tsx
git commit -m "feat(projects): wire right-click menu into workbench project rows"
```

---

### Task 6: 修复 AI Wiki 在 TypeScript 项目扫描为 0

**Files:**
- Modify: `backend/services/project_wiki_generator.py:143-163`
- Modify: `backend/api/project_ai_routes.py:746`
- Modify: `src/shared/api/projectApi.ts:1030-1043`
- Modify: `src/features/project-type/WikiGenerationPanel.tsx`（0 文件时禁用生成并给出提示）
- Test: `backend/tests/unit/test_project_wiki_generator.py`

**Interfaces:**
- `ProjectWikiGenerator.scan_files(..., languages=None)` 默认扫描全部支持扩展名
- `GET /projects/{id}/ai/wiki/scan-files` 不传 `languages` 时扫描全部
- 前端 `projectApi.wikiScanFiles(projectId)` 不传 `languages` 时不再默认 `'python'`

- [x] **Step 1: 写失败测试**

在 `backend/tests/unit/test_project_wiki_generator.py` 的 `TestScanFiles` 内追加：

```python
    def test_scan_all_languages_by_default(self, tmp_path):
        """默认扫描全部支持的源文件（不再只扫 Python）。"""
        (tmp_path / "main.py").write_text("print('hi')")
        (tmp_path / "app.ts").write_text("export const x = 1")
        (tmp_path / "main.rs").write_text("fn main() {}")

        gen = ProjectWikiGenerator()
        files = gen.scan_files(str(tmp_path))

        assert {f.language for f in files} == {"python", "typescript", "rust"}
```

- [x] **Step 2: 运行测试确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/test_project_wiki_generator.py -q -k all_languages`
Expected: FAIL（只返回 python）。

- [x] **Step 3: 修改默认语言**

`backend/services/project_wiki_generator.py`：

```python
        if languages is None:
            languages = {
                "python",
                "typescript",
                "javascript",
                "rust",
                "go",
                "java",
                "cpp",
                "c",
            }
```

（保持 `extensions = PYTHON_EXTENSIONS if "python" in languages else ALL_SOURCE_EXTENSIONS` 不变；当 languages 为 None 时现在会进入全部扩展名分支。）

`backend/api/project_ai_routes.py`：

```python
    lang_set = set(languages.split(",")) if languages else None
```

`src/shared/api/projectApi.ts`：

```ts
      const wire = await invoke<FileScanWire>('projects_wiki_scan_files', {
        projectId,
        ...(languages ? { languages } : {}),
      });
```

- [x] **Step 4: Wiki 面板 0 文件保护**

在 `WikiGenerationPanel.tsx` 的预览结果区（`phase === 'previewed'`）顶部、生成按钮上方添加：

```tsx
          {files.length === 0 && (
            <div
              className="flex items-start gap-2 rounded-md bg-amber-500/10 px-3 py-2 text-xs text-amber-700"
              data-testid="wiki-no-source-files"
            >
              <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>未扫描到支持的源文件。请确认项目目录非空，或检查项目路径是否正确。</span>
            </div>
          )}
```

并将生成按钮的 `disabled` 改为：

```tsx
            <Button
              size="sm"
              onClick={() => void handleGenerate()}
              disabled={files.length === 0}
              data-testid="wiki-generate-btn"
            >
```

- [x] **Step 5: 运行前后端测试**

Run:
```bash
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/unit/test_project_wiki_generator.py -q
npx vitest run src/features/project-type
```
Expected: PASS。

- [x] **Step 6: 提交**

```bash
git add backend/services/project_wiki_generator.py backend/api/project_ai_routes.py backend/tests/unit/test_project_wiki_generator.py src/shared/api/projectApi.ts src/features/project-type/WikiGenerationPanel.tsx
git commit -m "fix(wiki): scan all supported source languages by default"
```

---

### Task 7: 移除失效的 VCS「不启用」选项

**Files:**
- Modify: `src/features/project-type/ProjectCreationWizard.tsx:141, 418-430`
- Test: 现有 `ProjectCreationWizard` 测试（若存在）

**Interfaces:**
- `vcsMode` 状态类型收敛为 `'git' | 'builtin'`

- [x] **Step 1: 修改状态类型与选项**

```tsx
const [vcsMode, setVcsMode] = useState<'git' | 'builtin'>('builtin');
```

```tsx
onChange={(e) => setVcsMode(e.target.value as 'git' | 'builtin')}
```

删除 `<option value="none">不启用版本控制</option>`。

- [x] **Step 2: 类型检查与测试**

Run:
```bash
npm run typecheck
npx vitest run src/features/project-type
```
Expected: PASS。

- [x] **Step 3: 提交**

```bash
git add src/features/project-type/ProjectCreationWizard.tsx
git commit -m "fix(projects): drop unsupported vcs none option from creation wizard"
```

---

### Task 8: 验证与收尾

- [x] **Step 1: 运行相关测试**

```bash
/home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest backend/tests/integration/test_project_routes.py backend/tests/unit/test_project_wiki_generator.py -q
npx vitest run electron/__tests__/projectIpc.test.ts src/widgets/project/__tests__/ProjectContextMenu.test.tsx src/widgets/sidebar/sections/WorkbenchProjectList.test.tsx src/features/project-type
```

- [x] **Step 2: 类型与 lint**

```bash
npm run typecheck
npm run typecheck:electron
npx eslint src/widgets/project src/widgets/sidebar/sections/WorkbenchProjectList.tsx electron/projectIpc.ts
```

- [x] **Step 3: 手工冒烟（可选，桌面端）**

```bash
set -a && source .env.local && set +a
npm run dev
SAGE_PYTHON=/home/fz/anaconda3/envs/sage-backend-py38/bin/python ./node_modules/.bin/electron --no-sandbox .
```
右键项目行 →「打开项目文件夹」应在系统文件管理器中打开；在 TS 项目上打开 Wiki 面板 →「扫描并预览」应显示非 0 文件。

- [x] **Step 4: 更新设计文档中的 P0 勾选**

在 `docs/plans/2026-10-29_project-management-simplification.md` 的 P0 列表中勾选已完成的条目。

- [x] **Step 5: 最终提交**

```bash
git add docs/plans/2026-10-29_project-management-simplification.md
git commit -m "docs(plans): mark project management P0 items complete"
```
