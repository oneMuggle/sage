// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { PlaybookLibraryDetail } from '../../../shared/api/playbookApi';
import { PlaybookLibraryPanel } from '../PlaybookLibraryPanel';

const listLibraryMock = vi.fn();
const getLibraryItemMock = vi.fn();
const exportLibraryMock = vi.fn();
const deleteLibraryMock = vi.fn();

vi.mock('../../../shared/api/playbookApi', () => ({
  playbookApi: {
    listLibrary: (...args: unknown[]) => listLibraryMock(...args),
    getLibraryItem: (...args: unknown[]) => getLibraryItemMock(...args),
    exportLibrary: (...args: unknown[]) => exportLibraryMock(...args),
    deleteLibrary: (...args: unknown[]) => deleteLibraryMock(...args),
  },
}));

const ITEM = {
  id: 'lib-1',
  name: '科研课题规程',
  source: 'imported',
  spec_hash: 'abcdef1234567890',
  created_at: 1793500000000,
  stage_count: 3,
  directories: ['01_开题', '02_实施'],
};

const DETAIL = {
  item: ITEM,
  playbook: {
    name: '科研课题规程',
    description: '开题—实施—结题全周期',
    directory_layout: [{ path: '01_开题' }, { path: '02_实施' }],
    stages: [
      { label: '开题', artifacts: [{ id: 'proposal_report' }] },
      { label: '实施', artifacts: [] },
    ],
  },
} as unknown as PlaybookLibraryDetail;

beforeEach(() => {
  vi.clearAllMocks();
});

describe('PlaybookLibraryPanel', () => {
  it('规程库为空时显示引导', async () => {
    listLibraryMock.mockResolvedValue([]);
    render(<PlaybookLibraryPanel onClose={() => undefined} />);
    expect(await screen.findByTestId('playbook-library-empty')).toBeInTheDocument();
  });

  it('可查看详情、导出并删除条目', async () => {
    listLibraryMock.mockResolvedValue([ITEM]);
    getLibraryItemMock.mockResolvedValue(DETAIL);
    exportLibraryMock.mockResolvedValue({
      format: 'json',
      filename: 'cn-research-grant.sageplaybook.json',
      content: { format: 'sage.playbook' },
    });
    deleteLibraryMock.mockResolvedValue(undefined);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(<PlaybookLibraryPanel onClose={() => undefined} />);
    await screen.findByTestId('playbook-library-item-lib-1');

    fireEvent.click(screen.getByTestId('playbook-library-item-lib-1'));
    await waitFor(() => expect(getLibraryItemMock).toHaveBeenCalledWith('lib-1'));
    expect(await screen.findByTestId('playbook-library-detail')).toHaveTextContent(
      '开题（1 产物）',
    );

    fireEvent.click(screen.getByTestId('playbook-library-export-lib-1'));
    await waitFor(() => expect(exportLibraryMock).toHaveBeenCalledWith('lib-1'));

    fireEvent.click(screen.getByTestId('playbook-library-delete-lib-1'));
    await waitFor(() => expect(deleteLibraryMock).toHaveBeenCalledWith('lib-1'));
    await waitFor(() => expect(listLibraryMock).toHaveBeenCalledTimes(2));
    confirm.mockRestore();
  });

  it('取消删除时不调用删除接口', async () => {
    listLibraryMock.mockResolvedValue([ITEM]);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<PlaybookLibraryPanel onClose={() => undefined} />);
    await screen.findByTestId('playbook-library-delete-lib-1');
    fireEvent.click(screen.getByTestId('playbook-library-delete-lib-1'));
    expect(deleteLibraryMock).not.toHaveBeenCalled();
    confirm.mockRestore();
  });
});
