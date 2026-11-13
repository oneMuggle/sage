/**
 * Design Studio 类型定义
 */

// ---------------------------------------------------------------------------
// 设计系统
// ---------------------------------------------------------------------------

export interface DesignSystem {
  id: string;
  name: string;
  description: string;
  category: string;
  /** CSS tokens 文件名（如 tokens.css） */
  tokens_css: string;
  /** 设计说明 markdown 文件名（如 DESIGN.md） */
  design_md: string;
  /** 来源（如 open-design Apache 2.0） */
  source?: string;
}

// ---------------------------------------------------------------------------
// 模板
// ---------------------------------------------------------------------------

export type TemplateKind = 'deck' | 'prototype';

export interface DesignTemplate {
  id: string;
  name: string;
  description: string;
  kind: TemplateKind;
  /** SKILL.md 内容（供 LLM prompt 使用） */
  skill_md: string;
  /** example.html 文件路径 */
  example_html?: string;
  /** assets/ 目录下的资源 */
  assets?: string[];
}

// ---------------------------------------------------------------------------
// 项目
// ---------------------------------------------------------------------------

export type ProjectKind = 'deck' | 'prototype';

export type ProjectStatus = 'draft' | 'generating' | 'complete' | 'error';

export interface DesignProject {
  id: string;
  name: string;
  kind: ProjectKind;
  system_id: string;
  template_id: string;
  brief: string;
  status: ProjectStatus;
  created_at: string; // ISO 8601
  updated_at: string; // ISO 8601
}

// ---------------------------------------------------------------------------
// 产物（Artifact）
// ---------------------------------------------------------------------------

export interface DesignArtifact {
  id: string;
  project_id: string;
  version: number;
  html_content: string;
  title?: string;
  file_path?: string;
  kind: string;
  export_formats: string[];
  source_prompt?: string;
  created_at: string; // ISO 8601
}

/** GET /design/projects/{id} 返回项目 + 最新产物 */
export interface DesignProjectDetail extends DesignProject {
  latest_artifact: DesignArtifact | null;
}

// ---------------------------------------------------------------------------
// 生成 & 迭代请求
// ---------------------------------------------------------------------------

export interface GenerateRequest {
  /** 可选：覆盖项目 brief */
  brief?: string;
}

export interface IterateRequest {
  /** 用户反馈文本 */
  feedback: string;
}

// ---------------------------------------------------------------------------
// 导出
// ---------------------------------------------------------------------------

export type ExportFormat = 'html' | 'pdf' | 'pptx' | 'zip';

export interface ExportRequest {
  format: ExportFormat;
}

export interface ExportResult {
  ok: boolean;
  format: string;
  file_path?: string;
  html_content?: string;
  download_url?: string;
  error?: string;
}
