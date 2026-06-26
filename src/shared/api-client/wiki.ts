// Wiki API layer - HTTP API calls to backend
import type {
  WikiProject,
  FileNode,
  SearchResponse,
  IngestResult,
  WikiChatResponse,
  GraphData,
} from '../types/wiki';

// Backend API base URL
const API_BASE = 'http://127.0.0.1:8765/api/v1';

// Helper function for HTTP requests
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

async function httpDelete<T>(endpoint: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`HTTP ${response.status}: ${error}`);
  }

  return response.json();
}

// ==================== Project API ====================

export async function createWikiProject(name: string, basePath: string): Promise<WikiProject> {
  // Note: Project creation is not yet implemented in backend
  // For now, return a mock project
  return { id: basePath, name, path: basePath };
}

export async function openWikiProject(path: string): Promise<WikiProject> {
  // Note: Project opening is not yet implemented in backend
  // For now, return a mock project
  return { id: path, name: 'Wiki Project', path };
}

// ==================== File API ====================

export async function wikiListDirectory(path: string, projectPath: string): Promise<FileNode[]> {
  return httpGet<FileNode[]>('/wiki/list', { path, project_path: projectPath });
}

export async function wikiReadFile(path: string, projectPath: string): Promise<string> {
  return httpGet<string>('/wiki/read', { path, project_path: projectPath });
}

export async function wikiWriteFile(
  path: string,
  content: string,
  projectPath: string,
): Promise<void> {
  await httpPost('/wiki/write', { path, content, project_path: projectPath });
}

export async function wikiDeleteFile(path: string, projectPath: string): Promise<void> {
  await httpDelete('/wiki/delete', { path, project_path: projectPath });
}

export interface CascadeDeleteResult {
  success: boolean;
  source_deleted: string;
  deleted_wiki_pages: string[];
  deleted_vectors: number;
  cleaned_deadlinks: number;
}

export async function wikiDeleteSource(
  sourcePath: string,
  projectPath: string,
): Promise<CascadeDeleteResult> {
  return httpDelete<CascadeDeleteResult>(`/wiki/source/${sourcePath}`, {
    project_path: projectPath,
  });
}

export async function wikiRenameFile(
  oldPath: string,
  newPath: string,
  projectPath: string,
): Promise<void> {
  await httpPost('/wiki/rename', {
    old_path: oldPath,
    new_path: newPath,
    project_path: projectPath,
  });
}

// ==================== Search API ====================

export async function wikiSearch(
  query: string,
  projectPath: string,
  limit?: number,
): Promise<SearchResponse> {
  return httpGet<SearchResponse>('/wiki/search', {
    query,
    project_path: projectPath,
    limit: limit ?? 20,
  });
}

// ==================== Ingest API ====================

export async function wikiIngestSource(
  sourceFilePath: string,
  projectPath: string,
  apiUrl: string,
  apiKey: string,
  model: string,
  embedApiUrl: string,
  embedApiKey: string,
  embedModel: string,
): Promise<IngestResult> {
  return httpPost<IngestResult>('/wiki/ingest', {
    source_file: sourceFilePath,
    project_path: projectPath,
    llm_base_url: apiUrl,
    llm_api_key: apiKey,
    llm_model: model,
    embed_base_url: embedApiUrl,
    embed_api_key: embedApiKey,
    embed_model: embedModel,
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
  return httpPost<WikiChatResponse>('/wiki/chat', {
    query,
    project_path: projectPath,
    llm_base_url: apiUrl,
    llm_api_key: apiKey,
    llm_model: model,
    embed_base_url: embedApiUrl,
    embed_api_key: embedApiKey,
    embed_model: embedModel,
  });
}

// ==================== Graph API ====================

export async function getWikiGraph(
  projectPath: string,
  query?: string,
  limit: number = 100,
): Promise<GraphData> {
  return httpGet<GraphData>('/wiki/graph', {
    project_path: projectPath,
    query: query ?? undefined,
    limit,
  });
}

// ==================== Community API ====================

export interface CommunityInfo {
  community_id: number;
  members: string[];
  cohesion: number;
  size: number;
}

export interface CommunitiesResponse {
  communities: CommunityInfo[];
  graph: GraphData;
}

export async function getWikiCommunities(projectPath: string): Promise<CommunitiesResponse> {
  return httpGet<CommunitiesResponse>('/wiki/communities', {
    project_path: projectPath,
  });
}

// ==================== Research API ====================

export interface ResearchRequest {
  topic: string;
  project_path: string;
  search_provider?: string;
  search_api_key?: string;
  search_base_url?: string;
  llm_base_url: string;
  llm_api_key: string;
  llm_model: string;
  auto_ingest?: boolean;
}

export interface WebResultData {
  title: string;
  url: string;
  snippet: string;
  score: number;
}

export interface ResearchResponse {
  id: string;
  topic: string;
  status: string;
  queries: string[];
  web_results_count: number;
  web_results: WebResultData[];
  synthesis: string;
  saved_path: string;
  error: string;
}

export async function startWikiResearch(req: ResearchRequest): Promise<ResearchResponse> {
  return httpPost<ResearchResponse>('/wiki/research', req);
}

// ==================== Insights API ====================

export interface SurprisingConnection {
  source_id: string;
  source_label: string;
  target_id: string;
  target_label: string;
  reason: string;
  strength: number;
}

export interface KnowledgeGap {
  gap_type: string;
  node_id: string;
  node_label: string;
  description: string;
  severity: string;
  suggestion: string;
}

export interface InsightsResponse {
  surprising_connections: SurprisingConnection[];
  knowledge_gaps: KnowledgeGap[];
  stats: {
    total_nodes: number;
    total_edges: number;
    total_communities: number;
    surprising_connections: number;
    knowledge_gaps: number;
  };
}

export async function getWikiInsights(projectPath: string): Promise<InsightsResponse> {
  return httpGet<InsightsResponse>('/wiki/insights', {
    project_path: projectPath,
  });
}
