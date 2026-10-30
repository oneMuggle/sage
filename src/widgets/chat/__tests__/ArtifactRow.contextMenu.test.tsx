import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { Artifact } from '../../../features/artifacts/artifactApi';
import { I18nProvider } from '../../../shared/lib/i18n';
import { ArtifactRow } from '../artifacts/ArtifactRow';

const mocks = vi.hoisted(() => ({
  revealArtifact: vi.fn(() => Promise.resolve({ ok: true })),
  copyToClipboard: vi.fn(() => Promise.resolve(true)),
}));

vi.mock('../../../features/artifacts/artifactApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../features/artifacts/artifactApi')>();
  return { ...actual, revealArtifact: mocks.revealArtifact };
});

vi.mock('../../../shared/lib/clipboard', () => ({
  copyToClipboard: mocks.copyToClipboard,
}));

const artifact: Artifact = {
  id: 'a1',
  session_id: 'sess_001',
  tool_call_id: null,
  path: '/tmp/test.md',
  name: 'test.md',
  kind: 'markdown',
  size: 1024,
  created_at: 1722500000000,
};

function renderRow(onSelect = vi.fn(), onOpenDelivery?: () => void) {
  return render(
    <I18nProvider defaultLocale="zh">
      <ArtifactRow artifact={artifact} onSelect={onSelect} onOpenDelivery={onOpenDelivery} />
    </I18nProvider>,
  );
}

function openMenu() {
  fireEvent.contextMenu(screen.getByText('test.md'), { clientX: 6, clientY: 6 });
}

describe('ArtifactRow — context menu', () => {
  it('opens the artifact and reveals it in the file manager', async () => {
    const onSelect = vi.fn();
    renderRow(onSelect);

    openMenu();
    fireEvent.click(await screen.findByRole('menuitem', { name: '打开产物' }));
    expect(onSelect).toHaveBeenCalledWith(artifact);

    openMenu();
    fireEvent.click(await screen.findByRole('menuitem', { name: '在文件管理器中显示' }));
    await waitFor(() => expect(mocks.revealArtifact).toHaveBeenCalledWith('sess_001', 'a1'));
  });

  it('copies the artifact path', async () => {
    renderRow();

    openMenu();
    fireEvent.click(await screen.findByRole('menuitem', { name: '复制路径' }));

    expect(mocks.copyToClipboard).toHaveBeenCalledWith('/tmp/test.md', expect.any(Object));
  });

  it('exposes the delivery workspace only for office kinds with a handler', async () => {
    renderRow();
    openMenu();
    await screen.findByRole('menuitem', { name: '打开产物' });
    expect(screen.queryByRole('menuitem', { name: '打开交付工作台' })).toBeNull();

    const officeArtifact: Artifact = { ...artifact, kind: 'docx', name: 'report.docx' };
    render(
      <I18nProvider defaultLocale="zh">
        <ArtifactRow artifact={officeArtifact} onSelect={vi.fn()} onOpenDelivery={vi.fn()} />
      </I18nProvider>,
    );
    fireEvent.contextMenu(screen.getByText('report.docx'), { clientX: 6, clientY: 6 });
    expect(await screen.findByRole('menuitem', { name: '打开交付工作台' })).toBeInTheDocument();
  });
});
