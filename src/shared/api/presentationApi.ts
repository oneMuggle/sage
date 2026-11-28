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

/** 模板种类：品牌 / 风格 / 版式 / 整套。 */
export type PresentationTemplateKind = 'brand' | 'style' | 'layout' | 'deck';

export interface PresentationTemplate {
  kind: PresentationTemplateKind | string;
  template_id: string;
  name: string;
  summary: string;
  primary_color?: string | null;
  canvas_format?: string | null;
  page_count?: number | null;
  page_types: string[];
  root_path: string;
}

export interface PresentationTemplateList {
  available: boolean;
  error?: string | null;
  templates: PresentationTemplate[];
}

export interface PresentationTemplateRefreshResult {
  available: boolean;
  count: number;
  error?: string | null;
}

export interface PresentationRenderRequest {
  workspace_path: string;
  filename: string;
  svg_slides: string[];
  /** ``kind:id`` 选择；缺省或空数组表示不使用模板库。 */
  template_ids?: string[];
}

export interface PresentationRenderResult {
  success: boolean;
  output_path?: string | null;
  quality_passed: boolean;
  blocking_errors: PresentationIssue[];
  warnings: PresentationIssue[];
  summary: Record<string, unknown>;
  message: string;
  templates_applied: string[];
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
    templates_applied: Array.isArray(raw.templates_applied) ? raw.templates_applied : [],
  };
}

function normalizeTemplateList(raw: PresentationTemplateList): PresentationTemplateList {
  return {
    available: Boolean(raw.available),
    error: raw.error ?? null,
    templates: Array.isArray(raw.templates) ? raw.templates : [],
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

  /** 模板库列表；技能目录缺失时后端返回 available=false 而非报错。 */
  async getTemplates(kind?: PresentationTemplateKind): Promise<PresentationTemplateList> {
    try {
      const query = kind ? `?kind=${encodeURIComponent(kind)}` : '';
      const raw = await backendRequest<PresentationTemplateList>({
        path: `/api/v1/presentation/templates${query}`,
        method: 'GET',
      });
      return normalizeTemplateList(raw);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  /** 重扫模板库（技能目录新增/删除模板后由用户显式触发）。 */
  async refreshTemplates(): Promise<PresentationTemplateRefreshResult> {
    try {
      return await backendRequest<PresentationTemplateRefreshResult>({
        path: '/api/v1/presentation/templates/refresh',
        method: 'POST',
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },
};
