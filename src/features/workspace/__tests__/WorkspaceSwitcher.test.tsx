/**
 * WorkspaceSwitcher — 工作区切换器 (2026-10-29, P2) 单测。
 *
 * 覆盖取代 ProjectBadge 后的行为：chip 徽标（名称 / 类型 / 阶段 / VCS / 来源）、
 * 健康圆点、复制路径、工作台入口，以及下拉浮层里的切换流程
 * （bind 会话 + 写入偏好 + refresh）。
 *
 * jsdom 缺少 Radix Popover 依赖的若干浏览器 API（ResizeObserver / 指针捕获 /
 * scrollIntoView / rAF），在此就地补桩；打开浮层用 pointerDown + click。
 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ComponentProps } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ProjectSummary } from '../../../shared/api/projectApi';
import { I18nProvider } from '../../../shared/lib/i18n';
import { WorkspaceSwitcher } from '../WorkspaceSwitcher';

const {
  mockList,
  mockGetDefault,
  mockGetHealth,
  mockBind,
  mockSetPreference,
  mockRefresh,
  mockToastSuccess,
  mockToastError,
  mockWriteText,
} = vi.hoisted(() => ({
  mockList: vi.fn(),
  mockGetDefault: vi.fn(),
  mockGetHealth: vi.fn(),
  mockBind: vi.fn(),
  mockSetPreference: vi.fn(),
  mockRefresh: vi.fn(),
  mockToastSuccess: vi.fn(),
  mockToastError: vi.fn(),
  mockWriteText: vi.fn(),
}));

vi.mock('../../../shared/api/projectApi', () => ({
  projectApi: { list: mockList },
}));

vi.mock('../../../shared/api/workspaceApi', () => ({
  workspaceApi: {
    getDefault: mockGetDefault,
    getHealth: mockGetHealth,
    bind: mockBind,
    setPreference: mockSetPreference,
  },
}));

vi.mock('../../../shared/lib/workspaceContext', () => ({
  useOptionalWorkspaceContext: () => ({ refresh: mockRefresh }),
}));

vi.mock('sonner', () => ({
  toast: { success: mockToastSuccess, error: mockToastError },
}));

// --- jsdom 补桩：Radix Popover / floating-ui 依赖的浏览器 API ---
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
Object.defineProperty(globalThis, 'ResizeObserver', {
  configurable: true,
  writable: true,
  value: ResizeObserverStub,
});

if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
}
if (!Element.prototype.setPointerCapture) {
  Element.prototype.setPointerCapture = () => {};
}
if (!Element.prototype.releasePointerCapture) {
  Element.prototype.releasePointerCapture = () => {};
}
if (typeof window.requestAnimationFrame !== 'function') {
  window.requestAnimationFrame = (callback: FrameRequestCallback) =>
    setTimeout(() => callback(Date.now()), 0) as unknown as number;
  window.cancelAnimationFrame = (handle: number) => clearTimeout(handle);
}

const WORKSPACE = '/tmp/sage-workspace';

function makeProject(overrides: Partial<ProjectSummary> = {}): ProjectSummary {
  return {
    id: 'p1',
    path: WORKSPACE,
    name: 'Contract2026',
    createdAt: 0,
    lastOpenedAt: 0,
    sessionCount: 1,
    lastSessionId: null,
    allowedPaths: [],
    ...overrides,
  };
}

/** 渲染并冲刷 mount 后的异步 effect，避免 act() 警告。 */
async function renderSwitcher(
  props: Partial<ComponentProps<typeof WorkspaceSwitcher>> = {},
) {
  const result = render(
    <I18nProvider defaultLocale="zh">
      <WorkspaceSwitcher workspacePath={WORKSPACE} {...props} />
    </I18nProvider>,
  );
  await act(async () => {});
  return result;
}

