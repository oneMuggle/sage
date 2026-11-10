import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactElement } from 'react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';

const mockListReferences = vi.fn();
const mockCreateReference = vi.fn();
const mockDeleteReference = vi.fn();
const mockScanProject = vi.fn();
const mockConfirmDialog = vi.fn();

vi.mock('../../../shared/api', () => ({
  projectApi: {
    listReferences: (...args: unknown[]) => mockListReferences(...args),
    createReference: (...args: unknown[]) => mockCreateReference(...args),
    deleteReference: (...args: unknown[]) => mockDeleteReference(...args),
    scanProject: (...args: unknown[]) => mockScanProject(...args),
  },
}));

vi.mock('../../../shared/ui/ConfirmDialog/confirmService', () => ({
  confirmDialog: (...args: unknown[]) => mockConfirmDialog(...args),
}));

import type { ProjectReference } from '../../../shared/api';
import { ReferenceManager } from '../ReferenceManager';

const PROJECT_ID = 'project-abc';

// 共享 Radix Select 依赖 jsdom 未实现的指针捕获与滚动 API。
beforeAll(() => {
  window.HTMLElement.prototype.hasPointerCapture = vi.fn(() => false);
  window.HTMLElement.prototype.setPointerCapture = vi.fn();
  window.HTMLElement.prototype.releasePointerCapture = vi.fn();
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
  if (typeof globalThis.ResizeObserver === 'undefined') {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
  }
});

function renderManager(ui: ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>);
}

function makeRef(overrides: Partial<ProjectReference> = {}): ProjectReference {
  return {
    id: 'ref-1',
    projectId: PROJECT_ID,
    aliasName: 'cases',
    relPath: 'data/cases',
    targetPath: '/home/user/external/cases',
    kind: 'directory',
    createdAt: 1700000000000,
    ...overrides,
  };
}

