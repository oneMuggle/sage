/**
 * Design Studio API 客户端
 *
 * 通过 Electron IPC relay (backendRequest) 调用后端 REST API。
 */
import { backendRequest } from '../../shared/api/backendRequest';

import type {
  ChartSpec,
  CreateProjectInput,
  DesignArtifact,
  DesignArtifactSummary,
  DesignProject,
  DesignProjectDetail,
  DesignSourceBinding,
  DesignSourceInput,
  DesignSystem,
  DesignTemplate,
  EmbedChartResult,
  ExportFormat,
  ExportRequest,
  ExportResult,
  GenerateRequest,
  GenerationProgress,
  IterateRequest,
  IterationMessage,
  OfficeSourceListResponse,
  OfficeSourceRef,
  OutlineResult,
  ProjectTweaks,
  ReviewResult,
  SourcePreview,
} from './types';

const BASE = '/api/v1/design';

// ---------------------------------------------------------------------------
// 系统 & 模板
// ---------------------------------------------------------------------------

/** 列出所有设计系统 */
export async function listSystems(): Promise<DesignSystem[]> {
  return backendRequest<DesignSystem[]>({
    method: 'GET',
    path: `${BASE}/systems`,
  });
}

/** 列出所有模板（可选按 kind 过滤） */
export async function listTemplates(kind?: 'deck' | 'prototype'): Promise<DesignTemplate[]> {
  const params = new URLSearchParams();
  if (kind) params.set('kind', kind);

  return backendRequest<DesignTemplate[]>({
    method: 'GET',
    path: `${BASE}/templates${params.toString() ? `?${params.toString()}` : ''}`,
  });
}

// ---------------------------------------------------------------------------
// 项目 CRUD
// ---------------------------------------------------------------------------

/** 列出所有项目（可选按 kind 过滤） */
export async function listProjects(kind?: 'deck' | 'prototype'): Promise<DesignProject[]> {
  const params = new URLSearchParams();
  if (kind) params.set('kind', kind);

  return backendRequest<DesignProject[]>({
    method: 'GET',
    path: `${BASE}/projects${params.toString() ? `?${params.toString()}` : ''}`,
  });
}

/** 获取项目详情（含最新产物） */
export async function getProject(projectId: string): Promise<DesignProjectDetail> {
  return backendRequest<DesignProjectDetail>({
    method: 'GET',
    path: `${BASE}/projects/${projectId}`,
  });
}

/** 创建新项目（name/system_id/template_id 可省略，后端补默认值） */
export async function createProject(input: CreateProjectInput): Promise<DesignProject> {
  return backendRequest<DesignProject>({
    method: 'POST',
    path: `${BASE}/projects`,
    body: input,
  });
}

/** 删除项目 */
export async function deleteProject(projectId: string): Promise<void> {
  return backendRequest<void>({
    method: 'DELETE',
    path: `${BASE}/projects/${projectId}`,
  });
}

// ---------------------------------------------------------------------------
// 版本历史
// ---------------------------------------------------------------------------

/** 列出项目的全部产物版本（不含 HTML 正文） */
export async function listArtifacts(projectId: string): Promise<DesignArtifactSummary[]> {
  return backendRequest<DesignArtifactSummary[]>({
    method: 'GET',
    path: `${BASE}/projects/${projectId}/artifacts`,
  });
}

/** 获取单个版本（含 HTML 正文，用于预览） */
export async function getArtifact(projectId: string, artifactId: string): Promise<DesignArtifact> {
  return backendRequest<DesignArtifact>({
    method: 'GET',
    path: `${BASE}/projects/${projectId}/artifacts/${artifactId}`,
  });
}

/** 把旧版本恢复为新版本（服务端不调用 LLM） */
export async function restoreArtifact(
  projectId: string,
  artifactId: string,
): Promise<DesignArtifact> {
  return backendRequest<DesignArtifact>({
    method: 'POST',
    path: `${BASE}/projects/${projectId}/artifacts/${artifactId}/restore`,
  });
}

