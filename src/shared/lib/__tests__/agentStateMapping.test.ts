/**
 * r112: agentStateToText 单元测试——AgentState → 气泡占位文本单一真相源。
 *
 * 锁定三类映射：有占位文本（thinking/acting/observing/failed）、
 * 卡点态不覆盖气泡（permission_request/ask_user_question → null）、
 * 事件态静默（task_xxx / reasoning_xxx 等事件态 → null）。
 */
import { describe, expect, it } from 'vitest';

import type { AgentState } from '../../api/types';
import { agentStateToPhase, agentStateToText } from '../agentStateMapping';

const cases: Array<[AgentState, string | null, string?]> = [
  ['thinking', '🤔 思考中…'],
  ['acting', '🔧 行动中…'],
  ['acting', '🔧 调工具 web_search…', 'web_search'],
  ['observing', '👀 观察结果…'],
  ['failed', '❌ 失败'],
  ['permission_request', null],
  ['ask_user_question', null],
  ['reasoning', null],
  ['reasoning_delta', null],
  ['reasoning_final', null],
  ['content_delta', null],
  ['idle', null],
  ['done', null],
  ['task_plan', null],
  ['task_status', null],
  ['task_progress', null],
  ['task_review', null],
  ['todo_snapshot', null],
  ['artifact_created', null],
  ['memory_used', null],
  ['skill_activated', null],
  ['compact_triggered', null],
  ['attachment_rag_used', null],
  ['workspace_changed', null],
  ['sources_used', null],
  ['suspended', null],
  ['subagent_event', null],
  ['approval_mode', null],
  ['step_done', null],
  ['topic_shifted', null],
  ['orch_preflight', null],
  ['retry', null],
  ['heartbeat', null], // 2026-10-26: 重试退避心跳 — 不渲染气泡占位文本
];

describe('agentStateToText', () => {
  it.each(cases)('%s → %s', (state, expected, toolName) => {
    expect(agentStateToText(state, toolName)).toBe(expected);
  });
});

describe('agentStateToPhase', () => {
  it('retry → RefreshCw + 重试中', () => {
    expect(agentStateToPhase('retry')).toEqual({ iconName: 'RefreshCw', label: '重试中' });
  });

  // 2026-10-26: 重试退避心跳复用 retry 的展示(后端仍在重试退避等待)
  it('heartbeat → RefreshCw + 重试中 (复用 retry 展示)', () => {
    expect(agentStateToPhase('heartbeat')).toEqual({ iconName: 'RefreshCw', label: '重试中' });
  });

  it('null / undefined → null', () => {
    expect(agentStateToPhase(null)).toBeNull();
    expect(agentStateToPhase(undefined)).toBeNull();
  });
});

describe('agentStateMapping diagnostic formatters (Phase P114)', () => {
  it('formats agent phase summary and JSON payload', async () => {
    const { formatAgentPhaseSummary, formatAgentPhaseJson } = await import('../agentStateMapping');
    expect(formatAgentPhaseSummary('acting', 'web_search')).toBe(
      'acting · Wrench:执行工具 · 🔧 调工具 web_search…',
    );
    expect(formatAgentPhaseSummary(null)).toBe('none · no-phase · no-text');
    const parsed = JSON.parse(formatAgentPhaseJson('thinking'));
    expect(parsed).toEqual({
      schema: 'sage.shared.agent_state_mapping.v1',
      state: 'thinking',
      toolName: null,
      phase: { iconName: 'Brain', label: '思考中' },
      text: '🤔 思考中…',
    });
  });
});
