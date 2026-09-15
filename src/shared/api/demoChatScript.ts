/**
 * 演示模式 (2026-08-27) — 脚本化聊天流。
 *
 * chatApi.chatStream 在演示模式下直接走这里：不发任何请求，
 * 按固定时间线推送与真实后端完全同形的 AgentEvent 序列
 * （思考 → 推理 → 任务规划 → 子任务执行/工具调用 → 评审打回重试 →
 *   复核通过 → todo 快照 → 流式正文 → done），
 * 让聊天页 / 编排看板 / 工具调用折叠卡全部按真实逻辑渲染。
 *
 * 时间线约 25s。cancel() 清空全部未触发的定时器。
 */
import { DEMO_SURVEY_REPORT_MD, demoAppendMessages } from './demoInterceptors';
import type { AgentEvent } from './types';

export interface DemoChatHandlers {
  onEvent: (event: AgentEvent) => void;
  onError?: (error: Error) => void;
  onDone?: () => void;
}

const RUN_ID = 'run-demo-001';
const WORKSPACE = '/home/fz/sage-workspace';

const PLAN = {
  task1: { task_id: 'task-1', agent_id: 'executor-b', goal: '检索近三年大模型医学应用文献' },
  task2: { task_id: 'task-2', agent_id: 'executor-a', goal: '筛选核心论文并提取观点' },
  task3: { task_id: 'task-3', agent_id: 'planner', goal: '生成文献对比表与综述报告' },
  task4: { task_id: 'task-4', agent_id: 'reviewer', goal: '终审全部产物' },
};

/** task_status 事件速写 — 必填字段全带，缺省 error/output_preview 为 null。 */
function taskStatus(
  taskId: string,
  agentId: string,
  goal: string,
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled',
  extra?: { output_preview?: string; retry_count?: number },
): AgentEvent {
  return {
    state: 'task_status',
    iteration: 1,
    run_id: RUN_ID,
    task_id: taskId,
    status,
    agent_id: agentId,
    goal,
    output_preview: extra?.output_preview ?? null,
    ...(extra?.retry_count !== undefined ? { retry_count: extra.retry_count } : {}),
  };
}

/** acting 事件 — 携带工具调用（arguments 必须是 JSON 字符串）。 */
function acting(toolCallId: string, name: string, args: Record<string, unknown>): AgentEvent {
  return {
    state: 'acting',
    iteration: 1,
    tool_call: {
      id: toolCallId,
      type: 'function',
      function: { name, arguments: JSON.stringify(args) },
    },
  };
}

/** observing 事件 — content 是 JSON 字符串，metadata 供前端提取徽章。 */
function observing(toolCallId: string, resultPayload: Record<string, unknown>): AgentEvent {
  return {
    state: 'observing',
    iteration: 1,
    tool_result: {
      tool_call_id: toolCallId,
      role: 'tool',
      content: JSON.stringify(resultPayload),
    },
  };
}

function taskReview(
  taskId: string,
  verdict: 'pass' | 'fail',
  assertionCount: number,
  summary: string,
): AgentEvent {
  return {
    state: 'task_review',
    iteration: 1,
    run_id: RUN_ID,
    task_id: taskId,
    reviewer_id: 'reviewer',
    verdict,
    assertion_count: assertionCount,
    summary,
  };
}

/** 把最终报告按行切成流式块（保留换行，表格渲染友好）。 */
function chunkReport(text: string): string[] {
  return text
    .split('\n')
    .map((line) => `${line}\n`)
    .filter((c) => c.length > 0);
}