// ---------------------------------------------------------------------------
// 迭代消息
// ---------------------------------------------------------------------------

/** 读取持久化的迭代对话历史 */
export async function listMessages(projectId: string): Promise<IterationMessage[]> {
  return backendRequest<IterationMessage[]>({
    method: 'GET',
    path: `${BASE}/projects/${projectId}/messages`,
  });
}

/** 读取生成阶段进度（轮询用） */
export async function getProgress(projectId: string): Promise<GenerationProgress> {
  return backendRequest<GenerationProgress>({
    method: 'GET',
    path: `${BASE}/projects/${projectId}/progress`,
  });
}

/** 对最新产物运行设计 Lint（无 LLM） */
export async function reviewArtifact(projectId: string): Promise<ReviewResult> {
  return backendRequest<ReviewResult>({
    method: 'GET',
    path: `${BASE}/projects/${projectId}/review`,
  });
}

/**
 * 订阅阶段进度流（Electron 事件通道可用时）。
 * 返回取消函数；环境不支持时返回 null（调用方回退到轮询）。
 */
export function subscribeDesignProgress(
  projectId: string,
  handler: (progress: GenerationProgress) => void,
): (() => void) | null {
  const bridge = typeof window !== 'undefined' ? window.electronAPI : undefined;
  if (!bridge?.listen) return null;
  let unlisten: (() => void) | null = null;
  void bridge
    .listen<GenerationProgress>(`design-progress-${projectId}`, handler)
    .then((fn) => {
      unlisten = fn;
    })
    .catch(() => undefined);
  return () => {
    if (unlisten) unlisten();
  };
}

// ---------------------------------------------------------------------------
// 资源（Word 大纲 / 数据源 / 图表）
// ---------------------------------------------------------------------------

/** 从 .docx 提取大纲（后端只接受 docx 路径） */
export async function extractOutline(source: DesignSourceInput): Promise<OutlineResult> {
  return backendRequest<OutlineResult>({
    method: 'POST',
    path: `${BASE}/outline`,
    body: { ...source },
  });
}

/** 列出可作设计素材的 Office 文档（word / excel） */
export async function listOfficeSources(docType?: 'word' | 'excel'): Promise<OfficeSourceRef[]> {
  const params = new URLSearchParams();
  if (docType) params.set('doc_type', docType);

  const response = await backendRequest<OfficeSourceListResponse>({
    method: 'GET',
    path: `${BASE}/office-sources${params.toString() ? `?${params.toString()}` : ''}`,
  });
  return response.items ?? [];
}

/** 读取项目的数据源绑定（未绑定时后端返回 404） */
export async function getSource(projectId: string): Promise<DesignSourceBinding> {
  return backendRequest<DesignSourceBinding>({
    method: 'GET',
    path: `${BASE}/projects/${projectId}/source`,
  });
}

/** 绑定数据源（xlsx/csv/json） */
export async function bindSource(
  projectId: string,
  source: DesignSourceInput,
): Promise<DesignSourceBinding> {
  return backendRequest<DesignSourceBinding>({
    method: 'POST',
    path: `${BASE}/projects/${projectId}/source`,
    body: { ...source },
  });
}

/** 绑定前预览数据源（列名/行数/样例） */
export async function previewSource(source: DesignSourceInput): Promise<SourcePreview> {
  return backendRequest<SourcePreview>({
    method: 'POST',
    path: `${BASE}/source/preview`,
    body: { ...source },
  });
}

/** 解绑数据源 */
export async function unbindSource(projectId: string): Promise<void> {
  return backendRequest<void>({
    method: 'DELETE',
    path: `${BASE}/projects/${projectId}/source`,
  });
}

/** 用当前绑定的数据源重新生成（SSE） */
export async function refreshArtifact(projectId: string): Promise<DesignArtifact> {
  return readArtifactFromSse(
    await backendRequest<string>({
      method: 'POST',
      path: `${BASE}/projects/${projectId}/refresh`,
      responseType: 'text',
    }),
  );
}

