// src/features/artifacts/artifactApi.ts

import { backendRequest } from '../../shared/api/backendRequest';
import { isDemoMode } from '../../shared/api/demoInterceptors';

export type ArtifactKind = 'markdown' | 'code' | 'image' | 'csv' | 'json' | 'text';

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
