/**
 * /office 文档库 portal —— 页面侧行为。
 *
 * 覆盖：
 *   - 有侧栏 slot 时文档库挂进侧栏，页面不再渲染 office-layout-left；
 *   - generate / rules 深链下侧栏文档库依然存在（portal 挂在页面根节点）；
 *   - 无 slot（侧栏折叠 / 无 Layout 测试环境）回退 OfficeLayout 两栏；
 *   - 在非 documents tab 点击侧栏文档会切回 documents。
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useCallback } from 'react';
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
    getHealth: vi.fn().mockResolvedValue({
      path: '/tmp',
      health: 'healthy',
      detail: null,
      writable: true,
      isUsable: true,
    }),
  },
}));

if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

vi.mock('../../features/office', () => ({
  OfficeDocumentList: ({ onPreview }: { onPreview: (id: string) => void }) => (
    <button data-testid="office-document-list" onClick={() => onPreview('doc-1')}>
      doc
    </button>
  ),
  OfficeDuplicateDialog: () => null,
  OfficeEditPreviewDialog: () => null,
  OfficeSnapshotPanel: () => null,
  GenerateWorkspace: () => <div data-testid="office-generate-workspace" />,
  RulesWorkspace: () => <div data-testid="office-rules-workspace" />,
  useOfficeDocuments: () => ({
    documents: [{ id: 'doc-1', doc_type: 'word', title: '示例文档' }],
    loading: false,
    error: null,
    refresh: vi.fn(),
    view: 'live',
    setView: vi.fn(),
    q: '',
    setQ: vi.fn(),
    docType: 'all',
    setDocType: vi.fn(),
    sort: 'updated_desc',
    setSort: vi.fn(),
    duplicateGroups: [],
    archiveAllButNewest: vi.fn(),
    importAndReadMulti: vi.fn(),
    readDroppedMulti: vi.fn(),
    saveAs: vi.fn(),
    open: vi.fn(),
    showInFolder: vi.fn(),
    archiveDocument: vi.fn(),
    restoreDocument: vi.fn(),
    batchArchive: vi.fn(),
    batchRestore: vi.fn(),
    readDocument: vi.fn().mockResolvedValue({ summary: {} }),
    pendingDuplicate: null,
    resolvePendingDuplicate: vi.fn(),
  }),
}));

vi.mock('../../features/office/canvas/DocumentCanvas', () => ({
  DocumentCanvas: () => <div data-testid="document-canvas-stub" />,
}));
vi.mock('../office/OfficeLatexTab', () => ({
  OfficeLatexTab: () => <div data-testid="office-latex-tab-stub" />,
}));
vi.mock('../../features/office/WordRuleExtractionPanel', () => ({
  WordRuleExtractionPanel: () => <div data-testid="office-rules-stub" />,
}));
vi.mock('../../features/journal', () => ({
  JournalPanel: () => <div data-testid="office-journal-stub" />,
}));

import { SessionWorkspaceProvider } from '../../app/providers/SessionWorkspaceProvider';
import { I18nProvider } from '../../shared/lib/i18n';
import { useStore } from '../../shared/lib/store';
import { SidebarSlotProvider, useSidebarSlot } from '../../widgets/layout/SidebarSlotProvider';
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

function LocationProbe() {
  const location = useLocation();
  return <span data-testid="location-probe" data-search={location.search} />;
}

// 模拟 Sidebar 内容列里的 slot 容器：挂载时把 DOM 节点交给 Provider。
function SlotHost() {
  const { setSlotEl } = useSidebarSlot();
  const attach = useCallback((el: HTMLDivElement | null) => setSlotEl(el), [setSlotEl]);
  return <div data-testid="test-slot" ref={attach} />;
}

function renderOffice(options: { withSlot: boolean; initialEntries?: string[] }) {
  const { withSlot, initialEntries = ['/office'] } = options;
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <I18nProvider defaultLocale="zh">
        <SessionWorkspaceProvider>
          <SidebarSlotProvider>
            {withSlot && <SlotHost />}
            <Office />
            <LocationProbe />
          </SidebarSlotProvider>
        </SessionWorkspaceProvider>
      </I18nProvider>
    </MemoryRouter>,
  );
}

const probe = () => screen.getByTestId('location-probe');

async function waitForTabs() {
  await waitFor(() => expect(screen.getByTestId('office-tab-documents')).toBeInTheDocument());
}

describe('Office — 侧栏文档库 portal', () => {
  it('有 slot 时文档库挂进侧栏，页面不再渲染 office-layout-left', async () => {
    renderOffice({ withSlot: true });
    await waitForTabs();

    await waitFor(() => expect(screen.getByTestId('office-sidebar-library')).toBeInTheDocument());
    const slot = screen.getByTestId('test-slot');
    expect(slot).toContainElement(screen.getByTestId('office-sidebar-library'));
    expect(screen.queryByTestId('office-layout-left')).toBeNull();
    expect(screen.getByTestId('document-canvas-stub')).toBeInTheDocument();
  });

  it('generate 深链下侧栏文档库依然存在（portal 挂在页面根节点）', async () => {
    renderOffice({ withSlot: true, initialEntries: ['/office?tab=generate'] });
    await waitForTabs();

    expect(screen.getByTestId('office-generate-workspace')).toBeInTheDocument();
    expect(screen.getByTestId('office-sidebar-library')).toBeInTheDocument();
    expect(screen.getByTestId('test-slot')).toContainElement(
      screen.getByTestId('office-sidebar-library'),
    );
  });

  it('无 slot（侧栏折叠 / 无 Layout 环境）回退 OfficeLayout 两栏', async () => {
    renderOffice({ withSlot: false });
    await waitForTabs();

    expect(screen.queryByTestId('office-sidebar-library')).toBeNull();
    expect(screen.getByTestId('office-layout-left')).toContainElement(
      screen.getByTestId('office-document-list'),
    );
  });

  it('在 generate tab 点击侧栏文档会切回 documents', async () => {
    renderOffice({ withSlot: true, initialEntries: ['/office?tab=generate'] });
    await waitForTabs();
    expect(probe().getAttribute('data-search')).toBe('?tab=generate');

    fireEvent.click(screen.getByTestId('office-document-list'));

    await waitFor(() => expect(probe().getAttribute('data-search')).toBe(''));
    expect(screen.getByTestId('office-panel-documents').getAttribute('hidden')).toBeNull();
  });
});
