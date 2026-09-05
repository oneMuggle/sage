// src/widgets/chat/progress/ContextInput.tsx
/**
 * ContextInput — Phase 3 UI for parent agent / user to append steering
 * context to a running task.
 *
 * Flow:
 *  1. User selects message_type from dropdown (constraint/clarification/...).
 *  2. User types free-text content (max 8 KB UTF-8).
 *  3. Submit dispatches `orchRunControlClient.steerTask(...)` with the
 *     task's current `revision` as `expected_task_revision`.
 *  4. On 409 (CAS mismatch), the caller refreshes the run snapshot and the
 *     user retries.
 *
 * Security boundary: content is sent verbatim to backend steer endpoint;
 * backend validates whitelist + 8 KB cap. No tool grants, no privilege
 * escalation, no workspace escape.
 */

import { useMemo, useState } from 'react';

import { useRunControlStore } from '../../../entities/orchestration/runControlStore';
import { orchRunControlClient } from '../../../shared/api/orchRunControlClient';

type MessageType =
  | 'constraint'
  | 'clarification'
  | 'additional_context'
  | 'correction'
  | 'priority_update'
  | 'reference';

type ApplyMode = 'next_boundary' | 'new_followup';

interface ContextInputProps {
  runId: string;
  taskId: string;
  /** Current task revision; used for CAS. Read from store if not supplied. */
  expectedTaskRevision?: number;
  /** Optional creator identifier (defaults to "user"). */
  createdBy?: string;
}

const MESSAGE_TYPE_OPTIONS: Array<{ value: MessageType; label: string; hint: string }> = [
  { value: 'constraint', label: '约束', hint: '限制搜索范围/工具使用等' },
  { value: 'clarification', label: '澄清', hint: '补充问题定义或目标' },
  { value: 'additional_context', label: '补充上下文', hint: '提供新的事实/资料' },
  { value: 'correction', label: '纠正', hint: '指出并修正错误方向' },
  { value: 'priority_update', label: '优先级更新', hint: '调整子任务权重' },
  { value: 'reference', label: '参考', hint: '附加参考链接/文档' },
];

const APPLY_MODE_OPTIONS: Array<{ value: ApplyMode; label: string; hint: string }> = [
  { value: 'next_boundary', label: '下一个边界生效', hint: '下一步骤/工具调用前' },
  { value: 'new_followup', label: '创建后续任务', hint: '当前 task 完成后追加' },
];

const CONTENT_MAX_BYTES = 8 * 1024;

interface SubmitState {
  status: 'idle' | 'submitting' | 'success' | 'error' | 'conflict';
  message?: string;
  contextId?: string;
}

