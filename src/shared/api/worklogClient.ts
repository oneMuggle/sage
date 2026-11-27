/**
 * IPC client for the worklog (工作日志) subsystem (P2).
 *
 * Translates to backend HTTP via Electron preload:
 *   worklog_list     → GET    /api/v1/worklogs
 *   worklog_summary  → GET    /api/v1/worklogs/summary
 *   worklog_extract  → POST   /api/v1/worklogs/extract
 *   worklog_create   → POST   /api/v1/worklogs
 *   worklog_update   → PUT    /api/v1/worklogs/{id}
 *   worklog_delete   → DELETE /api/v1/worklogs/{id}
 *   worklog_confirm  → POST   /api/v1/worklogs/{id}/confirm
 *   worklog_dismiss  → POST   /api/v1/worklogs/{id}/dismiss
 *
 * 与 todos 的关系：todo 记「要做什么」，worklog 记「做过了什么」；两者一起
 * 构成日报 / 周报的双数据源。对话抽取的候选先落 ``pending``，人工确认
 * （``confirm``）后才进报告统计 —— 抽取可能误记，这一步是质量闸门。
 *
 * All methods throw on IPC failure; callers wrap in try/catch and surface a
 * toast on failure.
 */
import { invoke } from './desktopInvoke';
import type {
  CreateWorkLogInput,
  UpdateWorkLogInput,
  WorkLog,
  WorkLogExtractResult,
  WorkLogListParams,
  WorkLogListResponse,
  WorkLogSummary,
} from './types';

/** 摘要查询的日期窗（``YYYY-MM-DD``，含边界整日）。 */
export interface WorkLogSummaryParams {
  date_from?: string;
  date_to?: string;
  todo_id?: number;
  project_tag?: string;
}

export const worklogClient = {
  /**
   * 按时间倒序列出工作日志。
   *
   * ``date_from`` / ``date_to`` 会被 IPC 层转换成后端的 ``from`` / ``to``
   * 别名（Python 里 ``from`` 是关键字）。
   */
  async list(params?: WorkLogListParams): Promise<WorkLogListResponse> {
    return invoke<WorkLogListResponse>('worklog_list', { ...(params ?? {}) });
  },

  /** 时间窗内统计快照 —— 只统计已确认的记录。 */
  async summary(params?: WorkLogSummaryParams): Promise<WorkLogSummary> {
    return invoke<WorkLogSummary>('worklog_summary', { ...(params ?? {}) });
  },

  async create(input: CreateWorkLogInput): Promise<WorkLog> {
    return invoke<WorkLog>('worklog_create', { ...input });
  },

  /** 编辑正文 / 分类 / 关联项。状态迁移不走这里。 */
  async update(id: number, changes: UpdateWorkLogInput): Promise<WorkLog> {
    return invoke<WorkLog>('worklog_update', { id, ...changes });
  },

  async delete(id: number): Promise<void> {
    await invoke<void>('worklog_delete', { id });
  },

  /** 待确认候选 → 已确认（此后进报告统计）。 */
  async confirm(id: number): Promise<WorkLog> {
    return invoke<WorkLog>('worklog_confirm', { id });
  },

  /** 忽略候选；已确认的记录也可撤回。 */
  async dismiss(id: number): Promise<WorkLog> {
    return invoke<WorkLog>('worklog_dismiss', { id });
  },

  /** 从会话提炼日志候选（不落库，由用户逐条确认）。 */
  async extractFromSession(
    sessionId: string,
    messageIds?: string[],
  ): Promise<WorkLogExtractResult> {
    return invoke<WorkLogExtractResult>('worklog_extract', {
      session_id: sessionId,
      ...(messageIds && messageIds.length > 0 ? { message_ids: messageIds } : {}),
    });
  },
};

export function formatWorklogListSummary(
  res: Pick<WorkLogListResponse, 'items' | 'total' | 'limit' | 'offset'>,
): string {
  return `${res.items.length}/${res.total} worklogs · offset ${res.offset} · limit ${res.limit}`;
}

export function auditWorklogClientGovernance(): string {
  return JSON.stringify(
    {
      schema: 'sage.shared.api.worklog_client.governance.v1',
      phase: 'P2',
      methods: [
        'list',
        'summary',
        'create',
        'update',
        'delete',
        'confirm',
        'dismiss',
        'extractFromSession',
      ],
      sampleSummary: formatWorklogListSummary({ items: [], total: 0, limit: 50, offset: 0 }),
    },
    null,
    2,
  );
}
