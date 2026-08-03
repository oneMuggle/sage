import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Skill } from '../../shared/api/types';
import { I18nProvider } from '../../shared/lib/i18n';
import Skills from '../Skills';

// --------------- mocks --------------- //

const { mockSkills } = vi.hoisted(() => ({
  mockSkills: [] as Skill[],
}));

vi.mock('../../shared/api', () => ({
  skillsApi: {
    list: vi.fn().mockResolvedValue(mockSkills),
    toggle: vi.fn(),
    execute: vi.fn(),
    listSlashCommands: vi.fn().mockResolvedValue([]),
    delete: vi.fn(),
    archive: vi.fn(),
    rescan: vi.fn(),
    importFiles: vi.fn(),
  },
  skillDraftsApi: {
    list: vi.fn().mockResolvedValue({ drafts: [] }),
    approve: vi.fn().mockResolvedValue({ status: 'approved' }),
    reject: vi.fn().mockResolvedValue({ status: 'rejected' }),
  },
}));

// --------------- helpers --------------- //

function renderSkills() {
  return render(
    <MemoryRouter>
      <I18nProvider defaultLocale="zh">
        <Skills />
      </I18nProvider>
    </MemoryRouter>,
  );
}

// --------------- tests --------------- //

describe('Skills page — Pending Drafts tab', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders "Pending Drafts" tab trigger', async () => {
    renderSkills();
    // Wait for component to load
    await waitFor(() => {
      expect(screen.getByText('Pending Drafts')).toBeInTheDocument();
    });
  });

  it('renders tabs for skills and drafts', async () => {
    renderSkills();
    // Wait for component to load
    await waitFor(() => {
      expect(screen.getByText('Pending Drafts')).toBeInTheDocument();
    });

    // Both tab triggers should be present
    expect(screen.getByRole('tab', { name: /技能/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Pending Drafts/i })).toBeInTheDocument();
  });

  it('defaults to skills tab being active', async () => {
    renderSkills();
    // Wait for component to load
    await waitFor(() => {
      expect(screen.getByText('Pending Drafts')).toBeInTheDocument();
    });

    // The skills tab should be active by default
    const skillsTab = screen.getByRole('tab', { name: /技能/i });
    expect(skillsTab).toHaveAttribute('data-state', 'active');

    const draftsTab = screen.getByRole('tab', { name: /Pending Drafts/i });
    expect(draftsTab).toHaveAttribute('data-state', 'inactive');
  });
});
