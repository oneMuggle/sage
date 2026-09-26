// 对话阅读体验第二轮 C2：回答版本切换器 ‹ 2/3 ›。
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { AnswerVersionList } from '../../../features/chat/answerVersions';
import { I18nProvider } from '../../../shared/lib/i18n';
import { AnswerVersionSwitcher } from '../AnswerVersionSwitcher';

const fetchVersions = vi.fn();
const activate = vi.fn();
vi.mock('../../../features/chat/answerVersions', () => ({
  fetchAnswerVersions: (...args: unknown[]) => fetchVersions(...args),
  activateAnswerVersion: (...args: unknown[]) => activate(...args),
}));
const toastError = vi.fn();
vi.mock('sonner', () => ({ toast: { error: (...args: unknown[]) => toastError(...args) } }));

function versions(current: number, total: number): AnswerVersionList {
  return {
    anchor_id: 'u1',
    total,
    current_index: current,
    versions: Array.from({ length: total }, (_, i) => ({
      id: i + 1 === current ? 'current' : `ver-${i + 1}`,
      generated_at: i,
      preview: `v${i + 1}`,
      current: i + 1 === current,
    })),
  };
}

function renderSwitcher(onChanged = vi.fn()) {
  render(
    <I18nProvider defaultLocale="zh">
      <AnswerVersionSwitcher sessionId="s1" messageId="a1" onChanged={onChanged} />
    </I18nProvider>,
  );
  return onChanged;
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

beforeEach(() => {
  fetchVersions.mockReset();
  activate.mockReset();
  toastError.mockReset();
});

describe('AnswerVersionSwitcher', () => {
  it('shows the position and switches to the previous answer', async () => {
    fetchVersions.mockResolvedValueOnce(versions(3, 3));
    activate.mockResolvedValueOnce(undefined);
    const onChanged = renderSwitcher();

    expect(await screen.findByTestId('answer-version-count')).toHaveTextContent('3/3');
    expect(screen.getByTestId('answer-version-switcher')).toHaveAttribute(
      'aria-label',
      '回答版本 3/3',
    );
    expect(screen.getByTestId('answer-version-next')).toBeDisabled();
    fireEvent.click(screen.getByTestId('answer-version-prev'));

    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(activate).toHaveBeenCalledWith('s1', 'ver-2');
    expect(fetchVersions).toHaveBeenCalledWith('s1');
  });

  it('disables going back from the first answer', async () => {
    fetchVersions.mockResolvedValueOnce(versions(1, 2));
    activate.mockResolvedValueOnce(undefined);
    renderSwitcher();

    expect(await screen.findByTestId('answer-version-count')).toHaveTextContent('1/2');
    expect(screen.getByTestId('answer-version-prev')).toBeDisabled();
    fireEvent.click(screen.getByTestId('answer-version-next'));
    await waitFor(() => expect(activate).toHaveBeenCalledWith('s1', 'ver-2'));
  });

  it('stays hidden with a single answer or when the backend is unavailable', async () => {
    fetchVersions.mockResolvedValueOnce(versions(1, 1));
    renderSwitcher();
    await flush();
    expect(screen.queryByTestId('answer-version-switcher')).toBeNull();

    fetchVersions.mockRejectedValueOnce(new Error('offline'));
    renderSwitcher();
    await flush();
    expect(screen.queryByTestId('answer-version-switcher')).toBeNull();
  });

  it('reports a failed switch without reloading', async () => {
    fetchVersions.mockResolvedValueOnce(versions(2, 2));
    activate.mockRejectedValueOnce(new Error('boom'));
    const onChanged = renderSwitcher();

    fireEvent.click(await screen.findByTestId('answer-version-prev'));

    await waitFor(() => expect(toastError).toHaveBeenCalledWith('切换回答版本失败：boom'));
    expect(onChanged).not.toHaveBeenCalled();
  });
});
