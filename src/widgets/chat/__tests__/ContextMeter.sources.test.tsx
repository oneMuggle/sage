// src/widgets/chat/__tests__/ContextMeter.sources.test.tsx
// 批次 C · 来源可追溯：已注入 / 已截断 / 被排除 / 未核验四态，以及“无标识”时的诚实提示。
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import type { ContextSource, SessionUsage } from '../../../shared/api/usageApi';
import { ContextMeter } from '../ContextMeter';

const mockFetch = vi.fn<(sessionId: string) => Promise<SessionUsage>>();

vi.mock('../../../shared/api/usageApi', () => ({
  fetchSessionUsage: (sessionId: string) => mockFetch(sessionId),
}));

function usageFixture(sources: ContextSource[]): SessionUsage {
  return {
    session_id: 's1',
    requests: 1,
    prompt_tokens: 40_000,
    completion_tokens: 0,
    total_tokens: 40_000,
    estimated_cost_usd: 0,
    cached_tokens: 0,
    cache_read_tokens: 0,
    cache_creation_tokens: 0,
    cache_hit_rate: 0,
    last_model: 'claude-sonnet-4',
    last_prompt_tokens: 40_000,
    last_cached_tokens: 0,
    last_at_ms: 1,
    effective_context_window: 200_000,
    last_context_breakdown: {
      categories: { dynamic_context: 40_000 },
      estimated_total: 40_000,
      prompt_tokens: 40_000,
      calibrated: true,
      sources,
    },
  };
}

async function openPanel(sources: ContextSource[]): Promise<void> {
  mockFetch.mockResolvedValue(usageFixture(sources));
  render(<ContextMeter sessionId="s1" />);
  await waitFor(() => expect(mockFetch).toHaveBeenCalled());
  fireEvent.click(screen.getByTestId('context-meter'));
}

describe('ContextMeter 来源明细', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('可追溯来源展开后列出真实标识，并标记单条截断与被排除条数', async () => {
    await openPanel([
      {
        key: 'project_materials',
        tokens: 12_000,
        count: 1,
        trimmed: 400,
        excluded: 2,
        identifiable: true,
        items: [
          { id: 'mat-1', label: 'mat-1', truncated: false },
          { id: 'mat-2', label: 'mat-2 · 来源消息 msg_7', truncated: true },
        ],
        omitted_items: 1,
      },
    ]);
    fireEvent.click(screen.getByTestId('context-meter-source-toggle-project_materials'));
    const detail = screen.getByTestId('context-meter-source-detail-project_materials');
    expect(detail.textContent).toContain('mat-1');
    expect(detail.textContent).toContain('来源消息 msg_7');
    expect(screen.getAllByTestId('context-meter-source-item-project_materials')).toHaveLength(2);
    expect(detail.textContent).toContain('已截断');
    expect(detail.textContent).toContain('另有 1 条未列出');
    expect(screen.getByTestId('context-source-excluded-project_materials').textContent).toContain(
      '排除 2 条',
    );
  });

  it('无单条标识的记忆来源明确说明不可逐条追溯，不虚构来源', async () => {
    await openPanel([{ key: 'memory', tokens: 800, count: 1, identifiable: false }]);
    fireEvent.click(screen.getByTestId('context-meter-source-toggle-memory'));
    const detail = screen.getByTestId('context-meter-source-detail-memory');
    expect(detail.textContent).toContain('无法逐条追溯');
    expect(screen.queryByTestId('context-meter-source-item-memory')).toBeNull();
  });

  it('保留“非内容验真”的口径声明', async () => {
    await openPanel([{ key: 'skills', tokens: 500, count: 1, identifiable: true, items: [] }]);
    expect(screen.getByTestId('context-meter-sources').textContent).toContain('不是发送前预览');
  });
});
