import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { OfficeRefChip } from '../OfficeRefChip';

const mocks = vi.hoisted(() => ({
  copyToClipboard: vi.fn(() => Promise.resolve(true)),
  openOfficeDocument: vi.fn(() => Promise.resolve()),
  showOfficeDocumentInFolder: vi.fn(() => Promise.resolve()),
}));

vi.mock('../../../shared/lib/clipboard', () => ({
  copyToClipboard: mocks.copyToClipboard,
}));

vi.mock('../../../shared/lib/workspaceContext', () => ({
  useCurrentWorkspace: () => '/workspace/ws',
}));

function setOfficeApi(present: boolean) {
  Object.defineProperty(window, 'electronAPI', {
    configurable: true,
    value: present
      ? {
          office: {
            openOfficeDocument: mocks.openOfficeDocument,
            showOfficeDocumentInFolder: mocks.showOfficeDocumentInFolder,
          },
        }
      : undefined,
  });
}

const chip = { docId: 'doc-1', docType: 'word' as const, filename: '方案.docx' };

beforeEach(() => {
  vi.clearAllMocks();
});

function renderChip(onRemove?: () => void) {
  setOfficeApi(true);
  return render(
    <I18nProvider defaultLocale="zh">
      <OfficeRefChip chip={chip} variant="composer" onRemove={onRemove} />
    </I18nProvider>,
  );
}

describe('OfficeRefChip — context menu', () => {
  it('opens the document through the existing office IPC channel', async () => {
    renderChip();

    fireEvent.contextMenu(screen.getByTestId('office-ref-chip'), { clientX: 4, clientY: 4 });
    fireEvent.click(await screen.findByRole('menuitem', { name: '打开' }));

    await waitFor(() =>
      expect(mocks.openOfficeDocument).toHaveBeenCalledWith({
        workspacePath: '/workspace/ws',
        docType: 'word',
        documentId: 'doc-1',
        filename: '方案.docx',
      }),
    );
  });

  it('reveals the document in the OS file manager', async () => {
    renderChip();

    fireEvent.contextMenu(screen.getByTestId('office-ref-chip'), { clientX: 4, clientY: 4 });
    fireEvent.click(await screen.findByRole('menuitem', { name: '在文件夹中显示' }));

    await waitFor(() =>
      expect(mocks.showOfficeDocumentInFolder).toHaveBeenCalledWith(
        expect.objectContaining({ documentId: 'doc-1' }),
      ),
    );
  });

  it('copies the file name and exposes remove when provided', async () => {
    const onRemove = vi.fn();
    renderChip(onRemove);

    fireEvent.contextMenu(screen.getByTestId('office-ref-chip'), { clientX: 4, clientY: 4 });
    fireEvent.click(await screen.findByRole('menuitem', { name: '复制文件名' }));
    expect(mocks.copyToClipboard).toHaveBeenCalledWith('方案.docx', expect.any(Object));

    fireEvent.contextMenu(screen.getByTestId('office-ref-chip'), { clientX: 4, clientY: 4 });
    fireEvent.click(await screen.findByRole('menuitem', { name: '移除' }));
    expect(onRemove).toHaveBeenCalledTimes(1);
  });

  it('disables open/reveal when the desktop bridge is unavailable', async () => {
    setOfficeApi(false);
    render(
      <I18nProvider defaultLocale="zh">
        <OfficeRefChip chip={chip} />
      </I18nProvider>,
    );

    fireEvent.contextMenu(screen.getByTestId('office-ref-chip'), { clientX: 4, clientY: 4 });
    fireEvent.click(await screen.findByRole('menuitem', { name: '打开' }));

    expect(mocks.openOfficeDocument).not.toHaveBeenCalled();
  });
});
