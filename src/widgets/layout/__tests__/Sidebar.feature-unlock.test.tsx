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
    expect(screen.queryByText('编排')).not.toBeInTheDocument();
    expect(screen.queryByText('Office')).not.toBeInTheDocument();
  });

  it('unlocks the entry for the currently visited advanced route', () => {
    renderSidebarAt('/orchestration');
    // 访问 /orchestration 即解锁并显示编排入口
    expect(screen.getByText('编排')).toBeInTheDocument();
    // 未访问的高级入口仍然隐藏
    expect(screen.queryByText('Office')).not.toBeInTheDocument();
    // 解锁状态已持久化
    const stored = JSON.parse(localStorage.getItem(FEATURE_UNLOCK_STORAGE_KEY) as string);
    expect(stored).toContain('orchestration');
  });

  it('keeps the entry visible on later loads once unlocked (sticky)', () => {
    localStorage.setItem(FEATURE_UNLOCK_STORAGE_KEY, JSON.stringify(['orchestration']));
    renderSidebarAt('/chat');
    expect(screen.getByText('编排')).toBeInTheDocument();
    expect(screen.queryByText('Office')).not.toBeInTheDocument();
  });

  it('shows all advanced entries when all are unlocked', () => {
    localStorage.setItem(FEATURE_UNLOCK_STORAGE_KEY, JSON.stringify(['orchestration', 'office']));
    renderSidebarAt('/chat');
    expect(screen.getByText('编排')).toBeInTheDocument();
    expect(screen.getByText('Office')).toBeInTheDocument();
  });
});

/**
 * 技能入口不受渐进式披露门控（PR-1.1）。
 *
 * U10 sticky-unlock 曾把 `/skills` 纳入 `ADVANCED_FEATURE_BY_PATH`，造成自锁：
 * 入口可见性依赖"已经用过入口"，而技能页是 SKILL.md 体系的唯一 UI 入口。
 */
describe('Sidebar — skills entry is not gated', () => {
  it('renders the skills entry with no feature unlocked', () => {
    renderSidebarAt('/chat');
    expect(screen.getByText('技能')).toBeInTheDocument();
  });

  it('does not write a skills unlock record when visiting /skills', () => {
    renderSidebarAt('/skills');
    expect(screen.getByText('技能')).toBeInTheDocument();
    const raw = localStorage.getItem(FEATURE_UNLOCK_STORAGE_KEY);
    expect(raw == null ? [] : JSON.parse(raw)).not.toContain('skills');
  });
});

/**
 * U-Brand: Sidebar 顶部 logo + wordmark 必须从共享 <BrandLogo> 渲染。
 * 防止后续 commit 把硬编码 S 方块重新引回 Sidebar。
 */
describe('Sidebar — brand header (U-Brand)', () => {
  it('renders brand logo img with proper alt', () => {
    renderSidebarAt('/chat');
    // img 通过 a11y 名 "Sage 标志"（zh）或 "Sage logo"（en）查找
    const img = screen.getByRole('img', { name: /Sage/i });
    expect(img).toHaveAttribute('src', '/sage.svg');
  });

  it('renders Sage wordmark from sidebar.brand translation', () => {
    renderSidebarAt('/chat');
    // wordmark 与 nav 文字都包含 "Sage"；至少出现一次即可
    expect(screen.getAllByText('Sage').length).toBeGreaterThanOrEqual(1);
  });
});
