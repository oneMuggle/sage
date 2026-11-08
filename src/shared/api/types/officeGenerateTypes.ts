import type { OfficeDocType, OfficeDocumentSummary } from '../types';

/** Request of POST /api/v1/office/generate/nl. */
export interface OfficeNlGenerateRequest {
  task_id?: string;
  workspace_path: string;
  instruction: string;
  doc_type: OfficeDocType;
  reference_paths?: string[];
}

export interface OfficeTemplateChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

/** Request of POST /api/v1/office/generate/template-chat. Exactly one template source. */
export interface OfficeTemplateChatRequest {
  task_id?: string;
  workspace_path: string;
  template_id?: string;
  workspace_template?: string;
  messages: OfficeTemplateChatMessage[];
}

/** Request of POST /api/v1/office/generate/iterate. `.docx` sources only. */
export interface OfficeIterateRequest {
  task_id?: string;
  workspace_path: string;
  source_path: string;
  instruction: string;
}

/** Shared response of all three generate endpoints. */
export interface OfficeGenerateResult {
  output_path: string;
  filename: string;
  file_size_bytes: number;
  summary: OfficeDocumentSummary;
}
