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

function renderSkills(initialPath = '/') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
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

  it('renders localized "待审草稿" tab trigger in zh locale', async () => {
    renderSkills();
    await waitFor(() => {
      expect(screen.getByText('待审草稿')).toBeInTheDocument();
    });
  });

  it('renders tabs for skills and drafts', async () => {
    renderSkills();
    await waitFor(() => {
      expect(screen.getByText('待审草稿')).toBeInTheDocument();
    });

    expect(screen.getByRole('tab', { name: /技能/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /待审草稿/i })).toBeInTheDocument();
  });

  it('defaults to skills tab being active', async () => {
    renderSkills();
    await waitFor(() => {
      expect(screen.getByText('待审草稿')).toBeInTheDocument();
    });

    const skillsTab = screen.getByRole('tab', { name: /技能/i });
    expect(skillsTab).toHaveAttribute('data-state', 'active');

    const draftsTab = screen.getByRole('tab', { name: /待审草稿/i });
    expect(draftsTab).toHaveAttribute('data-state', 'inactive');
  });

  it('explains three draft-generation methods when empty', async () => {
    // 直接通过 URL search param 进入草稿 tab,绕开 Radix Tab 点击切换
    renderSkills('/?tab=drafts');
    expect(await screen.findByText(/复杂回合自动沉淀/, {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByText(/把这个流程保存为技能/)).toBeInTheDocument();
    // 空态说明段与页头按钮都含「扫描冷技能」,故用说明段特有子串断言唯一性
    expect(screen.getByText(/点击「扫描冷技能」按钮/)).toBeInTheDocument();
    expect(screen.getByText(/默认模型已配置/)).toBeInTheDocument();
    // 两个 CTA 按钮都应渲染
    expect(screen.getByRole('button', { name: /从最近会话生成/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /扫描冷技能/ })).toBeInTheDocument();
  });
});
