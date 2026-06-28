// Wiki API layer - wrappers around Tauri invoke() + HTTP helpers for project API
import { invoke } from '../../shared/api/desktopInvoke';
import type {
  WikiProject,
  FileNode,
  SearchResponse,
  IngestResult,
  WikiChatResponse,
  GraphData,
} from '../types/wiki';

// Backend API base URL (for project-level HTTP calls)
const API_BASE = 'http://127.0.0.1:8765/api/v1';

// Helper function for HTTP POST requests
async function httpPost<T>(endpoint: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`HTTP ${response.status}: ${error}`);
  }

  return response.json();
}

// Helper function for HTTP GET requests
async function httpGet<T>(
  endpoint: string,
  params?: Record<string, string | number | undefined>,
): Promise<T> {
  const url = new URL(`${API_BASE}${endpoint}`);
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined) {
        url.searchParams.append(key, String(value));
      }
    });
  }

  const response = await fetch(url.toString());

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`HTTP ${response.status}: ${error}`);
  }

  return response.json();
}

// ==================== Project API ====================

export interface ProjectInfo {
  id: string;
  name: string;
  path: string;
  created_at: string;
  has_content: boolean;
}

export async function createWikiProject(name: string, basePath: string): Promise<WikiProject> {
  const result = await httpPost<ProjectInfo>('/wiki/project/create', {
    name,
    base_path: basePath,
  });
  return {
    id: result.id,
    name: result.name,
    path: result.path,
  };
}

export async function openWikiProject(path: string): Promise<WikiProject> {
  const result = await httpPost<ProjectInfo>('/wiki/project/open', { path });
  return {
    id: result.id,
    name: result.name,
    path: result.path,
  };
}

export async function listWikiProjects(basePath: string): Promise<ProjectInfo[]> {
  return httpGet<ProjectInfo[]>('/wiki/project/list', { base_path: basePath });
}

// ==================== File API ====================

export async function wikiListDirectory(path: string, projectPath: string): Promise<FileNode[]> {
  return invoke<FileNode[]>('wiki_list_directory', { path, projectPath });
}

export async function wikiReadFile(path: string, projectPath: string): Promise<string> {
  return invoke<string>('wiki_read_file', { path, projectPath });
}

export async function wikiWriteFile(
  path: string,
  content: string,
  projectPath: string,
): Promise<void> {
  return invoke<void>('wiki_write_file', { path, content, projectPath });
}

export async function wikiDeleteFile(path: string, projectPath: string): Promise<void> {
  return invoke<void>('wiki_delete_file', { path, projectPath });
}

export async function wikiRenameFile(
  oldPath: string,
  newPath: string,
  projectPath: string,
): Promise<void> {
  return invoke<void>('wiki_rename_file', { oldPath, newPath, projectPath });
}

// ==================== Search API ====================

export async function wikiSearch(
  query: string,
  projectPath: string,
  limit?: number,
): Promise<SearchResponse> {
  return invoke<SearchResponse>('wiki_search', { query, projectPath, limit: limit ?? 20 });
}

// ==================== Ingest API ====================

export async function wikiIngestSource(
  ingestId: string,
  sourceFilePath: string,
  projectPath: string,
  apiUrl: string,
  apiKey: string,
  model: string,
  embedApiUrl: string,
  embedApiKey: string,
  embedModel: string,
): Promise<IngestResult> {
  return invoke<IngestResult>('wiki_ingest_source', {
    ingestId,
    sourceFilePath,
    projectPath,
    apiUrl,
    apiKey,
    model,
    embedApiUrl,
    embedApiKey,
    embedModel,
  });
}

// ==================== Chat API ====================

export async function wikiChat(
  query: string,
  projectPath: string,
  apiUrl: string,
  apiKey: string,
  model: string,
  embedApiUrl: string,
  embedApiKey: string,
  embedModel: string,
): Promise<WikiChatResponse> {
  return invoke<WikiChatResponse>('wiki_chat', {
    query,
    projectPath,
    apiUrl,
    apiKey,
    model,
    embedApiUrl,
    embedApiKey,
    embedModel,
  });
}

// ==================== Graph API ====================

export async function getWikiGraph(
  projectPath: string,
  query?: string,
  limit: number = 100,
): Promise<GraphData> {
  return invoke<GraphData>('wiki_get_graph', {
    projectPath,
    query: query ?? null,
    limit,
  });
}