export function ContextInput({
  runId,
  taskId,
  expectedTaskRevision,
  createdBy: _createdBy = 'user',
}: ContextInputProps) {
  const [messageType, setMessageType] = useState<MessageType>('constraint');
  const [applyMode, setApplyMode] = useState<ApplyMode>('next_boundary');
  const [content, setContent] = useState('');
  const [state, setState] = useState<SubmitState>({ status: 'idle' });

  const runs = useRunControlStore((s) => s.runs);
  const run = runs.get(runId);
  const task = run?.tasks.find((t) => t.task_id === taskId);
  const revision = expectedTaskRevision ?? task?.revision ?? 0;

  const byteLength = useMemo(
    () => new TextEncoder().encode(content).byteLength,
    [content],
  );
  const overLimit = byteLength > CONTENT_MAX_BYTES;

  const canSubmit =
    state.status !== 'submitting' &&
    content.trim().length > 0 &&
    !overLimit;

  async function handleSubmit() {
    if (!canSubmit) return;
    setState({ status: 'submitting' });
    try {
      const resp = await orchRunControlClient.steerTask({
        run_id: runId,
        task_id: taskId,
        message_type: messageType,
        content: content.trim(),
        apply_mode: applyMode,
        expected_task_revision: revision,
      });
      setState({
        status: 'success',
        contextId: (resp as { context_id?: string })?.context_id,
        message: '已投递，等待执行器接收',
      });
      setContent('');
    } catch (err: unknown) {
      const detail = extractErrorDetail(err);
      if (detail.error === 'task_state_changed') {
        setState({
          status: 'conflict',
          message: `并发冲突：task 状态已变更（期望 revision ${detail.expected_task_revision}，当前 ${detail.current_task_revision}）。请刷新后重试`,
        });
      } else if (detail.error === 'task_terminal') {
        setState({
          status: 'error',
          message: `task 已终态（${detail.task_status}），无法追加`,
        });
      } else {
        const fallback =
          typeof detail.error === 'string'
            ? detail.error
            : typeof detail.message === 'string'
              ? (detail.message as string)
              : String(err);
        setState({
          status: 'error',
          message: fallback,
        });
      }
    }
  }

  return (
    <div
      className="px-4 py-3 border-t border-border-primary bg-bg-secondary"
      data-testid="context-input"
    >
      <div className="text-xs text-text-tertiary mb-2">追加信息</div>

      <div className="flex items-center gap-2 mb-2">
        <label className="text-xs text-text-secondary" htmlFor="ctx-message-type">
          类型
        </label>
        <select
          id="ctx-message-type"
          className="flex-1 text-xs bg-bg-primary border border-border-primary rounded px-2 py-1"
          value={messageType}
          onChange={(e) => setMessageType(e.target.value as MessageType)}
        >
          {MESSAGE_TYPE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value} title={opt.hint}>
              {opt.label} — {opt.hint}
            </option>
          ))}
        </select>
      </div>

      <div className="flex items-center gap-2 mb-2">
        <label className="text-xs text-text-secondary" htmlFor="ctx-apply-mode">
          生效
        </label>
        <select
          id="ctx-apply-mode"
          className="flex-1 text-xs bg-bg-primary border border-border-primary rounded px-2 py-1"
          value={applyMode}
          onChange={(e) => setApplyMode(e.target.value as ApplyMode)}
        >
          {APPLY_MODE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value} title={opt.hint}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      <textarea
        className="w-full text-xs bg-bg-primary border border-border-primary rounded p-2 resize-y min-h-16 max-h-40"
        placeholder="输入补充信息（最多 8 KB）..."
        value={content}
        onChange={(e) => setContent(e.target.value)}
        data-testid="context-input-text"
      />
      <div className="flex items-center justify-between mt-1">
        <span
          className={`text-[10px] ${overLimit ? 'text-error' : 'text-text-tertiary'}`}
        >
          {byteLength.toLocaleString()} / {CONTENT_MAX_BYTES.toLocaleString()} bytes
        </span>
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!canSubmit}
          className="text-xs px-3 py-1 rounded bg-primary text-white disabled:opacity-40"
          data-testid="context-input-submit"
        >
          {state.status === 'submitting' ? '发送中…' : '发送'}
        </button>
      </div>

      {state.message && (
        <div
          className={`mt-2 text-xs ${
            state.status === 'error' || state.status === 'conflict'
              ? 'text-error'
              : 'text-green-600'
          }`}
          data-testid="context-input-feedback"
        >
          {state.message}
          {state.contextId && (
            <span className="ml-2 text-text-tertiary">
              ({state.contextId.slice(0, 16)})
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function extractErrorDetail(err: unknown): Record<string, unknown> {
  if (err == null) return {};
  if (typeof err === 'object') {
    const maybe = err as { detail?: unknown; message?: string; error?: string };
    if (typeof maybe.detail === 'string') {
      try {
        return JSON.parse(maybe.detail) as Record<string, unknown>;
      } catch {
        return { error: maybe.detail };
      }
    }
    if (maybe.detail && typeof maybe.detail === 'object') {
      return maybe.detail as Record<string, unknown>;
    }
    if (maybe.error) return { error: maybe.error };
    if (maybe.message) return { error: maybe.message };
  }
  return { error: String(err) };
}
