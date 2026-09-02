/**
 * 解析 NDJSON 流式响应
 */

export type AgentState =
  | 'idle'
  | 'thinking'
  | 'reasoning'
  | 'reasoning_delta'
  | 'reasoning_final' // 2026-09-02 (win7 cherry-pick): 后端 reasoning 流末尾发的全量事件,前端必须 replace 而非 append
  | 'acting'
  | 'observing'
  | 'content_delta'
  | 'done'
  | 'failed'
  // Multi-Agent Orchestration (2026-08-11)
  | 'task_plan'
  | 'task_status'
  // 进度可视化 P0-2 (2026-08-12): 整盘概览,见 types.ts TaskProgressEvent。
  | 'task_progress'
  // Wave 2 (2026-08-14): reviewer 复核结论事件,见 types.ts TaskReviewEvent。
  | 'task_review'
  // P1 todo 接线 (2026-08-21): agent 任务清单全量快照。
  | 'todo_snapshot';

// 窄类型事件接口 —— useChat taskBoard 状态机的数据类型。
// AgentState / AgentEvent（宽松字段）见 types.ts —— 双处保持一致。
export interface TaskPlanItem {
  task_id: string;
  agent_id: string;
  goal: string;
  // P1-6 (2026-08-14): 依赖透传 —— 与 types.ts 双处一致。
  depends_on?: string[];
}

export interface TaskPlanEvent {
  state: 'task_plan';
  run_id: string;
  plan: TaskPlanItem[];
}

export type TaskStatusValue = 'queued' | 'running' | 'done' | 'failed' | 'cancelled';

export interface TaskStatusEvent {
  state: 'task_status';
  run_id: string;
  task_id: string;
  status: TaskStatusValue;
  agent_id: string;
  goal: string;
  error: string | null;
  output_preview: string | null;
  // P0-7 (2026-08-20): 重试次数 —— 后端 _emit_task_status 一直携带,此前前端未声明被静默丢弃。
  retry_count?: number;
}

/** 进度可视化 P0-2 (2026-08-12): 整盘概览,与 types.ts TaskProgressEvent 同形。 */
export interface TaskProgressEvent {
  state: 'task_progress';
  run_id: string;
  total: number;
  done: number;
  running: number;
  queued: number;
  failed: number;
  cancelled: number;
}

/** Wave 2 (2026-08-14): reviewer 复核结论事件,与 types.ts TaskReviewEvent 同形。 */
export type ReviewVerdict = 'pass' | 'fail';

export interface TaskReviewEvent {
  state: 'task_review';
  run_id: string;
  task_id: string;
  reviewer_id: string;
  verdict: ReviewVerdict;
  assertion_count: number;
  summary: string;
}

/** P1 todo 接线: agent 自维护清单的全量快照事件。 */
export type TodoStatus = 'pending' | 'in_progress' | 'completed';

export interface TodoItem {
  content: string;
  status: TodoStatus;
  activeForm?: string;
}

export interface TodoSnapshotEvent {
  state: 'todo_snapshot';
  session_id: string;
  todos: TodoItem[];
}

export interface ToolCallRequestFE {
  id: string;
  type: 'function';
  function: {
    name: string;
    arguments: string;
  };
}

export interface ToolCallResultFE {
  tool_call_id: string;
  role: 'tool';
  content: string;
}

export interface AgentEvent {
  state: AgentState;
  iteration: number;
  content?: string;
  reasoning?: string;
  tool_call?: ToolCallRequestFE;
  tool_result?: ToolCallResultFE;
  error?: string;
  /** 阶段 4: 当前执行 agent 的 ID (供前端显示"当前处理 agent") */
  agent_id?: string;
  // Multi-Agent Orchestration (2026-08-11): 宽松字段（与 types.ts AgentEvent 同步）
  run_id?: string;
  plan?: TaskPlanItem[];
  task_id?: string;
  status?: TaskStatusValue;
  goal?: string;
  output_preview?: string | null;
  retry_count?: number;
  // 进度可视化 P0-2 (2026-08-12): 5 元组快照字段,与 TaskProgressEvent 对齐。
  total?: number;
  done?: number;
  running?: number;
  queued?: number;
  failed?: number;
  cancelled?: number;
  // Wave 2 (2026-08-14): task_review 事件 4 可选字段（仅 state='task_review' 时携带）。
  reviewer_id?: string;
  verdict?: ReviewVerdict;
  assertion_count?: number;
  summary?: string;
  // P1 todo 接线: todo_snapshot 全量快照字段。
  todos?: TodoItem[];
  session_id?: string;
}

export async function* parseNDJSONStream(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<AgentEvent, void, unknown> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        buffer += decoder.decode();
        break;
      }
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        try {
          const evt = JSON.parse(trimmed) as AgentEvent;
          yield evt;
        } catch {
          // 忽略解析失败的行
        }
      }
    }

    const trimmed = buffer.trim();
    if (trimmed) {
      try {
        yield JSON.parse(trimmed) as AgentEvent;
      } catch {
        // 忽略
      }
    }
  } finally {
    reader.releaseLock();
  }
}
