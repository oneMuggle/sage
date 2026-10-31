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
