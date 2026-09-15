// src/features/artifacts/artifactApi.ts

import { backendRequest } from '../../shared/api/backendRequest';
import { isDemoMode } from '../../shared/api/demoFlag';

export type ArtifactKind =
  | 'markdown'
  | 'code'
  | 'image'
  | 'csv'
  | 'json'
  | 'pdf' // F11 (round4 批次 D): data_url iframe 内嵌预览
  | 'docx' // C-2 (round5 批次 C): 后端转换 HTML 内嵌预览
  | 'xlsx'
  | 'pptx'
  | 'text';

export interface Artifact {
  id: string;
  session_id: string;
  tool_call_id: string | null;
  path: string;
  name: string;
  kind: ArtifactKind;
  size: number;
  created_at: number;
}

export interface ArtifactContent {
  ok: boolean;
  error?: string;
  kind?: string;
  content?: string;
  data_url?: string;
  /** C-2 (round5 批次 C): office 三件套预览——后端已全转义的 HTML 片段 */
  html?: string;
  truncated?: boolean;
}

function ensureBackendAccess(): void {
  if (isDemoMode()) throw new Error('演示模式不支持后端操作');
}

export async function listArtifacts(sessionId: string): Promise<Artifact[]> {
  ensureBackendAccess();
  try {
    const data = await backendRequest<{ artifacts?: Artifact[] }>({
      path: `/api/v1/sessions/${encodeURIComponent(sessionId)}/artifacts`,
    });
    return data.artifacts ?? [];
  } catch (error) {
    throw new Error(
      `listArtifacts failed: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
}

export async function readArtifactContent(
  sessionId: string,
  artifactId: string,
): Promise<ArtifactContent> {
  ensureBackendAccess();
  try {
    return await backendRequest<ArtifactContent>({
      path: `/api/v1/sessions/${encodeURIComponent(sessionId)}/artifacts/${encodeURIComponent(artifactId)}/content`,
    });
  } catch (error) {
    throw new Error(
      `readArtifactContent failed: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
}

export async function revealArtifact(
  sessionId: string,
  artifactId: string,
): Promise<{ ok: boolean; error?: string }> {
  ensureBackendAccess();
  return backendRequest<{ ok: boolean; error?: string }>({
    path: `/api/v1/sessions/${encodeURIComponent(sessionId)}/artifacts/${encodeURIComponent(artifactId)}/reveal`,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
}

// ==================== Version History (Phase 2 M2) ====================

export interface ArtifactVersion {
  artifact_id: string;
  version_num: number;
  content_hash: string;
  snapshot_path: string;
  created_at: number;
  note: string | null;
}

export interface ArtifactVersionWithContent extends ArtifactVersion {
  content: string;
}

export async function listArtifactVersions(
  sessionId: string,
  artifactId: string,
): Promise<ArtifactVersion[]> {
  ensureBackendAccess();
  try {
    const data = await backendRequest<{ versions?: ArtifactVersion[] }>({
      path: `/api/v1/sessions/${encodeURIComponent(sessionId)}/artifacts/${encodeURIComponent(artifactId)}/versions`,
    });
    return data.versions ?? [];
  } catch (error) {
    throw new Error(
      `listArtifactVersions failed: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
}

export async function getArtifactVersion(
  sessionId: string,
  artifactId: string,
  versionNum: number,
): Promise<ArtifactVersionWithContent> {
  ensureBackendAccess();
  try {
    return await backendRequest<ArtifactVersionWithContent>({
      path: `/api/v1/sessions/${encodeURIComponent(sessionId)}/artifacts/${encodeURIComponent(artifactId)}/versions/${versionNum}`,
    });
  } catch (error) {
    throw new Error(
      `getArtifactVersion failed: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
}

export interface RestoreVersionResponse {
  restored_from: number;
  new_version: ArtifactVersion;
}

export async function restoreArtifactVersion(
  sessionId: string,
  artifactId: string,
  versionNum: number,
  note = 'restore',
): Promise<RestoreVersionResponse> {
  ensureBackendAccess();
  try {
    return await backendRequest<RestoreVersionResponse>({
      path: `/api/v1/sessions/${encodeURIComponent(sessionId)}/artifacts/${encodeURIComponent(artifactId)}/versions/restore`,
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: { version_num: versionNum, note },
    });
  } catch (error) {
    throw new Error(
      `restoreArtifactVersion failed: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
}

export interface UpdateArtifactResponse {
  version: ArtifactVersion;
}

export async function updateArtifactContent(
  sessionId: string,
  artifactId: string,
  baseHash: string,
  content: string,
  note = 'edit',
): Promise<UpdateArtifactResponse> {
  ensureBackendAccess();
  try {
    return await backendRequest<UpdateArtifactResponse>({
      path: `/api/v1/sessions/${encodeURIComponent(sessionId)}/artifacts/${encodeURIComponent(artifactId)}`,
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: { base_hash: baseHash, content, note },
    });
  } catch (error) {
    throw new Error(
      `updateArtifactContent failed: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
}