describe('ReferenceManager', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListReferences.mockResolvedValue([]);
    mockCreateReference.mockImplementation(async (_projectId: string, input: unknown) => ({
      id: 'ref-new',
      projectId: PROJECT_ID,
      aliasName: 'new',
      kind: 'directory',
      createdAt: Date.now(),
      ...(input as Partial<ProjectReference>),
    }));
    mockDeleteReference.mockResolvedValue(undefined);
    mockScanProject.mockResolvedValue(undefined);
    mockConfirmDialog.mockResolvedValue(true);
  });

  afterEach(() => {
    cleanup();
  });

  it('renders the empty-state placeholder when no references exist', async () => {
    renderManager(<ReferenceManager projectId={PROJECT_ID} />);

    await waitFor(() => {
      expect(screen.getByTestId('reference-list-empty')).toBeInTheDocument();
    });
    expect(mockListReferences).toHaveBeenCalledWith(PROJECT_ID);
  });

  it('renders a list of references when API returns items', async () => {
    const refA = makeRef({ id: 'ref-a', aliasName: 'alpha' });
    const refB = makeRef({ id: 'ref-b', aliasName: 'beta', kind: 'file' });
    mockListReferences.mockResolvedValue([refA, refB]);

    renderManager(<ReferenceManager projectId={PROJECT_ID} />);

    await waitFor(() => {
      expect(screen.getByTestId('reference-row-ref-a')).toBeInTheDocument();
    });
    expect(screen.getByTestId('reference-row-ref-b')).toBeInTheDocument();
    expect(screen.queryByTestId('reference-list-empty')).not.toBeInTheDocument();
  });

  it('disables the create button when required fields are empty', async () => {
    renderManager(<ReferenceManager projectId={PROJECT_ID} />);

    await waitFor(() => {
      expect(screen.getByTestId('reference-list-empty')).toBeInTheDocument();
    });

    const createButton = screen.getByTestId('reference-create-button');
    expect(createButton).toBeDisabled();
  });

  it('submits the create form and reloads the list', async () => {
    const created = makeRef({ id: 'ref-new', aliasName: 'cases' });
    mockCreateReference.mockResolvedValue(created);
    mockListReferences.mockResolvedValueOnce([]).mockResolvedValueOnce([created]);

    renderManager(<ReferenceManager projectId={PROJECT_ID} />);

    await waitFor(() => {
      expect(screen.getByTestId('reference-list-empty')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId('reference-input-rel-path'), {
      target: { value: 'data/cases' },
    });
    fireEvent.change(screen.getByTestId('reference-input-target-path'), {
      target: { value: '/home/user/external/cases' },
    });
    fireEvent.change(screen.getByTestId('reference-input-alias'), {
      target: { value: 'cases' },
    });

    const createButton = screen.getByTestId('reference-create-button');
    expect(createButton).not.toBeDisabled();
    fireEvent.click(createButton);

    await waitFor(() => {
      expect(mockCreateReference).toHaveBeenCalledWith(PROJECT_ID, {
        relPath: 'data/cases',
        targetPath: '/home/user/external/cases',
        kind: 'directory',
        aliasName: 'cases',
      });
    });

    await waitFor(() => {
      expect(screen.getByTestId('reference-row-ref-new')).toBeInTheDocument();
    });
  });

  it('shows the localized kind label on the trigger and submits the selected kind', async () => {
    renderManager(<ReferenceManager projectId={PROJECT_ID} />);

    await waitFor(() => {
      expect(screen.getByTestId('reference-list-empty')).toBeInTheDocument();
    });

    const kindTrigger = screen.getByTestId('reference-input-kind');
    expect(kindTrigger).toHaveTextContent('文件夹');

    fireEvent.pointerDown(kindTrigger, { button: 0, pointerType: 'mouse' });
    const fileOption = await screen.findByRole('option', { name: '文件' });
    const mouseAt = { button: 0, pointerType: 'mouse', clientX: 100, clientY: 100 };
    fireEvent.pointerDown(fileOption, mouseAt);
    fireEvent.pointerMove(fileOption, mouseAt);
    fireEvent.pointerUp(fileOption, mouseAt);

    await waitFor(() => {
      expect(screen.getByTestId('reference-input-kind')).toHaveTextContent('文件');
    });

    fireEvent.change(screen.getByTestId('reference-input-rel-path'), {
      target: { value: 'data/cases' },
    });
    fireEvent.change(screen.getByTestId('reference-input-target-path'), {
      target: { value: '/home/user/external/cases' },
    });
    fireEvent.click(screen.getByTestId('reference-create-button'));

    await waitFor(() => {
      expect(mockCreateReference).toHaveBeenCalledWith(
        PROJECT_ID,
        expect.objectContaining({ kind: 'file' }),
      );
    });
  });

  it('calls scanProject and reloads when rescan is clicked', async () => {
    const discovered = makeRef({ id: 'ref-disc', aliasName: 'discovered' });
    mockListReferences.mockResolvedValueOnce([]).mockResolvedValueOnce([discovered]);

    renderManager(<ReferenceManager projectId={PROJECT_ID} />);

    await waitFor(() => {
      expect(screen.getByTestId('reference-list-empty')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('reference-scan-button'));

    await waitFor(() => {
      expect(mockScanProject).toHaveBeenCalledWith(PROJECT_ID);
    });

    await waitFor(() => {
      expect(screen.getByTestId('reference-row-ref-disc')).toBeInTheDocument();
    });
  });

  it('deletes a reference only after confirmDialog confirms', async () => {
    const ref = makeRef({ id: 'ref-del', aliasName: 'deleteme' });
    mockListReferences.mockResolvedValueOnce([ref]).mockResolvedValueOnce([]);

    renderManager(<ReferenceManager projectId={PROJECT_ID} />);

    await waitFor(() => {
      expect(screen.getByTestId('reference-row-ref-del')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('reference-delete-ref-del'));
    await waitFor(() => {
      expect(mockConfirmDialog).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(mockDeleteReference).toHaveBeenCalledWith(PROJECT_ID, 'ref-del');
    });
    await waitFor(() => {
      expect(screen.queryByTestId('reference-row-ref-del')).not.toBeInTheDocument();
    });
  });

  it('does not call deleteReference when the user cancels the confirmation', async () => {
    mockConfirmDialog.mockResolvedValue(false);
    const ref = makeRef({ id: 'ref-keep', aliasName: 'keepme' });
    mockListReferences.mockResolvedValue([ref]);

    renderManager(<ReferenceManager projectId={PROJECT_ID} />);

    await waitFor(() => {
      expect(screen.getByTestId('reference-row-ref-keep')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('reference-delete-ref-keep'));

    await waitFor(() => {
      expect(mockConfirmDialog).toHaveBeenCalledTimes(1);
    });
    expect(mockDeleteReference).not.toHaveBeenCalled();
    expect(screen.getByTestId('reference-row-ref-keep')).toBeInTheDocument();
  });

  it('renders an error banner when listReferences rejects', async () => {
    mockListReferences.mockRejectedValue(new Error('network down'));

    renderManager(<ReferenceManager projectId={PROJECT_ID} />);

    await waitFor(() => {
      const banner = screen.getByTestId('reference-error');
      expect(banner).toBeInTheDocument();
      expect(banner.textContent).toContain('network down');
    });
  });
});
