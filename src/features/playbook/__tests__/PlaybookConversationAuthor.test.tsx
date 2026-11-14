// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  PlaybookConversation,
  PlaybookSpec,
  PlaybookStageInference,
} from '../../../shared/api/playbookApi';
import { PlaybookConversationAuthor } from '../PlaybookConversationAuthor';

const startMock = vi.fn();
const sendMock = vi.fn();
const rollbackMock = vi.fn();
const commitMock = vi.fn();
const inferMock = vi.fn();
const bindMock = vi.fn();

vi.mock('../../../shared/api/playbookApi', () => ({
  playbookApi: {
    startAuthorConversation: (...args: unknown[]) => startMock(...args),
    sendAuthorMessage: (...args: unknown[]) => sendMock(...args),
    rollbackAuthorConversation: (...args: unknown[]) => rollbackMock(...args),
    commitAuthorConversation: (...args: unknown[]) => commitMock(...args),
    inferStages: (...args: unknown[]) => inferMock(...args),
    bind: (...args: unknown[]) => bindMock(...args),
  },
}));

const CREATED_AT = 1763100000000;

function spec(label = '开题'): PlaybookSpec {
  return {
    schema_version: '1.0',
    id: 'custom-demo',
    name: '示例规程',
    description: '开题-实施',
    applies_to: { project_types: ['research'], sub_types: [] },
    directory_layout: [],
    stages: [
      {
        id: 'stage-1',
        label,
        order: 1,
        objective: '',
        artifacts: [
          {
            id: 'proposal',
            label: '开题报告',
            required: true,
            match: { globs: ['**/开题报告*'], min_bytes: 0, min_count: 1 },
            content_checks: [],
          },
        ],
        exit_criteria: [],
        rules: [],
        recommended_milestones: [],
      },
    ],
    global_rules: [],
    todos: [],
    ai_guidance: {},
    meta: {},
  };
}

function conversation(overrides: Partial<PlaybookConversation> = {}): PlaybookConversation {
  return {
    id: 'conv-1',
    project_id: 'proj-1',
    messages: [
      {
        role: 'assistant',
        content: '已根据项目生成草案，请继续补充。',
        turn_index: 0,
        playbook_snapshot: null,
        created_at: CREATED_AT,
      },
    ],
    current_spec: spec(),
    status: 'active',
    created_at: CREATED_AT,
    updated_at: CREATED_AT,
    ...overrides,
  };
}

function renderPanel() {
  const onBound = vi.fn();
  const onNotice = vi.fn();
  const onError = vi.fn();
  render(
    <PlaybookConversationAuthor
      projectId="proj-1"
      onBound={onBound}
      onNotice={onNotice}
      onError={onError}
    />,
  );
  return { onBound, onNotice, onError };
}

async function openAndStart() {
  fireEvent.click(screen.getByTestId('playbook-conversation-toggle'));
  startMock.mockResolvedValue(conversation());
  fireEvent.click(screen.getByTestId('playbook-conversation-start'));
  await waitFor(() => expect(screen.getByTestId('playbook-conversation-messages')).toBeTruthy());
}

