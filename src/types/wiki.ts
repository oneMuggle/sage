// Wiki TypeScript types

export interface WikiProject {
  id: string
  name: string
  path: string
}

export interface FileNode {
  name: string
  path: string
  is_dir: boolean
  children?: FileNode[]
}

export interface WikiPage {
  path: string
  content: string
  title: string
}

export interface SearchResult {
  path: string
  title: string
  snippet: string
  score: number
}

export interface SearchResponse {
  results: SearchResult[]
  total: number
}

export interface IngestResult {
  source_path: string
  wiki_page_path: string
  page_type: string
}

export interface WikiChatResponse {
  answer: string
  citations: string[]
}

export type WikiView = 'browser' | 'search' | 'chat'
