import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { FEATURE_UNLOCK_STORAGE_KEY } from '../../../shared/lib/hooks/useFeatureUnlock';
import { I18nProvider } from '../../../shared/lib/i18n';
import { useStore } from '../../../shared/lib/store';
import { Sidebar } from '../Sidebar';

// vi.mock 工厂会被提升，直接引用外层 const 会 TDZ —— 必须走 vi.hoisted。
const { confirmDialogMock } = vi.hoisted(() => ({
  confirmDialogMock: vi.fn<(opts: { title: string; message?: string }) => Promise<boolean>>(),
}));

vi.mock('../../../shared/ui/ConfirmDialog/confirmService', () => ({
  confirmDialog: (opts: { title: string; message?: string }) => confirmDialogMock(opts),
}));

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
  confirmDialogMock.mockReset();
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

/**
 * P1-7 契约变更：渐进式披露不再等于「隐藏」。
 *
 * 原本未解锁入口直接 `return null`，造成"功能不存在"的错觉 —— `/office`
 * 是本项目核心差异化能力，却只能靠输 URL 或命令面板发现。现改为
 * **灰态可见**（`data-locked="true"`）：入口常驻 → 点击给出用途说明 →
 * 确认后解锁进入。一级导航区的隐藏逻辑不变，灰态只出现在「更多」分组内。
 */
const lockedEntry = (name: string) => screen.queryByTestId(`sidebar-locked-${name}`);
const isLocked = (name: string) => lockedEntry(name) !== null;

describe('Sidebar — progressive disclosure (U10, P1-7 灰态可见)', () => {
  it('未首次使用时高级入口灰态可见（而非隐藏）', () => {
    renderSidebarAt('/chat');
    // 常规入口仍然可见
    expect(screen.getByText('对话')).toBeInTheDocument();
    expect(screen.getByText('设置')).toBeInTheDocument();
    // 高级入口：可见但标记为未启用 —— 用户能知道功能存在
    expect(screen.getByText('编排')).toBeInTheDocument();
    expect(screen.getByText('Office')).toBeInTheDocument();
    expect(screen.getByText('Arena')).toBeInTheDocument();
    expect(isLocked('orchestration')).toBe(true);
    expect(isLocked('office')).toBe(true);
    expect(isLocked('arena')).toBe(true);
  });

  it('访问高级路由即解锁该入口，其余保持灰态', () => {
    renderSidebarAt('/orchestration');
    expect(screen.getByText('编排')).toBeInTheDocument();
    // 已解锁 → 不再是灰态条目
    expect(isLocked('orchestration')).toBe(false);
    // 未访问的仍是灰态（但可见）
    expect(isLocked('office')).toBe(true);
    expect(isLocked('arena')).toBe(true);
    const stored = JSON.parse(localStorage.getItem(FEATURE_UNLOCK_STORAGE_KEY) as string);
    expect(stored).toContain('orchestration');
  });

  it('解锁状态跨会话保持（sticky）', () => {
    localStorage.setItem(FEATURE_UNLOCK_STORAGE_KEY, JSON.stringify(['orchestration']));
    renderSidebarAt('/chat');
    expect(screen.getByText('编排')).toBeInTheDocument();
    expect(isLocked('orchestration')).toBe(false);
    expect(isLocked('office')).toBe(true);
    expect(isLocked('arena')).toBe(true);
  });

  it('全部解锁后不再有任何灰态条目', () => {
    localStorage.setItem(
      FEATURE_UNLOCK_STORAGE_KEY,
      JSON.stringify(['orchestration', 'office', 'arena-accounts']),
    );
    renderSidebarAt('/chat');
    expect(screen.getByText('编排')).toBeInTheDocument();
    expect(screen.getByText('Office')).toBeInTheDocument();
    // P5：入口并入 /arena 三页签控制台，label 从「Arena 账号」改为「Arena」
    expect(screen.getByText('Arena')).toBeInTheDocument();
    expect(screen.queryByTestId(/^sidebar-locked-/)).toBeNull();
  });

  it('P1-7: 点击灰态入口给出用途说明，确认后解锁并进入', async () => {
    let settle: (ok: boolean) => void = () => {};
    confirmDialogMock.mockImplementation(
      () =>
        new Promise<boolean>((resolve) => {
          settle = resolve;
        }),
    );
    renderSidebarAt('/chat');

    fireEvent.click(lockedEntry('office')!);
    await waitFor(() => expect(confirmDialogMock).toHaveBeenCalled());
    // 说明里要讲清这个高级能力能干什么，否则引导无意义
    expect(confirmDialogMock.mock.calls[0][0].message).toContain('Word');
    // 用户还没点确认 —— 此时绝不能已经解锁
    expect(isLocked('office')).toBe(true);
    expect(localStorage.getItem(FEATURE_UNLOCK_STORAGE_KEY) ?? '[]').not.toContain('office');

    await act(async () => {
      settle(true);
    });
    await waitFor(() => expect(isLocked('office')).toBe(false));
    expect(localStorage.getItem(FEATURE_UNLOCK_STORAGE_KEY) ?? '[]').toContain('office');
  });

  it('P1-7: 取消说明不产生解锁副作用', async () => {
    let settle: (ok: boolean) => void = () => {};
    confirmDialogMock.mockImplementation(
      () =>
        new Promise<boolean>((resolve) => {
          settle = resolve;
        }),
    );
    renderSidebarAt('/chat');

    fireEvent.click(lockedEntry('arena')!);
    await waitFor(() => expect(confirmDialogMock).toHaveBeenCalled());
    await act(async () => {
      settle(false);
    });

    // 拒绝对「说明」而言是正常路径 —— 不该留下任何解锁痕迹
    expect(localStorage.getItem(FEATURE_UNLOCK_STORAGE_KEY) ?? '[]').not.toContain('arena');
    expect(isLocked('arena')).toBe(true);
  });

  it('unlocks arena entry when visiting /arena directly (legacy /arena-accounts too)', () => {
    // P5：规范路径 /arena 直接解锁
    renderSidebarAt('/arena');
    expect(screen.getByText('Arena')).toBeInTheDocument();
    expect(isLocked('arena')).toBe(false);
    const stored = JSON.parse(localStorage.getItem(FEATURE_UNLOCK_STORAGE_KEY) as string);
    expect(stored).toContain('arena-accounts');

    // 旧路径 /arena-accounts（重定向到 /arena）同样保留解锁语义
    localStorage.clear();
    renderSidebarAt('/arena-accounts');
    const storedLegacy = JSON.parse(
      localStorage.getItem(FEATURE_UNLOCK_STORAGE_KEY) as string,
    );
    expect(storedLegacy).toContain('arena-accounts');
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
    expect(img).toHaveAttribute('src', './sage.svg');
  });

  it('renders Sage wordmark from sidebar.brand translation', () => {
    renderSidebarAt('/chat');
    // wordmark 与 nav 文字都包含 "Sage"；至少出现一次即可
    expect(screen.getAllByText('Sage').length).toBeGreaterThanOrEqual(1);
  });
});
