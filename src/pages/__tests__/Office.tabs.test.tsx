/**
 * Office — tab 信息架构测试 (2026-11 IA restructure)。
 *
 * 覆盖：
 *   - 默认 tab 是 `documents`，URL 无参数时显示 documents 面板；
 *   - 顶层 tab 切换把 URL 的 `tab` 参数同步到正确的值；
 *   - 深度链接 `?tab=generate` 直接落地对应 tab；
 *   - 未知 tab 值回落到 documents，避免空白面板；
 *   - TabContent 的 keep-alive：切换过的 panel 保持 mounted；
 *   - a11y：tablist / tab / tabpanel 角色与 aria 属性；
 *   - JournalPanel 在 generate tab 中折叠在 <details> 内；
 *   - 切回默认 tab 时 URL 中的 `tab` 参数被清掉。
 *
 * win7 说明：main 侧还有「审校与规范」「LaTeX」两个任务域，依赖尚未同步到
 * release/win7 的 Word 文档智能 / LaTeX 功能栈，因此这里只覆盖两个分区。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockBind = vi.fn();
const mockGet = vi.fn();
const mockRevoke = vi.fn();

vi.mock('../../shared/api/workspaceApi', () => ({
  workspaceApi: {
    bind: (...args: unknown[]) => mockBind(...args),
    get: (...args: unknown[]) => mockGet(...args),
    revoke: (...args: unknown[]) => mockRevoke(...args),
    setPreference: vi.fn().mockResolvedValue({ path: '/tmp', stored: true }),
    forgetPreference: vi.fn().mockResolvedValue({ cleared: true }),
    getDefault: vi.fn().mockResolvedValue({ path: null, source: 'scratch', isFallback: true }),
    getHealth: vi
      .fn()
      .mockResolvedValue({ path: '/tmp', health: 'healthy', detail: null, writable: true, isUsable: true }),
  },
}));

if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

// 各子面板都 stub 成 testid 容器，便于断言 "该 panel 已渲染"。
vi.mock('../../features/office', () => ({
  OfficeCapabilityBar: () => <div data-testid="office-capability-bar" />,
  OfficeDocumentList: () => <div data-testid="office-document-list" />,
  OfficeDuplicateDialog: () => null,
  OfficeIntake: ({ children }: { children?: ReactNode }) => (
    <div data-testid="office-intake">{children}</div>
  ),
  OfficeGenerateForm: () => <div data-testid="office-generate-form" />,
  OfficePreviewPanel: () => <div data-testid="office-preview-panel" />,
  useOfficeDocuments: () => ({
    documents: [],
    loading: false,
    error: null,
    refresh: vi.fn(),
    view: 'live',
    setView: vi.fn(),
    importAndReadMulti: vi.fn(),
    readDroppedMulti: vi.fn(),
    saveAs: vi.fn(),
    open: vi.fn(),
    showInFolder: vi.fn(),
    archiveDocument: vi.fn(),
    restoreDocument: vi.fn(),
    batchArchive: vi.fn(),
    batchRestore: vi.fn(),
    readDocument: vi.fn(),
    pendingDuplicate: null,
    resolvePendingDuplicate: vi.fn(),
  }),
}));

vi.mock('../../features/journal', () => ({
  JournalPanel: () => <div data-testid="office-journal-stub" />,
}));

import { SessionWorkspaceProvider } from '../../app/providers/SessionWorkspaceProvider';
import { I18nProvider } from '../../shared/lib/i18n';
import { useStore } from '../../shared/lib/store';
import { Office } from '../Office';

beforeEach(() => {
  mockBind.mockReset();
  mockGet.mockReset();
  mockRevoke.mockReset();
  mockGet.mockResolvedValue({
    binding: {
      sessionId: 'session-1',
      workspacePath: '/tmp/ws',
      generation: 1,
      activatedAt: 1,
      revokedAt: null,
    },
  });
  useStore.setState({ currentSessionId: 'session-1', sessions: [], messages: [] });
});

afterEach(() => {
  useStore.setState({ currentSessionId: null });
});

// 测试用的路由观察器 — 把 location.search 写到 DOM 上，断言深度链接
// 时可以直接读 `data-search`。
function LocationProbe() {
  const location = useLocation();
  return <span data-testid="location-probe" data-search={location.search} />;
}

function renderOffice(initialEntries: string[] = ['/office']) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <I18nProvider defaultLocale="zh">
        <SessionWorkspaceProvider>
          <Office />
          <LocationProbe />
        </SessionWorkspaceProvider>
      </I18nProvider>
    </MemoryRouter>,
  );
}

const probe = () => screen.getByTestId('location-probe');

// Radix Tabs 在 `onMouseDown` 时激活（不是 onClick），所以测试里必须
// 派发 mousedown 才能触发切换 —— 真实用户的鼠标序列天然包含这一步。
function activateTab(trigger: HTMLElement) {
  fireEvent.mouseDown(trigger, { button: 0, ctrlKey: false });
}

describe('Office — default tab and a11y roles', () => {
  it('lands on `documents` when no tab param is present', async () => {
    renderOffice();
    await waitFor(() => expect(screen.getByTestId('office-page')).toBeInTheDocument());
    expect(screen.getByTestId('office-panel-documents')).toBeInTheDocument();
    // 默认 URL 没有 tab 参数（默认值不写回 URL，避免污染书签）
    expect(probe().getAttribute('data-search')).toBe('');
    // tablist role + 2 triggers
    const tablist = screen.getByRole('tablist', { name: /文档|tabs|office/i });
    expect(tablist).toBeInTheDocument();
    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(2);
  });

  it('marks the active tab with aria-selected=true and its panel visible', async () => {
    renderOffice();
    await waitFor(() => screen.getByTestId('office-page'));
    const active = screen.getByTestId('office-tab-documents');
    expect(active.getAttribute('aria-selected')).toBe('true');
    // 非激活 panel 的 hidden 由我们控制
    expect(screen.getByTestId('office-panel-generate').getAttribute('hidden')).not.toBeNull();
  });
});

describe('Office — tab switching syncs URL', () => {
  it('clicking the generate trigger updates ?tab=generate and renders JournalPanel', async () => {
    renderOffice();
    await waitFor(() => screen.getByTestId('office-page'));
    activateTab(screen.getByTestId('office-tab-generate'));
    await waitFor(() =>
      expect(probe().getAttribute('data-search')).toBe('?tab=generate'),
    );
    expect(screen.getByTestId('office-generate-form')).toBeInTheDocument();
    expect(screen.getByTestId('office-journal-stub')).toBeInTheDocument();
    expect(screen.getByTestId('office-panel-generate').getAttribute('hidden')).toBeNull();
  });

  it('switching back to the default tab clears the `tab` param from the URL', async () => {
    renderOffice(['/office?tab=generate']);
    await waitFor(() => screen.getByTestId('office-page'));
    expect(probe().getAttribute('data-search')).toBe('?tab=generate');
    activateTab(screen.getByTestId('office-tab-documents'));
    await waitFor(() =>
      expect(probe().getAttribute('data-search')).toBe(''),
    );
  });
});

describe('Office — deep links', () => {
  it('?tab=generate deep link activates the generate tab on mount', async () => {
    renderOffice(['/office?tab=generate']);
    await waitFor(() => screen.getByTestId('office-page'));
    const active = screen.getByTestId('office-tab-generate');
    expect(active.getAttribute('aria-selected')).toBe('true');
    expect(screen.getByTestId('office-panel-generate').getAttribute('hidden')).toBeNull();
    expect(screen.getByTestId('office-generate-form')).toBeInTheDocument();
  });

  it('?tab=bogus falls back to documents so the page is never blank', async () => {
    renderOffice(['/office?tab=bogus']);
    await waitFor(() => screen.getByTestId('office-page'));
    expect(screen.getByTestId('office-tab-documents').getAttribute('aria-selected')).toBe('true');
    expect(screen.getByTestId('office-panel-documents').getAttribute('hidden')).toBeNull();
  });
});

describe('Office — keep-alive behaviour', () => {
  it('switching away from generate keeps the generate panel mounted (hidden)', async () => {
    renderOffice();
    await waitFor(() => screen.getByTestId('office-page'));
    activateTab(screen.getByTestId('office-tab-generate'));
    await waitFor(() => expect(screen.getByTestId('office-generate-form')).toBeInTheDocument());
    activateTab(screen.getByTestId('office-tab-documents'));
    await waitFor(() =>
      expect(screen.getByTestId('office-tab-documents').getAttribute('aria-selected')).toBe('true'),
    );
    const hiddenPanel = screen.getByTestId('office-panel-generate');
    expect(hiddenPanel.getAttribute('hidden')).not.toBeNull();
    expect(screen.queryByTestId('office-generate-form')).toBeInTheDocument();
  });
});

describe('Office — journal in generate tab is collapsed by default', () => {
  it('renders JournalPanel inside a collapsed <details> element', async () => {
    renderOffice(['/office?tab=generate']);
    await waitFor(() => screen.getByTestId('office-page'));
    const details = screen
      .getByTestId('office-generate-form')
      .parentElement!.querySelector('details');
    expect(details).not.toBeNull();
    expect(details!.hasAttribute('open')).toBe(false);
    expect(screen.getByTestId('office-journal-stub')).toBeInTheDocument();
  });
});

describe('Office — keyboard navigation', () => {
  it('Enter on a tab trigger activates that tab', async () => {
    renderOffice();
    await waitFor(() => screen.getByTestId('office-page'));
    const trigger = screen.getByTestId('office-tab-generate');
    trigger.focus();
    fireEvent.keyDown(trigger, { key: 'Enter' });
    await waitFor(() =>
      expect(probe().getAttribute('data-search')).toBe('?tab=generate'),
    );
  });
});
