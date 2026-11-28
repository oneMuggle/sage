/**
 * Presentation API client — ppt-master 确定性工程层（SVG -> 原生可编辑 PPTX）。
 *
 * 后端对应 backend/api/presentation_routes.py（挂载在 /api/v1/presentation）。
 * 与 officeGenerateApi 一致使用 backendRequest（Electron 主进程带鉴权中继，
 * 网页回退模式走同源带 token 的 fetch），不在渲染层裸调 fetch。
 */

import { backendRequest } from './backendRequest';
import { handleApiError } from './utils';

/** 质量报告中的单条问题（字段来自 ppt-master，结构可能随上游演进）。 */
export interface PresentationIssue {
  code?: string;
  message?: string;
  file?: string;
  [key: string]: unknown;
}

export interface PresentationEnvironment {
  ready: boolean;
  skill_root?: string | null;
  python?: string | null;
  error?: string | null;
}

export interface PresentationRenderRequest {
  workspace_path: string;
  filename: string;
  svg_slides: string[];
}

export interface PresentationRenderResult {
  success: boolean;
  output_path?: string | null;
  quality_passed: boolean;
  blocking_errors: PresentationIssue[];
  warnings: PresentationIssue[];
  summary: Record<string, unknown>;
  message: string;
}

function asIssueList(value: unknown): PresentationIssue[] {
  return Array.isArray(value) ? (value as PresentationIssue[]) : [];
}

function normalizeResult(raw: PresentationRenderResult): PresentationRenderResult {
  return {
    ...raw,
    blocking_errors: asIssueList(raw.blocking_errors),
    warnings: asIssueList(raw.warnings),
    summary: raw.summary ?? {},
  };
}

export const presentationApi = {
  async getEnvironment(): Promise<PresentationEnvironment> {
    try {
      return await backendRequest<PresentationEnvironment>({
        path: '/api/v1/presentation/environment',
        method: 'GET',
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  async renderFromSvgs(req: PresentationRenderRequest): Promise<PresentationRenderResult> {
    try {
      const raw = await backendRequest<PresentationRenderResult>({
        path: '/api/v1/presentation/render-svgs',
        method: 'POST',
        body: req,
      });
      return normalizeResult(raw);
    } catch (error) {
      throw handleApiError(error);
    }
  },
};