async function openPopover(): Promise<HTMLElement> {
  const trigger = screen.getByTestId('workspace-switcher-trigger');
  fireEvent.pointerDown(trigger);
  fireEvent.click(trigger);
  return screen.findByTestId('workspace-switcher-health-label');
}

beforeEach(() => {
  vi.clearAllMocks();
  mockList.mockResolvedValue([]);
  mockGetDefault.mockResolvedValue({
    path: WORKSPACE,
    source: 'project',
    isFallback: false,
  });
  mockGetHealth.mockResolvedValue({
    path: WORKSPACE,
    health: 'healthy',
    detail: null,
    writable: true,
    isUsable: true,
  });
  mockBind.mockResolvedValue({ binding: null });
  mockSetPreference.mockResolvedValue({ path: WORKSPACE, stored: true });
  mockRefresh.mockResolvedValue(undefined);
  mockWriteText.mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: mockWriteText },
  });
});

describe('WorkspaceSwitcher', () => {
  it('renders nothing and skips lookups when no workspace is bound', async () => {
    const { container } = await renderSwitcher({ workspacePath: null });

    expect(container).toBeEmptyDOMElement();
    expect(mockList).not.toHaveBeenCalled();
    expect(mockGetHealth).not.toHaveBeenCalled();
  });

  it('shows the registered project name, badges and full-path title', async () => {
    mockList.mockResolvedValue([
      makeProject({ projectType: 'business', projectStage: 'execution', vcsMode: 'builtin' }),
    ]);

    await renderSwitcher();

    await waitFor(() =>
      expect(screen.getByTestId('workspace-switcher-type-badge')).toHaveTextContent(
        '一般档案与文书',
      ),
    );
    expect(screen.getByText('Contract2026')).toBeInTheDocument();
    expect(screen.getByTestId('workspace-switcher-stage-badge')).toHaveTextContent('文书编制');
    expect(screen.getByTestId('workspace-switcher-vcs-badge')).toHaveTextContent('快照');
    expect(screen.getByTestId('workspace-switcher-source-badge')).toHaveTextContent('项目');
    expect(screen.getByTestId('workspace-switcher-trigger')).toHaveAttribute('title', WORKSPACE);
  });

  it('falls back to the path basename for an unregistered workspace', async () => {
    mockList.mockResolvedValue([]);
    mockGetDefault.mockResolvedValue({
      path: '/tmp/not-registered',
      source: 'session_binding',
      isFallback: false,
    });

    await renderSwitcher({ workspacePath: '/tmp/not-registered' });

    await waitFor(() => expect(screen.getByText('not-registered')).toBeInTheDocument());
    expect(screen.queryByTestId('workspace-switcher-type-badge')).toBeNull();
    expect(screen.getByTestId('workspace-switcher-source-badge')).toHaveTextContent('会话绑定');
  });

  it('still renders a usable chip when the project list request fails', async () => {
    mockList.mockRejectedValue(new Error('offline'));

    await renderSwitcher({ workspacePath: '/tmp/fallback-name' });

    await waitFor(() => expect(screen.getByText('fallback-name')).toBeInTheDocument());
    expect(screen.getByTestId('workspace-switcher-trigger')).toBeInTheDocument();
  });

  it.each([
    ['healthy', 'bg-emerald-500'],
    ['read_only', 'bg-amber-500'],
    ['missing', 'bg-red-500'],
  ])('reflects health=%s on the chip dot', async (health, dotClass) => {
    mockGetHealth.mockResolvedValue({
      path: WORKSPACE,
      health,
      detail: null,
      writable: health === 'healthy',
      isUsable: health !== 'missing',
    });

    await renderSwitcher();

    await waitFor(() =>
      expect(screen.getByTestId('workspace-switcher-health-dot').className).toContain(dotClass),
    );
  });

  it('copies the workspace path', async () => {
    await renderSwitcher();

    fireEvent.click(screen.getByTestId('workspace-switcher-copy-path-btn'));

    await waitFor(() => expect(mockWriteText).toHaveBeenCalledWith(WORKSPACE));
  });

  it('invokes the workbench callback', async () => {
    const onOpenWorkbench = vi.fn();
    await renderSwitcher({ onOpenWorkbench });

    fireEvent.click(screen.getByTestId('workspace-switcher-workbench-btn'));

    expect(onOpenWorkbench).toHaveBeenCalledTimes(1);
  });

  it('opens the popover and reports the health detail', async () => {
    mockGetHealth.mockResolvedValue({
      path: WORKSPACE,
      health: 'read_only',
      detail: '只读目录',
      writable: false,
      isUsable: true,
    });

    await renderSwitcher();
    const healthLabel = await openPopover();

    expect(healthLabel).toHaveTextContent('只读');
    expect(screen.getByText('· 只读目录')).toBeInTheDocument();
  });

  it('switches workspace: binds the session, remembers the preference and refreshes', async () => {
    const other = makeProject({ id: 'p2', path: '/tmp/other', name: 'Other' });
    mockList.mockResolvedValue([makeProject(), other]);

    await renderSwitcher({ sessionId: 'sess-1' });
    await waitFor(() => expect(screen.getByText('Contract2026')).toBeInTheDocument());

    await openPopover();
    const options = await screen.findAllByTestId('workspace-switcher-option');
    expect(options).toHaveLength(2);
    fireEvent.click(options[1]);

    await waitFor(() => expect(mockBind).toHaveBeenCalledWith('sess-1', '/tmp/other'));
    expect(mockSetPreference).toHaveBeenCalledWith('/tmp/other');
    expect(mockRefresh).toHaveBeenCalled();
    expect(mockToastSuccess).toHaveBeenCalledWith('已切换工作区');
  });

  it('skips session binding when no session is active', async () => {
    mockList.mockResolvedValue([
      makeProject(),
      makeProject({ id: 'p2', path: '/tmp/other', name: 'Other' }),
    ]);

    await renderSwitcher({ sessionId: null });
    await waitFor(() => expect(screen.getByText('Contract2026')).toBeInTheDocument());

    await openPopover();
    const options = await screen.findAllByTestId('workspace-switcher-option');
    fireEvent.click(options[1]);

    await waitFor(() => expect(mockSetPreference).toHaveBeenCalledWith('/tmp/other'));
    expect(mockBind).not.toHaveBeenCalled();
  });

  it('reports a failure toast when switching fails', async () => {
    mockList.mockResolvedValue([
      makeProject(),
      makeProject({ id: 'p2', path: '/tmp/other', name: 'Other' }),
    ]);
    mockBind.mockRejectedValue(new Error('绑定失败'));

    await renderSwitcher({ sessionId: 'sess-1' });
    await waitFor(() => expect(screen.getByText('Contract2026')).toBeInTheDocument());

    await openPopover();
    const options = await screen.findAllByTestId('workspace-switcher-option');
    fireEvent.click(options[1]);

    await waitFor(() => expect(mockToastError).toHaveBeenCalledWith('绑定失败'));
    expect(mockToastSuccess).not.toHaveBeenCalled();
  });

  it('warns when the current workspace is a scratch directory', async () => {
    mockGetDefault.mockResolvedValue({
      path: WORKSPACE,
      source: 'scratch',
      isFallback: true,
    });

    await renderSwitcher();
    await openPopover();

    expect(await screen.findByTestId('workspace-switcher-scratch-hint')).toHaveTextContent(
      '当前使用的是草稿目录',
    );
  });

  it('shows an unusable warning when the workspace is missing', async () => {
    mockGetHealth.mockResolvedValue({
      path: WORKSPACE,
      health: 'missing',
      detail: 'ENOENT',
      writable: false,
      isUsable: false,
    });

    await renderSwitcher();
    await openPopover();

    expect(await screen.findByTestId('workspace-switcher-unusable-warning')).toHaveTextContent(
      '当前工作区不可用',
    );
  });
});
