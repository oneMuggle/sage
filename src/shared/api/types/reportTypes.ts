/**
 * 报告（report）类型 —— 日报 / 周报（P3）。
 *
 * 与待办 / 工作日志的关系：
 * - ``Todo`` 记「要做什么」，``WorkLog`` 记「做过了什么」；
 * - ``Report`` 是这两者在**某个时间窗内**的聚合快照 —— 正文是 Markdown，
 *   ``stats`` 是生成时刻的统计切片（工作日志条数 / 完成数 / 积压数）。
 *
 * **快照语义**：``content`` 与 ``stats`` 在生成时刻冻结 —— 之后工作日志再改，
 * 历史报告也不回写。因此 ``stats`` 里存的是当时的数字，不是实时查询结果。
 */

// ============================================================================
// 报告
// ============================================================================

/** 报告类型：日报 / 周报。 */
export type ReportType = 'daily' | 'weekly';

/** 工作日志侧的统计切片（只统计 ``confirmed`` 的记录）。 */
export interface ReportWorklogStats {
  total: number;
  /** kind → 条数；kind 取值同 ``WorkLogKind``。 */
  by_kind: Record<string, number>;
  /** 涉及多少个会话。 */
  sessions: number;
  /** 明细（可能为空数组；后端按上限截断）。 */
  items?: { kind: string; content: string; created_at: string }[];
}

/** 待办侧的统计切片。 */
export interface ReportTodoStats {
  /** 窗内完成的待办标题。 */
  completed: string[];
  completed_count: number;
  /** 未完成的高优先级待办标题。 */
  pending_high: string[];
  /** 已逾期的未完成待办标题。 */
  overdue: string[];
  /** 未完成总量（``pending`` + ``in_progress``，不限时间窗）。 */
  pending_count: number;
}

/** 报告的统计快照。 */
export interface ReportStats {
  /** 正文是否由 LLM 生成；``false`` 表示降级为纯模板。 */
  ai_generated?: boolean;
  worklogs?: ReportWorklogStats | null;
  todos?: ReportTodoStats | null;
}

/** 一份存档的报告。 */
export interface Report {
  id: number;
  title: string;
  report_type: ReportType;
  /** 时间窗下界，``YYYY-MM-DD``（含当天整日）。 */
  period_start: string;
  /** 时间窗上界，``YYYY-MM-DD``（含当天整日）。 */
  period_end: string;
  /** Markdown 正文。 */
  content: string;
  stats?: ReportStats | null;
  /** 本地 ISO8601，如 ``2026-11-27T20:30:00.123456``（无时区）。 */
  created_at: string;
  updated_at: string;
}

/** ``POST /reports/generate`` 的响应。 */
export interface ReportGenerateResult {
  report: Report;
}

/** ``GET /reports`` 的响应。 */
export interface ReportListResponse {
  items: Report[];
  total: number;
  limit: number;
  offset: number;
}

/** 生成报告的入参 —— 后端 ``GenerateReportIn`` 声明 ``extra="forbid"``。 */
export interface GenerateReportInput {
  report_type: ReportType;
  /** 缺省时后端按类型取默认窗：日报 = 今天，周报 = 近 7 天（含今天）。 */
  period_start?: string;
  period_end?: string;
  title?: string;
}

/** 报告列表查询参数。 */
export interface ReportListParams {
  report_type?: ReportType;
  limit?: number;
  offset?: number;
}
