// Wiki API layer - wrappers around Tauri invoke()
import { invoke } from '../../lib/desktopInvoke';
import type {
  WikiProject,
  FileNode,
  SearchResponse,
  IngestResult,
  WikiChatResponse,
  GraphData,
} from '../types/wiki';

// ==================== Project API ====================

export async function createWikiProject(name: string, basePath: string): Promise<WikiProject> {
  return invoke<WikiProject>('create_wiki_project', { name, basePath });
}

export async function openWikiProject(path: string): Promise<WikiProject> {
  return invoke<WikiProject>('open_wiki_project', { path });
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