/** 渲染图表并注入最新产物（不调 LLM，追加新版本） */
export async function embedChart(
  projectId: string,
  chart: ChartSpec,
  slot?: string,
): Promise<EmbedChartResult> {
  return backendRequest<EmbedChartResult>({
    method: 'POST',
    path: `${BASE}/projects/${projectId}/chart`,
    body: slot ? { chart, slot } : { chart },
  });
}

// ---------------------------------------------------------------------------
// 微调参数
// ---------------------------------------------------------------------------

/** 读取项目微调参数（未设置时返回空默认值） */
export async function getTweaks(projectId: string): Promise<ProjectTweaks> {
  return backendRequest<ProjectTweaks>({
    method: 'GET',
    path: `${BASE}/projects/${projectId}/tweaks`,
  });
}

/** 合并保存项目微调参数；replace=true 时按精确字段集覆盖（null 清空） */
export async function updateTweaks(
  projectId: string,
  tweaks: ProjectTweaks,
  replace = false,
): Promise<ProjectTweaks> {
  return backendRequest<ProjectTweaks>({
    method: 'PUT',
    path: `${BASE}/projects/${projectId}/tweaks`,
    body: replace ? { ...tweaks, replace: true } : tweaks,
  });
}

// ---------------------------------------------------------------------------
// 生成 & 迭代
// ---------------------------------------------------------------------------

/** 生成设计产物 */
export async function generateArtifact(
  projectId: string,
  request: GenerateRequest,
): Promise<DesignArtifact> {
  return readArtifactFromSse(
    await backendRequest<string>({
      method: 'POST',
      path: `${BASE}/projects/${projectId}/generate`,
      body: request,
      responseType: 'text',
    }),
  );
}

/** 迭代设计产物（基于用户反馈） */
export async function iterateArtifact(
  projectId: string,
  request: IterateRequest,
): Promise<DesignArtifact> {
  return readArtifactFromSse(
    await backendRequest<string>({
      method: 'POST',
      path: `${BASE}/projects/${projectId}/iterate`,
      body: request,
      responseType: 'text',
    }),
  );
}

/**
 * 从后端 SSE 响应体中取出最终产物。
 *
 * 后端 generate/iterate 是 SSE 端点（progress → complete → [error]），
 * IPC relay 以 text 形式返回完整响应体，这里解析 `complete` / `error` 事件。
 */
function readArtifactFromSse(body: string): DesignArtifact {
  let artifact: DesignArtifact | null = null;
  let errorDetail: string | null = null;

  for (const block of body.split('\n\n')) {
    const lines = block.split('\n');
    const eventLine = lines.find((line) => line.startsWith('event:'));
    const dataLine = lines.find((line) => line.startsWith('data:'));
    if (!eventLine || !dataLine) continue;

    const eventName = eventLine.slice('event:'.length).trim();
    const payload = JSON.parse(dataLine.slice('data:'.length).trim()) as {
      artifact?: DesignArtifact;
      detail?: string;
    };

    if (eventName === 'complete' && payload.artifact) {
      artifact = payload.artifact;
    } else if (eventName === 'error') {
      errorDetail = payload.detail ?? 'Design generation failed';
    }
  }

  if (errorDetail) throw new Error(errorDetail);
  if (!artifact) throw new Error('生成未返回产物');
  return artifact;
}

// ---------------------------------------------------------------------------
// 导出
// ---------------------------------------------------------------------------

/** 导出设计产物（PDF/PPTX/ZIP/HTML）；inline=true 时返回 base64 内容 */
export async function exportArtifact(
  projectId: string,
  format: ExportFormat,
  inline = false,
): Promise<ExportResult> {
  const request: ExportRequest = inline ? { format, inline: true } : { format };
  return backendRequest<ExportResult>({
    method: 'POST',
    path: `${BASE}/projects/${projectId}/export`,
    body: request,
  });
}
