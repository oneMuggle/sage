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

/** 创建项目的输入：只有 brief 必填，其余由后端默认值补齐 */
export interface CreateProjectInput {
  name?: string;
  kind: ProjectKind;
  system_id?: string;
  template_id?: string;
  brief: string;
}

/** GET /design/projects/{id}/artifacts 的列表项（不含 HTML 正文） */
export interface DesignArtifactSummary {
  id: string;
  project_id: string;
  version: number;
  title: string;
  kind: string;
  created_at: string;
}

/** 一次迭代对话消息（服务端持久化） */
export interface IterationMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  artifact_id?: string | null;
  artifact_version?: number | null;
  created_at: string;
}

/** 项目级微调参数（覆盖设计系统 CSS 变量，不重新生成） */
export interface ProjectTweaks {
  accent?: string | null;
  radius?: number | null;
  font_size?: number | null;
  density?: number | null;
  font_family?: string | null;
}

/** 生成阶段进度（idle / starting / composing / generating / linting / saving / complete / error） */
export interface GenerationProgress {
  stage: string;
  message: string;
  updated_at?: string;
}

// ---------------------------------------------------------------------------
// 资源（数据源 / 图表 / Word 大纲）
// ---------------------------------------------------------------------------

export interface DesignSourceBinding {
  kind: string;
  file_path: string;
  name: string;
}

export interface SourcePreviewSheet {
  name: string;
  row_count: number;
  columns: string[];
  sample: string[][];
}

export interface SourcePreview {
  ok: boolean;
  kind: string;
  sheets: SourcePreviewSheet[];
}

export interface OutlineResult {
  title: string;
  source_path: string;
  slide_count: number;
  outline_md: string;
}

export type ChartType = 'line' | 'bar' | 'hbar' | 'pie';

export interface ChartSeriesSpec {
  name: string;
  x?: (string | number)[];
  y: number[];
}

export interface ChartSpec {
  type: ChartType;
  title?: string | null;
  labels?: string[] | null;
  series: ChartSeriesSpec[];
}

export interface EmbedChartResult {
  ok: boolean;
  artifact_id: string;
  version: number;
  title: string;
  injected_at_slot: boolean;
}

// ---------------------------------------------------------------------------
// 质量评审（复用后端 DesignLinter）
// ---------------------------------------------------------------------------

export interface LintIssueSummary {
  rule_id: string;
  severity: 'error' | 'warning';
  message: string;
  line?: number | null;
}

export interface ReviewResult {
  ok: boolean;
  error_count: number;
  warning_count: number;
  issues: LintIssueSummary[];
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
  /** true 时后端以 base64 内联返回文件内容，便于前端直接下载 */
  inline?: boolean;
}

export interface ExportResult {
  ok: boolean;
  format: string;
  file_path?: string;
  html_content?: string;
  download_url?: string;
  filename?: string;
  content_base64?: string;
  error?: string;
}
