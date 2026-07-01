import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { Skill } from '../../shared/api/types';
import { I18nProvider } from '../../shared/lib/i18n';
import Skills from '../Skills';

const listMock = vi.fn();
const toggleMock = vi.fn();

vi.mock('../../shared/api', () => ({
  skillsApi: {
    list: () => listMock(),
    toggle: (...args: unknown[]) => toggleMock(...args),
    execute: vi.fn(),
    listSlashCommands: vi.fn().mockResolvedValue([]),
  },
}));

const sampleSkills: Skill[] = [
  {
    name: 'web-search',
    description: 'Search the web',
    triggers: ['search'],
    parameters: {},
    examples: [],
    enabled: true,
    usage_count: 5,
    source: 'builtin',
  },
  {
    name: 'coder',
    description: 'Write code',
    triggers: ['code'],
    parameters: {},
    examples: [],
    enabled: false,
    usage_count: 2,
    source: 'builtin',
  },
];

function renderSkills() {
  return render(
    <I18nProvider defaultLocale="zh">
      <Skills />
    </I18nProvider>,
  );
}

describe('Skills page — refresh button', () => {
  afterEach(() => {
    listMock.mockReset();
    toggleMock.mockReset();
  });

  it('renders the refresh button in the page header', async () => {
    listMock.mockResolvedValueOnce(sampleSkills);
    renderSkills();

    // initial load → list() called once
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(1));

    const refreshBtn = screen.getByRole('button', { name: /刷新|refresh/i });
    expect(refreshBtn).toBeInTheDocument();
    expect(refreshBtn).toBeInstanceOf(HTMLButtonElement);
  });

  it('clicking the refresh button re-invokes skillsApi.list()', async () => {
    listMock.mockResolvedValue(sampleSkills);
    renderSkills();
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole('button', { name: /刷新|refresh/i }));

    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(2));
  });

  it('disables refresh button while a load is in flight', async () => {
    // first load resolves immediately; second hangs until we resolve it
    listMock.mockResolvedValueOnce(sampleSkills);

    let resolveSecond!: (v: Skill[]) => void;
    const pendingSecond = new Promise<Skill[]>((res) => {
      resolveSecond = res;
    });
    listMock.mockReturnValueOnce(pendingSecond);

    renderSkills();

    // Wait for initial load (resolved).
    await waitFor(() => expect(screen.getByText('web-search')).toBeInTheDocument());

    const refreshBtn = screen.getByRole('button', { name: /刷新|refresh/i });
    fireEvent.click(refreshBtn);

    // While the second call is in flight, the button should be disabled.
    await waitFor(() => expect(refreshBtn).toBeDisabled());

    // Finish the load → button re-enabled.
    resolveSecond(sampleSkills);
    await waitFor(() => expect(refreshBtn).not.toBeDisabled());
  });
});

describe('Skills page — auto-refresh toggle', () => {
  // 每次测试前确保从真实 timer 起步, 避免上一个测试残留的 fake state
  beforeEach(() => {
    vi.useRealTimers();
    listMock.mockReset();
    toggleMock.mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('auto-refresh toggle defaults to OFF', async () => {
    listMock.mockResolvedValue(sampleSkills);
    renderSkills();
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(1));

    const toggle = screen.getByRole('switch', { name: /自动刷新/i });
    expect(toggle).toHaveAttribute('aria-checked', 'false');
  });

  it('flipping toggle ON starts 10s interval that re-calls list', async () => {
    listMock.mockResolvedValue(sampleSkills);
    renderSkills();
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(1));

    // 仅 fake timing 函数, 保留 promise microtasks 以便 listMock mockResolvedValue 立刻 resolve
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'setTimeout', 'clearTimeout'] });

    const toggle = screen.getByRole('switch', { name: /自动刷新/i });
    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute('aria-checked', 'true');

    // 快进 10s 后, list 应当被再次调用
    await act(async () => {
      vi.advanceTimersByTime(10000);
    });
    expect(listMock).toHaveBeenCalledTimes(2);

    // 再过 10s, 第三次
    await act(async () => {
      vi.advanceTimersByTime(10000);
    });
    expect(listMock).toHaveBeenCalledTimes(3);
  });

  it('flipping toggle OFF clears interval (no extra list calls)', async () => {
    listMock.mockResolvedValue(sampleSkills);
    renderSkills();
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(1));

    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'setTimeout', 'clearTimeout'] });

    const toggle = screen.getByRole('switch', { name: /自动刷新/i });
    fireEvent.click(toggle); // ON
    await act(async () => {
      vi.advanceTimersByTime(10000);
    });
    expect(listMock).toHaveBeenCalledTimes(2);

    fireEvent.click(toggle); // OFF
    await act(async () => {
      vi.advanceTimersByTime(30000);
    });
    expect(listMock).toHaveBeenCalledTimes(2); // 不再增加
  });

  it('auto-refresh failure does NOT reset toggle', async () => {
    listMock.mockResolvedValueOnce(sampleSkills);
    listMock.mockRejectedValueOnce(new Error('network down'));
    listMock.mockResolvedValue(sampleSkills);

    renderSkills();
    await waitFor(() => expect(listMock).toHaveBeenCalledTimes(1));

    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'setTimeout', 'clearTimeout'] });

    const toggle = screen.getByRole('switch', { name: /自动刷新/i });
    fireEvent.click(toggle); // ON

    // 快进到 polling 触发 (失败): 用 advanceTimersByTimeAsync 让 promise 微任务自然 resolve
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });

    // toggle 应仍为 ON (失败不关) — listMock 至少被调用两次
    expect(listMock.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(toggle).toHaveAttribute('aria-checked', 'true');
  });
});
