// src/features/artifacts/artifactApi.ts

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

function httpError(fn: string, res: Response): Error {
  return new Error(`${fn} failed: ${res.status}${res.statusText ? ` ${res.statusText}` : ''}`);
}

export async function listArtifacts(sessionId: string): Promise<Artifact[]> {
  const res = await fetch(`/api/v1/sessions/${sessionId}/artifacts`);
  if (!res.ok) {
    throw httpError('listArtifacts', res);
  }
  const data = await res.json();
  return data.artifacts ?? [];
}

export async function readArtifactContent(
  sessionId: string,
  artifactId: string
): Promise<ArtifactContent> {
  const res = await fetch(`/api/v1/sessions/${sessionId}/artifacts/${artifactId}/content`);
  if (!res.ok) {
    throw httpError('readArtifactContent', res);
  }
  return res.json();
}

export async function revealArtifact(
  sessionId: string,
  artifactId: string
): Promise<{ ok: boolean; error?: string }> {
  const res = await fetch(`/api/v1/sessions/${sessionId}/artifacts/${artifactId}/reveal`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!res.ok) {
    throw httpError('revealArtifact', res);
  }
  return res.json();
}
