/**
 * Word 模板 Profile / 填充的 wire 类型（§118）。
 *
 * 对应后端：
 * - `POST /api/v1/office/word/template/profile`
 * - `POST /api/v1/office/word/template/profile/fill`
 *
 * 请求体由 pydantic `extra="forbid"` 校验，字段名保持 snake_case 原样。
 */

/** 槽位类别：内容控件 / 书签 / 占位符（{{x}} 或 Jinja 变量）/ 嵌入图片。 */
export type OfficeWordTemplateSlotKind =
  | 'content_control'
  | 'bookmark'
  | 'placeholder'
  | 'jinja'
  | string;

export interface OfficeWordTemplateSlot {
  name: string;
  kind: OfficeWordTemplateSlotKind;
  type: 'text' | 'image';
  required: boolean;
  description: string | null;
  current_value: string | null;
  confidence: number;
  anchor: string | null;
}

export interface OfficeWordTemplateWarning {
  code: string;
  message: string;
}

export interface OfficeWordTemplateProfileSummary {
  slots: number;
  kinds: Record<string, number>;
  has_jinja_control: boolean;
}

export interface OfficeWordTemplateProfileRequest {
  workspace_path: string;
  file_path: string;
}

export interface OfficeWordTemplateProfileResult {
  ok: boolean;
  kind: 'word-template-profile';
  source_path: string;
  slots: OfficeWordTemplateSlot[];
  warnings: OfficeWordTemplateWarning[];
  summary: OfficeWordTemplateProfileSummary;
}

export interface OfficeWordTemplateFillRequest {
  workspace_path: string;
  template_path: string;
  output_filename: string;
  data: Record<string, string>;
  /** image 槽位 → 工作区相对路径 / 绝对路径 / data URL。 */
  images?: Record<string, string>;
}

export interface OfficeWordTemplateFillResult {
  ok: boolean;
  template_path: string;
  /** 相对 workspace 的输出路径（posix 分隔）。 */
  output_path: string;
  filename: string;
  filled_count: number;
  unfilled_slots: string[];
  residual_placeholders: string[];
  jinja_rendered: boolean;
  images_rendered: number;
  warnings: OfficeWordTemplateWarning[];
}
