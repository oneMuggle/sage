/**
 * M0 (2026-11-03): 聊天头部「专家」选择器测试。
 *
 * 覆盖：选项加载与排序、当前绑定回显、切换落库、禁用/删除后回落主助手、
 * agents 加载失败只留主助手、无会话时禁用。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { useStore } from '../../../shared/lib/store';
import { SessionSpecialistPicker } from '../SessionSpecialistPicker';

const mockList = vi.fn<() => Promise<Array<Record<string, unknown>>>>();
const mockSetSpecialist = vi.fn<(sessionId: string, specialistId: string) => Promise<unknown>>();

vi.mock('../../../shared/api/agentsApi', () => ({
  agentsApi: {
    list: () => mockList(),
  },
}));

vi.mock('../../../shared/api/sessionApi', () => ({
  sessionApi: {
    setSpecialist: (sessionId: string, specialistId: string) =>
      mockSetSpecialist(sessionId, specialistId),
  },
}));

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function agent(id: string, name: string, enabled = true): Record<string, unknown> {
  return {
    id,
    name,
    role: 'general',
    description: '',
    system_prompt: '',
    tools: [],
    memory_access: [],
    model_config: { model: null, temperature: null, max_tokens: null },
    max_iterations: 20,
    enabled,
  };
}

function seedSession(specialistId?: string, sessionId: string | null = 's1'): void {
  useStore.setState({
    currentSessionId: sessionId,
    sessions:
      sessionId == null
        ? []
        : [
            {
              id: sessionId,
              title: '测试会话',
              created_at: 1,
              updated_at: 1,
              last_message_at: null,
              message_count: 0,
              is_pinned: false,
              specialist_id: specialistId,
            },
          ],
  });
}

function renderPicker() {
  return render(
    <I18nProvider>
      <SessionSpecialistPicker />
    </I18nProvider>,
  );
}

describe('SessionSpecialistPicker (M0)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockList.mockResolvedValue([
      agent('primary', '主助手'),
      agent('writer', '写作专家'),
      agent('analyst', '分析专家'),
      agent('retired', '已禁用专家', false),
    ]);
    mockSetSpecialist.mockResolvedValue(undefined);
    seedSession('primary');
  });

  it('lists enabled agents with primary first and others name-sorted', async () => {
    renderPicker();

    await waitFor(() => {
      expect(screen.getByTestId('session-specialist-picker')).not.toBeDisabled();
    });
    const options = Array.from(
      (screen.getByTestId('session-specialist-picker') as HTMLSelectElement).options,
    ).map((option) => option.value);

    // primary 恒在最前；其余按名称排序；禁用专家不出现。
    expect(options).toEqual(['primary', 'analyst', 'writer']);
  });

  it('reflects the session bound specialist', async () => {
    seedSession('writer');
    renderPicker();

    await waitFor(() => {
      expect((screen.getByTestId('session-specialist-picker') as HTMLSelectElement).value).toBe(
        'writer',
      );
    });
  });

  it('patches the session and updates the store on change', async () => {
    renderPicker();
    await waitFor(() => {
      expect(screen.getByTestId('session-specialist-picker')).not.toBeDisabled();
    });

    fireEvent.change(screen.getByTestId('session-specialist-picker'), {
      target: { value: 'writer' },
    });

    await waitFor(() => {
      expect(mockSetSpecialist).toHaveBeenCalledWith('s1', 'writer');
    });
    expect(useStore.getState().sessions[0].specialist_id).toBe('writer');
  });

  it('falls back to primary when the bound specialist is disabled or deleted', async () => {
    seedSession('retired');
    renderPicker();

    await waitFor(() => {
      const select = screen.getByTestId('session-specialist-picker') as HTMLSelectElement;
      expect(select.value).toBe('primary');
      expect(Array.from(select.options).map((option) => option.value)).not.toContain('retired');
    });
  });

  it('keeps only the primary fallback option when the agents list fails to load', async () => {
    mockList.mockRejectedValue(new Error('agents down'));
    renderPicker();

    await waitFor(() => {
      const select = screen.getByTestId('session-specialist-picker') as HTMLSelectElement;
      expect(Array.from(select.options).map((option) => option.value)).toEqual(['primary']);
    });
    expect(screen.getByText('主助手')).toBeInTheDocument();
  });

  it('is disabled without an active session', async () => {
    seedSession(undefined, null);
    renderPicker();

    // 等 agents 列表落地，避免异步 setState 落在用例结束后（act 警告）。
    await waitFor(() => {
      expect(
        (screen.getByTestId('session-specialist-picker') as HTMLSelectElement).options,
      ).toHaveLength(3);
    });
    expect(screen.getByTestId('session-specialist-picker')).toBeDisabled();
  });
});