export function runDemoChatStream(
  sessionId: string,
  message: string,
  handlers: DemoChatHandlers,
): { streamId: string; cancel: () => void } {
  const streamId = `demo-stream-${sessionId.slice(0, 8)}`;
  const timers: ReturnType<typeof setTimeout>[] = [];
  let cancelled = false;

  const schedule = (delayMs: number, fn: () => void): void => {
    timers.push(
      setTimeout(() => {
        if (!cancelled) fn();
      }, delayMs),
    );
  };
  const emit = (delayMs: number, evt: AgentEvent): void => {
    schedule(delayMs, () => handlers.onEvent(evt));
  };

  /* ── 阶段 1：思考与推理 ─────────────────────────────── */
  emit(350, { state: 'thinking', iteration: 1, agent_id: 'planner' });
  emit(900, {
    state: 'reasoning',
    iteration: 1,
    agent_id: 'planner',
    reasoning:
      '任务拆解：用户要求调研近三年大语言模型在医学领域的应用，' +
      '整理核心文献并产出对比表与综述报告。\n' +
      '规划 4 个子任务：文献收集（executor-b）、精读提取（executor-a）、' +
      '对比表与综述生成（planner，依赖前两项）、终审（reviewer）。',
  });
  emit(1600, {
    state: 'reasoning_delta',
    iteration: 1,
    agent_id: 'planner',
    reasoning: '\n审查标准：引用 ≥ 20 篇、近三年来源占比 ≥ 50%、对比表字段齐全、综述结构完整。',
  });

  /* ── 阶段 2：任务规划（必须先于一切 task_status） ───── */
  emit(2300, {
    state: 'task_plan',
    iteration: 1,
    run_id: RUN_ID,
    plan: [
      PLAN.task1,
      PLAN.task2,
      { ...PLAN.task3, depends_on: ['task-1', 'task-2'] },
      { ...PLAN.task4, depends_on: ['task-1', 'task-2', 'task-3'] },
    ],
  });
  emit(2700, {
    state: 'task_progress',
    iteration: 1,
    run_id: RUN_ID,
    total: 4,
    done: 0,
    running: 0,
    queued: 4,
    failed: 0,
    cancelled: 0,
  });

  /* ── 阶段 3：并行执行 + 工具调用 ────────────────────── */
  emit(3000, taskStatus(PLAN.task1.task_id, PLAN.task1.agent_id, PLAN.task1.goal, 'running'));
  emit(3300, taskStatus(PLAN.task2.task_id, PLAN.task2.agent_id, PLAN.task2.goal, 'running'));
  emit(
    4000,
    acting('tc-demo-1', 'web_search', {
      query: 'large language model 医学应用 survey 2024..2026',
      top_k: 30,
    }),
  );
  emit(
    5200,
    observing('tc-demo-1', {
      hits: 86,
      metadata: { badge: 'success', note: '初检命中 86 条，去重后 61 条' },
    }),
  );
  emit(
    5900,
    acting('tc-demo-2', 'read_file', {
      path: `${WORKSPACE}/data/文献清单-初筛-86篇.csv`,
    }),
  );
  emit(
    7000,
    observing('tc-demo-2', {
      rows: 61,
      metadata: { badge: 'success', note: '读取初筛清单 61 行 × 7 列' },
    }),
  );
  emit(
    7800,
    taskStatus(PLAN.task1.task_id, PLAN.task1.agent_id, PLAN.task1.goal, 'done', {
      output_preview: '初检命中 86 条，经去重与年份过滤保留 61 条，覆盖三大方向',
    }),
  );
  emit(
    9000,
    taskStatus(PLAN.task2.task_id, PLAN.task2.agent_id, PLAN.task2.goal, 'done', {
      output_preview: '筛选出 23 篇核心论文，方法/数据集/结论字段提取完成',
    }),
  );

  /* ── 阶段 4：评审打回 → 重试 → 复核通过 ─────────────── */
  emit(
    9800,
    taskReview(PLAN.task2.task_id, 'fail', 4, '缺少 2026 年最新来源，建议补充近半年文献 3 篇以上'),
  );
  emit(
    10400,
    taskStatus(PLAN.task2.task_id, PLAN.task2.agent_id, PLAN.task2.goal, 'running', {
      retry_count: 1,
    }),
  );
  emit(
    12400,
    taskStatus(PLAN.task2.task_id, PLAN.task2.agent_id, PLAN.task2.goal, 'done', {
      output_preview: '已补充 4 篇 2026 年文献，最终 23 篇提取字段齐全',
      retry_count: 1,
    }),
  );
  emit(13000, taskReview(PLAN.task2.task_id, 'pass', 4, '来源时效达标，提取字段齐全，通过'));

  /* ── 阶段 5：对比表 + 综述报告（office_create × 2） ─── */
  emit(13600, taskStatus(PLAN.task3.task_id, PLAN.task3.agent_id, PLAN.task3.goal, 'running'));
  emit(
    14100,
    acting('tc-demo-3', 'office_create', {
      doc_type: 'excel',
      filename: '文献对比表-23篇核心文献.xlsx',
      workspace: WORKSPACE,
    }),
  );
  emit(
    15000,
    observing('tc-demo-3', {
      doc_id: 'of-2',
      metadata: { badge: 'success', note: 'Excel 对比表生成成功' },
    }),
  );
  emit(
    15600,
    acting('tc-demo-4', 'office_create', {
      doc_type: 'word',
      filename: '文献综述报告-大模型医学应用.docx',
      workspace: WORKSPACE,
    }),
  );
  emit(
    16600,
    observing('tc-demo-4', {
      doc_id: 'of-1',
      metadata: { badge: 'success', note: 'Word 综述报告生成成功' },
    }),
  );
  emit(
    17200,
    taskStatus(PLAN.task3.task_id, PLAN.task3.agent_id, PLAN.task3.goal, 'done', {
      output_preview: '对比表（23 篇 × 6 列）与综述报告（6 章节）生成完成',
    }),
  );

  /* ── 阶段 6：终审 ───────────────────────────────────── */
  emit(17800, taskStatus(PLAN.task4.task_id, PLAN.task4.agent_id, PLAN.task4.goal, 'running'));
  emit(
    19000,
    taskStatus(PLAN.task4.task_id, PLAN.task4.agent_id, PLAN.task4.goal, 'done', {
      output_preview: '终审通过：5 项断言全部满足',
    }),
  );
  emit(
    19400,
    taskReview(PLAN.task4.task_id, 'pass', 5, '对比表字段齐全，综述含背景/发现/空白三段'),
  );

  /* ── 阶段 7：todo 快照收尾 ──────────────────────────── */
  emit(19800, {
    state: 'todo_snapshot',
    iteration: 1,
    session_id: sessionId,
    todos: [
      { content: '拆解任务并规划执行顺序', status: 'completed' },
      { content: '检索近三年大模型医学应用文献', status: 'completed' },
      { content: '筛选 23 篇核心论文并提取观点', status: 'completed' },
      { content: '生成文献对比表与综述报告', status: 'completed' },
      { content: '终审全部产物', status: 'completed' },
    ],
  });

  /* ── 阶段 8：流式正文（20.2s → 24s） ────────────────── */
  const chunks = chunkReport(DEMO_SURVEY_REPORT_MD);
  const streamStart = 20200;
  const streamSpan = 3800;
  chunks.forEach((chunk, i) => {
    emit(streamStart + Math.round((i * streamSpan) / chunks.length), {
      state: 'content_delta',
      iteration: 1,
      content: chunk,
    });
  });

  /* ── 阶段 9：会话元数据更新 + done ──────────────────── */
  emit(24600, { state: 'idle', iteration: 1, type: 'session_updated', session_id: sessionId });
  schedule(25000, () => {
    handlers.onEvent({ state: 'done', iteration: 2 });
    demoAppendMessages(sessionId, message, DEMO_SURVEY_REPORT_MD);
    handlers.onDone?.();
  });

  return {
    streamId,
    cancel: () => {
      cancelled = true;
      timers.forEach((t) => clearTimeout(t));
      timers.length = 0;
    },
  };
}
