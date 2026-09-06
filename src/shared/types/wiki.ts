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

export type WikiView =
  | 'browser'
  | 'search'
  | 'chat'
  | 'graph'
  | 'lint'
  | 'review'
  | 'sources'
  | 'insights'
  | 'queue';

// Lint 检查项
export interface LintItem {
  id: string;
  type:
    | 'orphan'
    | 'broken-link'
    | 'no-outlinks'
    | 'semantic'
    // Backend-backed lint types (backend/wiki/lint.py → LintType)
    | 'required_dir'
    | 'required_file'
    | 'frontmatter_missing'
    | 'frontmatter_title'
    | 'wikilink_broken';
  severity: 'error' | 'warning' | 'info';
  page: string;
  message: string;
  suggestion?: string;
  // Backend-backed fields (optional — populated when sourced from API)
  detail?: string;
  broken_target?: string;
  suggested_target?: string;
  suggested_source?: string;
  affected_pages?: string[];
}

// Lint 检查整体响应 (对齐 backend LintResult.to_dict())
export interface LintResponse {
  total: number;
  by_severity: { error: number; warning: number; info: number };
  issues: LintIssueRaw[];
}

// 后端 Lint 原始问题形状 (snake_case,从 API 返回;
// 前端 lint-store 会把它映射为 LintItem)
export interface LintIssueRaw {
  type:
    | 'required_dir'
    | 'required_file'
    | 'frontmatter_missing'
    | 'frontmatter_title'
    | 'wikilink_broken'
    | 'orphan';
  severity: 'error' | 'warning' | 'info';
  page: string;
  detail: string;
  broken_target?: string | null;
  suggested_target?: string | null;
  suggested_source?: string | null;
  affected_pages?: string[] | null;
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
  // Backend-backed fields (optional — populated when sourced from API)
  confidence?: number;
  detail?: string;
  suggestion?: string;
}

export interface ReviewAction {
  id: string;
  label: string;
  type: 'research' | 'open' | 'create' | 'dismiss' | 'delete';
}

// Review 检查整体响应 (对齐 backend ReviewResult.to_dict())
export interface ReviewResponse {
  total: number;
  by_type: {
    duplicate: number;
    contradiction: number;
    'missing-page': number;
    confirm: number;
    suggestion: number;
  };
  items: ReviewItemRaw[];
}

// 后端 Review 原始问题形状 (snake_case,从 API 返回;
// 前端 review-store 会把它映射为 ReviewItem)
export interface ReviewItemRaw {
  id: string;
  type: 'contradiction' | 'duplicate' | 'missing-page' | 'confirm' | 'suggestion';
  title: string;
  description: string;
  affected_pages: string[];
  confidence: number;
  detail?: string;
  suggestion?: string;
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
