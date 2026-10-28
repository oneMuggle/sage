/**
 * Plan Mode 增强（2026-10-28）共享类型。
 *
 * 这些类型同时被后端事件载荷（`chatAndEventTypes.ts`）、Zustand 槽位
 * （`chatStreamStore.ts`）与 UI 组件（`ResearchSummaryCard` /
 * `StepConfirmDialog`）消费，故定义在 `shared` 层 —— `shared` 不得反向
 * 依赖 `components`。
 */

export interface ResearchFinding {
  title: string;
  summary: string;
  relevance: 'high' | 'medium' | 'low';
  sources: string[];
}

export interface ResearchSource {
  url: string;
  title: string;
  snippet: string;
}

/** scout_deep 深度调研报告（对齐 backend/orchestration/research_report.py）。 */
export interface ResearchReport {
  topic: string;
  findings: ResearchFinding[];
  sources: ResearchSource[];
  confidence: number;
  estimated_effort: string;
  synthesis: string;
}

/** 自动确认点信息（对齐 backend/orchestration/confirm_marker.py 命中类别）。 */
export interface StepConfirmInfo {
  /** 当前步骤描述 */
  goal: string;
  /** 步骤 ID */
  stepId: string;
  /** 影响预估（如 "将删除 3 个文件"） */
  impact?: string;
  /** 上一步输出摘要 */
  previousOutput?: string;
  /** 下一步预览 */
  nextStepPreview?: string;
  /** 触发的规则类别 */
  categories?: string[];
}

/** 用户对确认点的应答动作。 */
export type StepConfirmAction = 'continue' | 'skip' | 'abort';