describe('PlaybookConversationAuthor', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('starts a conversation and renders the seeded draft', async () => {
    renderPanel();
    fireEvent.click(screen.getByTestId('playbook-conversation-toggle'));
    expect(screen.getByTestId('playbook-conversation-start')).toBeTruthy();

    startMock.mockResolvedValue(conversation());
    fireEvent.click(screen.getByTestId('playbook-conversation-start'));

    await waitFor(() => expect(startMock).toHaveBeenCalledWith('proj-1'));
    expect(await screen.findByText('已根据项目生成草案，请继续补充。')).toBeTruthy();
    expect(screen.getByTestId('playbook-conversation-stages').textContent).toContain('开题');
    expect(screen.getByText('1 个产物')).toBeTruthy();
  });

  it('sends a message and notifies on deterministic fallback', async () => {
    const { onNotice } = renderPanel();
    await openAndStart();

    sendMock.mockResolvedValue({
      conversation: conversation({
        messages: [
          ...conversation().messages,
          {
            role: 'user',
            content: '加一个评审阶段',
            turn_index: 1,
            playbook_snapshot: null,
            created_at: CREATED_AT,
          },
          {
            role: 'assistant',
            content: '收到。',
            turn_index: 2,
            playbook_snapshot: spec('评审'),
            created_at: CREATED_AT,
          },
        ],
      }),
      reply: '收到。',
      playbook: spec('评审'),
      llm_available: false,
      source: 'deterministic',
      turn_index: 2,
    });

    fireEvent.change(screen.getByTestId('playbook-conversation-input'), {
      target: { value: '加一个评审阶段' },
    });
    fireEvent.click(screen.getByTestId('playbook-conversation-send'));

    await waitFor(() =>
      expect(sendMock).toHaveBeenCalledWith('proj-1', 'conv-1', '加一个评审阶段'),
    );
    await waitFor(() => expect(onNotice).toHaveBeenCalledWith('（未配置 LLM，已降级为规则草案）'));
    expect((screen.getByTestId('playbook-conversation-input') as HTMLTextAreaElement).value).toBe(
      '',
    );
  });

  it('rolls back to the previous assistant turn', async () => {
    renderPanel();
    await openAndStart();

    sendMock.mockResolvedValue({
      conversation: conversation({
        messages: [
          ...conversation().messages,
          {
            role: 'user',
            content: '第一轮',
            turn_index: 1,
            playbook_snapshot: null,
            created_at: CREATED_AT,
          },
          {
            role: 'assistant',
            content: '已调整。',
            turn_index: 2,
            playbook_snapshot: spec('评审'),
            created_at: CREATED_AT,
          },
        ],
        current_spec: spec('评审'),
      }),
      reply: '已调整。',
      playbook: spec('评审'),
      llm_available: true,
      source: 'llm',
      turn_index: 2,
    });
    fireEvent.change(screen.getByTestId('playbook-conversation-input'), {
      target: { value: '第一轮' },
    });
    fireEvent.click(screen.getByTestId('playbook-conversation-send'));
    await waitFor(() => expect(screen.getByText('1. 评审')).toBeTruthy());

    rollbackMock.mockResolvedValue({ conversation: conversation(), playbook: spec() });
    fireEvent.click(screen.getByTestId('playbook-conversation-rollback'));

    await waitFor(() => expect(rollbackMock).toHaveBeenCalledWith('proj-1', 'conv-1', 1));
  });

  it('commits the draft, notifies the version and refreshes the card', async () => {
    const { onBound, onNotice } = renderPanel();
    await openAndStart();

    commitMock.mockResolvedValue({
      snapshot: {
        id: 'snap-1',
        project_id: 'proj-1',
        version: 3,
        source: 'ai-authored',
        parent_id: null,
        spec: spec(),
        spec_hash: 'abc',
        created_at: CREATED_AT,
        active: true,
      },
      conversation: conversation({ status: 'committed' }),
    });

    fireEvent.click(screen.getByTestId('playbook-conversation-commit'));

    await waitFor(() => expect(commitMock).toHaveBeenCalledWith('proj-1', 'conv-1'));
    await waitFor(() => expect(onNotice).toHaveBeenCalledWith('已绑定第 3 版规程'));
    expect(onBound).toHaveBeenCalled();
  });

  it('binds an inferred playbook only after explicit confirmation', async () => {
    const { onBound, onNotice } = renderPanel();
    fireEvent.click(screen.getByTestId('playbook-conversation-toggle'));

    const inference: PlaybookStageInference = {
      stages: [
        { label: '开题', source: 'directory', confidence: 0.8, artifacts: ['开题报告'] },
        { label: '实施', source: 'directory', confidence: 0.8, artifacts: [] },
      ],
      confidence: 0.8,
      source: 'directory',
      rationale: '识别到 01_开题、02_实施 编号目录',
      playbook: spec('开题'),
    };
    inferMock.mockResolvedValue(inference);

    fireEvent.click(screen.getByTestId('playbook-infer-btn'));
    await waitFor(() => expect(inferMock).toHaveBeenCalledWith('proj-1'));
    expect(await screen.findByTestId('playbook-infer-result')).toBeTruthy();
    expect(bindMock).not.toHaveBeenCalled();

    bindMock.mockResolvedValue(undefined);
    fireEvent.click(screen.getByTestId('playbook-bind-inferred'));

    await waitFor(() =>
      expect(bindMock).toHaveBeenCalledWith('proj-1', {
        spec: inference.playbook,
        source: 'inferred',
      }),
    );
    await waitFor(() => expect(onNotice).toHaveBeenCalledWith('已按推断结果绑定规程'));
    expect(onBound).toHaveBeenCalled();
  });

  it('reports API failures through onError', async () => {
    const { onError } = renderPanel();
    fireEvent.click(screen.getByTestId('playbook-conversation-toggle'));
    startMock.mockRejectedValue(new Error('后端不可用'));

    fireEvent.click(screen.getByTestId('playbook-conversation-start'));

    await waitFor(() => expect(onError).toHaveBeenCalledWith('后端不可用'));
  });
});
