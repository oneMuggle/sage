import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { skillDraftsApi } from '../../../shared/api';
import { I18nProvider } from '../../../shared/lib/i18n';
import SkillDraftList from '../SkillDraftList';

// --------------- mocks --------------- //

const { listMock, approveMock, rejectMock } = vi.hoisted(() => ({
  listMock: vi.fn().mockResolvedValue({ drafts: [] }),
  approveMock: vi.fn().mockResolvedValue({ status: 'approved' }),
  rejectMock: vi.fn().mockResolvedValue({ status: 'rejected' }),
}));

vi.mock('../../../shared/api', () => ({
  skillDraftsApi: {
    list: listMock,
    approve: approveMock,
    reject: rejectMock,
  },
}));

// --------------- helpers --------------- //

function renderDraftList() {
  return render(
    <I18nProvider defaultLocale="zh">
      <SkillDraftList />
    </I18nProvider>,
  );
}

const makeDraft = (id = 'draft-1', name = 'test-skill') => ({
  id,
  name,
  description: `${name} description`,
  when_to_use: 'when testing',
  content: '# test content',
  trigger_type: 'complex_turn',
  source_session_id: 'session-abc',
  source_context: {},
  status: 'pending' as const,
  created_at: 1700000000000,
});

// --------------- tests --------------- //

describe('SkillDraftList component', () => {
  beforeEach(() => {
    listMock.mockResolvedValue({ drafts: [] });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('shows loading state initially', () => {
    listMock.mockImplementation(() => new Promise(() => {})); // Never resolves
    renderDraftList();
    expect(screen.getByText(/加载草稿中/i)).toBeInTheDocument();
  });

  it('shows empty state when no drafts', async () => {
    listMock.mockResolvedValue({ drafts: [] });
    renderDraftList();

    await waitFor(() => expect(listMock).toHaveBeenCalled());
    expect(screen.getByText(/暂无待审草稿/i)).toBeInTheDocument();
  });

  it('renders draft cards from API', async () => {
    listMock.mockResolvedValue({
      drafts: [makeDraft('d1', 'alpha-skill'), makeDraft('d2', 'beta-skill')],
    });
    renderDraftList();

    await waitFor(() => expect(screen.getByText('alpha-skill')).toBeInTheDocument());
    expect(screen.getByText('beta-skill')).toBeInTheDocument();
  });

  it('approve button calls API and removes draft from list', async () => {
    const drafts = [makeDraft('d1', 'alpha-skill')];
    listMock.mockResolvedValue({ drafts });
    approveMock.mockResolvedValue({
      status: 'approved',
      skill_name: 'alpha-skill',
      draft_id: 'd1',
    });

    renderDraftList();
    const approveBtn = await screen.findByRole('button', { name: /approve alpha-skill/i });
    fireEvent.click(approveBtn);

    await waitFor(() => expect(approveMock).toHaveBeenCalledWith('d1'));
    await waitFor(() =>
      expect(screen.queryByText('alpha-skill')).not.toBeInTheDocument(),
    );
  });

  it('reject button calls API and removes draft from list', async () => {
    const drafts = [makeDraft('d1', 'alpha-skill')];
    listMock.mockResolvedValue({ drafts });
    rejectMock.mockResolvedValue({
      status: 'rejected',
      draft_id: 'd1',
    });

    renderDraftList();
    const rejectBtn = await screen.findByRole('button', { name: /reject alpha-skill/i });
    fireEvent.click(rejectBtn);

    await waitFor(() => expect(rejectMock).toHaveBeenCalledWith('d1'));
    await waitFor(() =>
      expect(screen.queryByText('alpha-skill')).not.toBeInTheDocument(),
    );
  });

  it('polls every 10s', async () => {
    listMock.mockResolvedValue({ drafts: [] });

    // Set up fake timers BEFORE rendering
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'setTimeout', 'clearTimeout'] });

    renderDraftList();

    // Initial call happens immediately
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(listMock).toHaveBeenCalledTimes(1);

    // Advance 10s → should poll again
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(listMock).toHaveBeenCalledTimes(2);

    // Another 10s → third call
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(listMock).toHaveBeenCalledTimes(3);
  });

  it('approve failure shows error and keeps draft', async () => {
    const drafts = [makeDraft('d1', 'alpha-skill')];
    listMock.mockResolvedValue({ drafts });
    approveMock.mockRejectedValue(new Error('network error'));

    renderDraftList();
    const approveBtn = await screen.findByRole('button', { name: /approve alpha-skill/i });
    fireEvent.click(approveBtn);

    await waitFor(() => expect(approveMock).toHaveBeenCalledWith('d1'));
    // Draft should still be visible after failure
    await waitFor(() => expect(screen.getByText('alpha-skill')).toBeInTheDocument());
  });

  it('shows error state when API fails', async () => {
    listMock.mockRejectedValue(new Error('API error'));
    renderDraftList();

    await waitFor(() => expect(screen.getByText(/加载失败/i)).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /重试/i })).toBeInTheDocument();
  });
});
