/**
 * 对标 S3: 侧边栏导航收敛 —— 一级 4 项 + 可折叠「更多」分组。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { FEATURE_UNLOCK_STORAGE_KEY } from '../../../shared/lib/hooks/useFeatureUnlock';
import { I18nProvider } from '../../../shared/lib/i18n';
import { useStore } from '../../../shared/lib/store';
import { Sidebar } from '../Sidebar';

vi.mock('../../../features/manage-settings/useSettings', () => ({
  useSettings: () => ({
    settings: {
      endpoints: [],
      modelSelections: {
        chatModel: { endpointId: null, modelId: null },
        visionModel: { endpointId: null, modelId: null },
        embeddingModel: { endpointId: null, modelId: null },
      },
      maxContext: 4096,
      temperature: 0.7,
    },
  }),
}));

vi.mock('../../../features/manage-endpoints/api', () => ({
  testEndpointConnection: vi.fn().mockResolvedValue({ success: false }),
}));

beforeEach(() => {
  localStorage.clear();
  const setState = useStore.setState as unknown as (partial: Record<string, unknown>) => void;
  setState({ currentSessionId: null, sessions: [] });
});

function renderSidebarAt(path: string) {
  return render(
    <I18nProvider defaultLocale="zh">
      <MemoryRouter initialEntries={[path]}>
        <Sidebar />
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe('Sidebar — "更多" group (S3 nav convergence)', () => {
  it('shows primary entries and an expanded 更多 group by default', () => {
    renderSidebarAt('/chat');
    for (const label of ['对话', '记忆', '知识库', '设置']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByTestId('sidebar-more-toggle')).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('技能')).toBeInTheDocument();
  });

  it('collapses/expands the group and persists the choice', () => {
    renderSidebarAt('/chat');
    fireEvent.click(screen.getByTestId('sidebar-more-toggle'));
    expect(screen.queryByText('技能')).not.toBeInTheDocument();
    expect(localStorage.getItem('sage:sider:more-open:v1')).toBe('0');
    fireEvent.click(screen.getByTestId('sidebar-more-toggle'));
    expect(screen.getByText('技能')).toBeInTheDocument();
  });

  it('forces the group open when the current route lives inside it', () => {
    localStorage.setItem('sage:sider:more-open:v1', '0');
    renderSidebarAt('/skills');
    expect(screen.getByText('技能')).toBeInTheDocument();
    expect(screen.getByTestId('sidebar-more-toggle')).toHaveAttribute('aria-expanded', 'true');
  });

  it('still respects progressive disclosure inside the group', () => {
    renderSidebarAt('/chat');
    expect(screen.queryByText('编排')).not.toBeInTheDocument();
    localStorage.setItem(FEATURE_UNLOCK_STORAGE_KEY, JSON.stringify(['orchestration']));
  });
});
