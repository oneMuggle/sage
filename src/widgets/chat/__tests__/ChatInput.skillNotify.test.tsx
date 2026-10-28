import { render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';

// ===== 核心 mock: skillsApi.list 用 spyOn (不用 barrel mock) =====
// 理由: barrel 整体 mock 会连带打断 ChatInput 从同目录导入的其他 api
// (worktreeApi / fileSearchClient / types), 且手写的 fixture 容易漏掉 Skill
// 的必填字段。spyOn 只替换 list 一个方法, 其余保持真实对象, 类型零妥协。
import { skillsApi } from '../../../shared/api/skillsApi';
import type { Skill } from '../../../shared/api/types';
import { I18nProvider } from '../../../shared/lib/i18n';
import { ChatInput } from '../ChatInput';

// Mock 与 ChatInput.btw.test.tsx 对齐
vi.mock('../../../shared/lib/hooks/useFileUpload', () => ({
  useFileUpload: () => ({
    files: [],
    images: [],
    addFile: vi.fn(),
    addImage: vi.fn(),
    removeFile: vi.fn(),
    removeImage: vi.fn(),
    clearAll: vi.fn(),
    handleDrop: vi.fn(),
    handleDragOver: vi.fn(),
    isDragOver: false,
  }),
}));

vi.mock('../../../features/chat/useBtwCommand', () => ({
  useBtwCommand: () => ({
    open: vi.fn(),
    close: vi.fn(),
    isOpen: false,
    question: '',
    answer: '',
    isLoading: false,
  }),
}));

vi.mock('../../../features/chat/AtFileMenu', () => ({
  AtFileMenu: () => null,
}));

const makeSkill = (over: Partial<Skill> = {}): Skill => ({
  name: 'skill-a',
  description: 'A',
  triggers: ['a'],
  parameters: {},
  examples: [],
  enabled: true,
  usage_count: 0,
  dispatch: {
    disable_model_invocation: false,
    user_invocable: true,
    user_invocable_name: null,
    command_dispatch: 'prompt',
  },
  ...over,
});

let listSkillsMock: MockInstance<typeof skillsApi.list>;

type ListenHandler = (e: { payload: unknown }) => void;
let skillsNotifyHandler: ListenHandler | null = null;
const unlistenMock = vi.fn();
vi.mock('../../../shared/api/desktopEvent', () => ({
  listen: vi.fn(async (event: string, handler: ListenHandler) => {
    if (event === 'skills:notify') {
      skillsNotifyHandler = handler;
    }
    return unlistenMock;
  }),
}));

const renderWithI18n = (ui: React.ReactElement) =>
  render(<I18nProvider defaultLocale="zh">{ui}</I18nProvider>);

describe('ChatInput — skills:notify subscription', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    skillsNotifyHandler = null;
    listSkillsMock = vi.spyOn(skillsApi, 'list').mockResolvedValue([makeSkill()]);
  });

  afterEach(() => {
    listSkillsMock.mockRestore();
  });

  it('subscribes to skills:notify on mount', async () => {
    const { listen } = await import('../../../shared/api/desktopEvent');

    renderWithI18n(<ChatInput onSend={vi.fn()} />);

    // T6-R1: implementation calls desktopListen('skills:notify', handler) with 2 args.
    // Vitest toHaveBeenCalledWith compares arity exactly; assert 2 args, not 3.
    await waitFor(() => expect(listen).toHaveBeenCalledWith('skills:notify', expect.any(Function)));
  });

  it('re-fetches skills list when skills:notify event arrives', async () => {
    renderWithI18n(<ChatInput onSend={vi.fn()} />);

    await waitFor(() => expect(skillsNotifyHandler).not.toBeNull());

    // 初始 mount 已拉 1 次
    const initialCalls = listSkillsMock.mock.calls.length;
    expect(initialCalls).toBeGreaterThanOrEqual(1);

    // 触发 notify 事件 → 应再拉一次
    skillsNotifyHandler!({ payload: { kind: 'skills_rescanned', loaded_count: 1 } });

    await waitFor(() => expect(listSkillsMock.mock.calls.length).toBeGreaterThan(initialCalls));
  });

  it('does not crash if handler fires before skills list resolves', async () => {
    // 让首次 list 永远 pending
    let pendingResolver: (v: Skill[]) => void;
    listSkillsMock.mockReturnValueOnce(
      new Promise<Skill[]>((resolve) => {
        pendingResolver = resolve;
      }),
    );

    renderWithI18n(<ChatInput onSend={vi.fn()} />);

    // 等 handler 注册完成
    await waitFor(() => expect(skillsNotifyHandler).not.toBeNull());

    // 触发事件 — 不应抛出
    expect(() =>
      skillsNotifyHandler!({ payload: { kind: 'skill_deleted', name: 'x' } }),
    ).not.toThrow();

    // resolve pending, 避免未处理 promise 泄漏
    pendingResolver!([]);
  });
});
