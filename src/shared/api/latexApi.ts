import { backendRequest } from './backendRequest';

export interface LatexTemplateSlot {
  name: string;
  kind: 'command_arg' | 'environment_body' | 'placeholder' | 'comment' | string;
  type: 'text' | 'rich_text' | 'date' | 'list' | string;
  required: boolean;
  description: string;
  current_value: string;
  confidence: number;
  command?: string;
  environment?: string;
  placeholder?: string;
  anchor?: { file: string; line: number; column?: number };
}

export interface LatexTemplateProfile {
  ok: boolean;
  kind: 'latex-template';
  source_path: string;
  document_class?: string | null;
  document_options: string[];
  packages: string[];
  macros: Record<string, Record<string, unknown>>;
  style: Record<string, unknown>;
  metadata: Record<string, unknown>;
  slots: LatexTemplateSlot[];
  warnings: Array<{ code: string; message: string }>;
  includes: string[];
}

export interface LatexFillResult {
  ok: boolean;
  template_path: string;
  output_path: string;
  filename: string;
  filled_count: number;
  unfilled_slots: string[];
  validation: {
    ok: boolean;
    issues: Array<{
      code: string;
      severity: 'error' | 'warning';
      message: string;
      line: number;
      column: number;
    }>;
  };
  warnings: Array<{ code: string; message: string }>;
}

export interface LatexAuditIssue {
  rule_id: string;
  severity: 'error' | 'warning' | 'info';
  category: string;
  message: string;
  fix_hint: string;
  anchor?: { file: string; line?: number; column?: number; page?: number };
  evidence?: Record<string, unknown>;
}

export interface LatexAuditResult {
  ok: boolean;
  source_path: string;
  issues: LatexAuditIssue[];
  summary: {
    count: number;
    severity: { error: number; warning: number; info: number };
    categories: Record<string, number>;
  };
  required_sections: string[];
}

export interface LatexCapabilities {
  engines: Array<{ name: string; path: string }>;
  latexdiff: string | null;
}

export interface LatexCompileResult {
  ok: boolean;
  code?: string;
  message?: string;
  engine?: string;
  pdf_path?: string;
  returncode?: number;
  log_tail?: string;
  duration_ms?: number;
  available?: Array<{ name: string; path: string }>;
  issues?: LatexAuditIssue[];
}

export interface LatexDiffResult {
  ok: boolean;
  code?: string;
  message?: string;
  diff_path?: string;
  pdf_path?: string;
  compile?: LatexCompileResult;
  latexdiff_available?: boolean;
  log_tail?: string;
}

export interface LatexProjectExtractResult {
  ok: boolean;
  project_dir: string;
  main_file: string | null;
  main_candidates: string[];
  files_count: number;
  bytes_written: number;
  warnings: Array<{ code: string; message: string; path?: string }>;
}

export interface LatexPdfAuditResult {
  ok: boolean;
  source_path: string;
  summary: {
    pages: number;
    page_size: { width: number; height: number; label: string };
    page_sizes: Array<{ width: number; height: number; pages: number[] }>;
    fonts: Array<{
      basefont: string;
      type: string;
      ext: string;
      embedded: boolean;
      pages: number[];
    }>;
    images_count: number;
    min_image_dpi: number | null;
  };
  issues: LatexAuditIssue[];
}

export async function analyzeLatexTemplate(
  workspacePath: string,
  filePath: string,
): Promise<LatexTemplateProfile> {
  return backendRequest<LatexTemplateProfile>({
    method: 'POST',
    path: '/api/v1/office/latex/template/analyze',
    body: { workspace_path: workspacePath, file_path: filePath },
  });
}

export async function fillLatexTemplate(
  workspacePath: string,
  templatePath: string,
  outputFilename: string,
  data: Record<string, string | string[]>,
): Promise<LatexFillResult> {
  return backendRequest<LatexFillResult>({
    method: 'POST',
    path: '/api/v1/office/latex/template/fill',
    body: {
      workspace_path: workspacePath,
      template_path: templatePath,
      output_filename: outputFilename,
      data,
    },
  });
}

export async function auditLatex(
  workspacePath: string,
  filePath: string,
  requiredSections: string[] = [],
): Promise<LatexAuditResult> {
  return backendRequest<LatexAuditResult>({
    method: 'POST',
    path: '/api/v1/office/latex/audit',
    body: {
      workspace_path: workspacePath,
      file_path: filePath,
      required_sections: requiredSections,
    },
  });
}

export async function getLatexCapabilities(): Promise<LatexCapabilities> {
  return backendRequest<LatexCapabilities>({
    path: '/api/v1/office/latex/capabilities',
  });
}

export async function compileLatex(
  workspacePath: string,
  filePath: string,
  outputFilename?: string,
  engine?: string,
  timeoutS = 60,
): Promise<LatexCompileResult> {
  return backendRequest<LatexCompileResult>({
    method: 'POST',
    path: '/api/v1/office/latex/compile',
    body: {
      workspace_path: workspacePath,
      file_path: filePath,
      output_filename: outputFilename || null,
      engine: engine || null,
      timeout_s: timeoutS,
    },
  });
}

export async function latexdiff(
  workspacePath: string,
  originalPath: string,
  revisedPath: string,
  outputFilename = '',
  compilePdf = false,
  engine?: string,
): Promise<LatexDiffResult> {
  return backendRequest<LatexDiffResult>({
    method: 'POST',
    path: '/api/v1/office/latex/diff',
    body: {
      workspace_path: workspacePath,
      original_path: originalPath,
      revised_path: revisedPath,
      output_filename: outputFilename,
      compile_pdf: compilePdf,
      engine: engine || null,
      timeout_s: 60,
    },
  });
}

export async function extractLatexProject(
  workspacePath: string,
  zipPath: string,
  outputDirName?: string,
): Promise<LatexProjectExtractResult> {
  return backendRequest<LatexProjectExtractResult>({
    method: 'POST',
    path: '/api/v1/office/latex/project/extract',
    body: {
      workspace_path: workspacePath,
      zip_path: zipPath,
      output_dir_name: outputDirName || null,
    },
  });
}

export async function auditLatexPdf(
  workspacePath: string,
  filePath: string,
  requiredMinPages?: number,
  requiredMaxPages?: number,
  minImageDpi = 150,
): Promise<LatexPdfAuditResult> {
  return backendRequest<LatexPdfAuditResult>({
    method: 'POST',
    path: '/api/v1/office/latex/pdf/audit',
    body: {
      workspace_path: workspacePath,
      file_path: filePath,
      required_min_pages: requiredMinPages || null,
      required_max_pages: requiredMaxPages || null,
      min_image_dpi: minImageDpi,
    },
  });
}
