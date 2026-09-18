/**
 * 桌宠 P1: petStore 纯函数归约 + 持久化测试。
 * (docs/plans/2026-09-18_desktop-pet-design.md §2.1)
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { SessionStreamSlots } from '../../send-message/chatStreamStore';
import {
  FLASH_TTL_MS,
  SLEEP_AFTER_MS,
  computePetState,
  toPetSessionLite,
  usePetStore,
  type PetComputeInput,
  type PetSessionLite,
} from '../petStore';

const lite = (overrides: Partial<PetSessionLite> = {}): PetSessionLite => ({
  busy: true,
  thinking: false,
  working: false,
  reporting: false,
  ...overrides,
});

const baseInput = (overrides: Partial<PetComputeInput> = {}): PetComputeInput => ({
  sessions: {},
  attentionSessionIds: [],
  flash: null,
  now: 1_000_000,
  idleSince: 1_000_000,
  ...overrides,
});

const slot = (overrides: Partial<SessionStreamSlots> = {}): SessionStreamSlots => ({
  streaming: null,
  streamingToolCalls: [],
  taskBoard: null,
  todos: [],
  completedSteps: [],
  shiftInfo: null,
  ...overrides,
});

describe('computePetState 优先级归约', () => {
  it('attention 最高：任何其他活动都在等确认之后', () => {
    const snap = computePetState(
      baseInput({
        sessions: { s1: lite({ thinking: true }) },
        attentionSessionIds: ['s9'],
        flash: { kind: 'celebrate', sessionId: 's1', at: 1_000_000 - 1000 },
      }),
    );
    expect(snap).toEqual({ state: 'attention', sessionId: 's9' });
  });

  it('flash 窗口内优先于 thinking；过期后回落', () => {
    const flash = { kind: 'celebrate' as const, sessionId: 's1', at: 1_000_000 - 1000 };
    expect(
      computePetState(baseInput({ sessions: { s1: lite({ thinking: true }) }, flash })).state,
    ).toBe('celebrate');
    const expired = { kind: 'celebrate' as const, sessionId: 's1', at: 1_000_000 - FLASH_TTL_MS.celebrate - 1 };
    expect(
      computePetState(baseInput({ sessions: { s1: lite({ thinking: true }) }, flash: expired }))
        .state,
    ).toBe('thinking');
  });

  it('thinking > working > reporting，各取首个命中会话', () => {
    const snap = computePetState(
      baseInput({
        sessions: {
          a: lite({ working: true }),
          b: lite({ reporting: true }),
          c: lite({ thinking: true }),
        },
      }),
    );
    expect(snap).toEqual({ state: 'thinking', sessionId: 'c' });

    expect(
      computePetState(baseInput({ sessions: { a: lite({ working: true }), b: lite({ reporting: true }) } }))
    ).toEqual({ state: 'working', sessionId: 'a' });

    expect(
      computePetState(baseInput({ sessions: { b: lite({ reporting: true }) } }))
    ).toEqual({ state: 'reporting', sessionId: 'b' });
  });

  it('busy 但无细粒度活动 → idle；idle 满 SLEEP_AFTER_MS → sleeping', () => {
    expect(computePetState(baseInput({ sessions: { a: lite() } })).state).toBe('idle');
    expect(computePetState(baseInput({ idleSince: 1_000_000 - SLEEP_AFTER_MS })).state).toBe(
      'sleeping',
    );
    expect(
      computePetState(baseInput({ idleSince: 1_000_000 - SLEEP_AFTER_MS + 1 })).state,
    ).toBe('idle');
  });
});

describe('toPetSessionLite 投影', () => {
  it('thinking/reasoning 族 → thinking；acting/content_delta/工具在飞 → working', () => {
    const streaming = (state: string) =>
      ({ messageId: 'm1', content: '', reasoning: '', state, currentAgentId: null, iteration: 0 }) as never;
    expect(toPetSessionLite(slot({ streaming: streaming('reasoning_delta') })).thinking).toBe(true);
    expect(toPetSessionLite(slot({ streaming: streaming('acting') })).working).toBe(true);
    expect(toPetSessionLite(slot({ streaming: streaming('content_delta') })).working).toBe(true);
    expect(
      toPetSessionLite(
        slot({ streaming: streaming('thinking'), streamingToolCalls: [{ id: 't1' } as never] }),
      ).working,
    ).toBe(true);
    expect(toPetSessionLite(slot()).busy).toBe(false);
  });

  it('taskBoard 有 running/queued 子任务且流未结束 → reporting', () => {
    const board = (
      statuses: Record<string, { status: string }>,
      counts: { running: number; queued: number },
    ) =>
      ({
        runId: 'r1',
        plan: [],
        statuses,
        progress: { total: 2, done: 0, ...counts, failed: 0, cancelled: 0 },
      }) as never;
    const streaming = {
      messageId: 'm1',
      content: '',
      reasoning: '',
      state: 'task_plan' as const,
      currentAgentId: null,
      iteration: 0,
    };
    expect(
      toPetSessionLite(
        slot({ streaming, taskBoard: board({ t1: { status: 'running' } }, { running: 1, queued: 0 }) }),
      ).reporting,
    ).toBe(true);
    expect(
      toPetSessionLite(slot({ streaming, taskBoard: board({}, { running: 0, queued: 0 }) })),
    ).toMatchObject({ reporting: false, busy: true });
  });
});

describe('petStore 持久化与 flash', () => {
  beforeEach(() => {
    localStorage.clear();
    usePetStore.setState({ enabled: false, petId: '', flash: null });
  });

  it('setEnabled/setPetId 写穿 localStorage，重载初值读取一致', () => {
    usePetStore.getState().setEnabled(true);
    usePetStore.getState().setPetId('violet-cat');
    expect(localStorage.getItem('pet-enabled')).toBe('1');
    expect(localStorage.getItem('pet-selected')).toBe('violet-cat');
  });

  it('triggerFlash 记录 kind/session 并在 TTL 后自动清除', () => {
    vi.useFakeTimers();
    try {
      usePetStore.getState().triggerFlash('celebrate', 's1');
      expect(usePetStore.getState().flash).toMatchObject({ kind: 'celebrate', sessionId: 's1' });
      vi.advanceTimersByTime(FLASH_TTL_MS.celebrate + 10);
      expect(usePetStore.getState().flash).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
