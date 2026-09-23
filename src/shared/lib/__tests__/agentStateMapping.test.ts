/**
 * r112: agentStateToText 单元测试——AgentState → 气泡占位文本单一真相源。
 *
 * 锁定三类映射：有占位文本（thinking/acting/observing/failed）、
 * 卡点态不覆盖气泡（permission_request/ask_user_question → null）、
 * 事件态静默（task_xxx / reasoning_xxx 等事件态 → null）。
 */
import { describe, expect, it } from 'vitest';

import type { AgentState } from '../../api/types';

import { agentStateToText } from '../agentStateMapping';

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
];

describe('agentStateToText', () => {
  it.each(cases)('%s → %s', (state, expected, toolName) => {
    expect(agentStateToText(state, toolName)).toBe(expected);
  });
});
