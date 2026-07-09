// Wiki TypeScript types

export interface WikiProject {
  id: string;
  name: string;
  path: string;
}

export interface FileNode {
  name: string;
  path: string;
  is_dir: boolean;
  children?: FileNode[];
}

export interface WikiPage {
  path: string;
  content: string;
  title: string;
}

export interface SearchResult {
  path: string;
  title: string;
  snippet: string;
  score: number;
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
}

export interface IngestResult {
  source_path: string;
  wiki_page_path: string;
  page_type: string;
}

export interface WikiChatResponse {
  answer: string;
  citations: string[];
}

export type WikiView =
  | 'browser'
  | 'search'
  | 'chat'
  | 'graph'
  | 'lint'
  | 'review'
  | 'sources'
  | 'insights';

// Lint 检查项
export interface LintItem {
  id: string;
  type: 'orphan' | 'broken-link' | 'no-outlinks' | 'semantic';
  severity: 'warning' | 'info';
  page: string;
  message: string;
  suggestion?: string;
}

// Review 审核项
export interface ReviewItem {
  id: string;
  type: 'contradiction' | 'duplicate' | 'missing-page' | 'confirm' | 'suggestion';
  title: string;
  description: string;
  affectedPages: string[];
  resolved: boolean;
  actions: ReviewAction[];
}

export interface ReviewAction {
  id: string;
  label: string;
  type: 'research' | 'open' | 'create' | 'dismiss' | 'delete';
}

// Activity 活动项
export interface ActivityItem {
  id: string;
  type: 'ingest' | 'lint' | 'query';
  status: 'running' | 'done' | 'error';
  startedAt: number;
  completedAt?: number;
  filesWritten?: string[];
  error?: string;
}

// Research 研究任务
export interface ResearchTask {
  id: string;
  topic: string;
  status: 'queued' | 'searching' | 'synthesizing' | 'done' | 'error';
  webResults: WebResult[];
  synthesis: string;
  savedPath?: string;
}

export interface WebResult {
  title: string;
  url: string;
  snippet: string;
}

export type GraphSignal = 'DirectLink' | 'SourceOverlap' | 'TypeAffinity';

export interface GraphNode {
  id: string;
  label: string;
  page_type?: string;
  sources: string[];
  wikilinks: string[];
}

export interface GraphEdge {
  source: string;
  target: string;
  signal: GraphSignal;
  weight: number;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// --- Added 2026-06-27: folder picker support ---

export interface ProjectCheckResponse {
  exists: boolean;
  writable: boolean;
  is_project: boolean;
  parent_writable: boolean;
  warning: string | null;
  error: string | null;
}

export interface RecentProject {
  path: string;
  name: string;
  opened_at: number;
  intent: 'create' | 'open';
}

export interface RecordRecentRequest {
  path: string;
  name: string;
  intent: 'create' | 'open';
}

export interface SelectDirectoryOpts {
  intent: 'create' | 'open';
  defaultPath?: string;
}
