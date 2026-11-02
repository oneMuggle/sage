/** Shared types for the LaTeX preview payload (backend `kind: "latex"`). */

export interface LatexAnchor {
  file: string;
  line: number;
  column?: number;
}

export interface LatexWarning {
  code: string;
  message: string;
  anchor?: LatexAnchor;
  detail?: Record<string, unknown>;
}

export interface LatexMetadata {
  document_class?: string | null;
  document_options?: string[];
  title?: string | null;
  authors?: string[];
  affiliations?: string[];
  emails?: string[];
  date?: string | null;
  abstract?: string | null;
  keywords?: string[];
  extra?: Record<string, string>;
}

export interface LatexListItem {
  text: string;
}

export interface LatexBlock {
  type: string;
  level?: number;
  text?: string;
  ordered?: boolean;
  items?: LatexListItem[];
  latex?: string;
  display?: boolean;
  src?: string;
  caption?: string;
  label?: string;
  headers?: string[];
  rows?: string[][];
  entries?: Array<{ key: string; text: string }>;
  anchor?: LatexAnchor;
}

export interface LatexStructured {
  source_path: string;
  metadata: LatexMetadata;
  blocks: LatexBlock[];
  warnings: LatexWarning[];
  includes?: string[];
  citations?: string[];
}
