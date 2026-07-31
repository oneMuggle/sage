import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

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

describe('Sidebar — progressive disclosure (U10)', () => {
  it('hides advanced entries before first use', () => {
    renderSidebarAt('/chat');
    // 常规入口仍然可见
    expect(screen.getByText('对话')).toBeInTheDocument();
    expect(screen.getByText('设置')).toBeInTheDocument();
    // 高级入口隐藏
    expect(screen.queryByText('技能')).not.toBeInTheDocument();
    expect(screen.queryByText('编排')).not.toBeInTheDocument();
    expect(screen.queryByText('Office')).not.toBeInTheDocument();
  });

  it('unlocks the entry for the currently visited advanced route', () => {
    renderSidebarAt('/skills');
    // 访问 /skills 即解锁并显示技能入口
    expect(screen.getByText('技能')).toBeInTheDocument();
    // 未访问的高级入口仍然隐藏
    expect(screen.queryByText('编排')).not.toBeInTheDocument();
    expect(screen.queryByText('Office')).not.toBeInTheDocument();
    // 解锁状态已持久化
    const stored = JSON.parse(localStorage.getItem(FEATURE_UNLOCK_STORAGE_KEY) as string);
    expect(stored).toContain('skills');
  });

  it('keeps the entry visible on later loads once unlocked (sticky)', () => {
    localStorage.setItem(FEATURE_UNLOCK_STORAGE_KEY, JSON.stringify(['skills']));
    renderSidebarAt('/chat');
    expect(screen.getByText('技能')).toBeInTheDocument();
    expect(screen.queryByText('编排')).not.toBeInTheDocument();
  });

  it('shows all advanced entries when all are unlocked', () => {
    localStorage.setItem(
      FEATURE_UNLOCK_STORAGE_KEY,
      JSON.stringify(['skills', 'orchestration', 'office']),
    );
    renderSidebarAt('/chat');
    expect(screen.getByText('技能')).toBeInTheDocument();
    expect(screen.getByText('编排')).toBeInTheDocument();
    expect(screen.getByText('Office')).toBeInTheDocument();
  });
});
