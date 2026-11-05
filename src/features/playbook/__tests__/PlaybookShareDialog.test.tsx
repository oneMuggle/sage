// @vitest-environment jsdom
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { PlaybookShareDialog } from '../PlaybookShareDialog';

const createShareLinkMock = vi.fn();

vi.mock('../../../shared/api/playbookApi', () => ({
  playbookApi: {
    createShareLink: (...args: unknown[]) => createShareLinkMock(...args),
  },
}));

const LINK = {
  token: 'tok_abc123',
  playbook_id: 'lib-1',
  playbook_name: '科研课题规程',
  expires_at: 1793500000000,
  share_url: '/share/playbook/tok_abc123',
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('PlaybookShareDialog', () => {
  it('生成后展示带 # 前缀的绝对分享链接', async () => {
    createShareLinkMock.mockResolvedValue(LINK);

    render(
      <PlaybookShareDialog
        open
        libraryId="lib-1"
        playbookName="科研课题规程"
        onClose={() => undefined}
      />,
    );

    const url = await screen.findByTestId('playbook-share-url');
    await waitFor(() => expect(url).toHaveTextContent('#/share/playbook/tok_abc123'));
    expect(url.textContent).toContain(window.location.origin);
  });

  it('未指定库条目时不请求后端', () => {
    render(<PlaybookShareDialog open libraryId={null} onClose={() => undefined} />);

    expect(createShareLinkMock).not.toHaveBeenCalled();
  });

  it('生成失败时展示错误', async () => {
    createShareLinkMock.mockRejectedValue(new Error('后端不可用'));

    render(<PlaybookShareDialog open libraryId="lib-1" onClose={() => undefined} />);

    expect(await screen.findByText('后端不可用')).toBeInTheDocument();
  });
});
