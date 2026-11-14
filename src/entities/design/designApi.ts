/**
 * Design Studio API 客户端
 *
 * 通过 Electron IPC relay (backendRequest) 调用后端 REST API。
 */
import { backendRequest } from '../../shared/api/backendRequest';

import type {
  DesignArtifact,
  DesignProject,
  DesignProjectDetail,
  DesignSystem,
  DesignTemplate,
  ExportFormat,
  ExportRequest,
  ExportResult,
  GenerateRequest,
  IterateRequest,
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
export async function listTemplates(
  kind?: 'deck' | 'prototype',
): Promise<DesignTemplate[]> {
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
export async function listProjects(
  kind?: 'deck' | 'prototype',
): Promise<DesignProject[]> {
  const params = new URLSearchParams();
  if (kind) params.set('kind', kind);

  return backendRequest<DesignProject[]>({
    method: 'GET',
    path: `${BASE}/projects${params.toString() ? `?${params.toString()}` : ''}`,
  });
}

/** 获取项目详情（含最新产物） */
export async function getProject(
  projectId: string,
): Promise<DesignProjectDetail> {
  return backendRequest<DesignProjectDetail>({
    method: 'GET',
    path: `${BASE}/projects/${projectId}`,
  });
}

/** 创建新项目 */
export async function createProject(input: {
  name: string;
  kind: 'deck' | 'prototype';
  system_id: string;
  template_id: string;
  brief: string;
}): Promise<DesignProject> {
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

/** 导出设计产物（PDF/PPTX/ZIP/HTML） */
export async function exportArtifact(
  projectId: string,
  format: ExportFormat,
): Promise<ExportResult> {
  const request: ExportRequest = { format };
  return backendRequest<ExportResult>({
    method: 'POST',
    path: `${BASE}/projects/${projectId}/export`,
    body: request,
  });
}
