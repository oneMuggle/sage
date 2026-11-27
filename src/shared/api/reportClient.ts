/**
 * IPC client for the report (日报 / 周报) subsystem (P3).
 *
 * Translates to backend HTTP via Electron preload:
 *   report_generate → POST /api/v1/reports/generate   （生成即存档）
 *   report_list     → GET  /api/v1/reports
 *   report_get      → GET  /api/v1/reports/{id}
 *
 * **参数名必须是 snake_case** —— ``electron/invoke.ts`` 只对**请求体**做
 * camelCase → snake_case 转换，路由的 body/path 构造器拿到的是原始 args。
 * 而后端 ``GenerateReportIn`` 声明了 ``extra="forbid"``，多传一个键就 422。
 *
 * All methods throw on IPC failure; callers wrap in try/catch and surface a
 * toast / inline error on failure.
 */
import { invoke } from './desktopInvoke';
import type {
  GenerateReportInput,
  Report,
  ReportGenerateResult,
  ReportListParams,
  ReportListResponse,
} from './types';

export const reportClient = {
  /**
   * 聚合工作日志 + 待办 → 生成 Markdown → **存档**。
   *
   * 返回的就是已经存好的那条记录 —— 正文与统计快照在生成时刻冻结。
   */
  async generate(input: GenerateReportInput): Promise<Report> {
    const result = await invoke<ReportGenerateResult>('report_generate', {
      report_type: input.report_type,
      ...(input.period_start ? { period_start: input.period_start } : {}),
      ...(input.period_end ? { period_end: input.period_end } : {}),
      ...(input.title ? { title: input.title } : {}),
    });
    return result.report;
  },

  /** 存档报告列表（按创建时间倒序）。 */
  async list(params?: ReportListParams): Promise<ReportListResponse> {
    return invoke<ReportListResponse>('report_list', { ...(params ?? {}) });
  },

  /** 单份存档报告详情。 */
  async get(id: number): Promise<Report> {
    return invoke<Report>('report_get', { id });
  },
};
