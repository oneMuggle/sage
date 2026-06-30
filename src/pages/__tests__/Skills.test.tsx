import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

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
