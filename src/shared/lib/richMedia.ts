/**
 * P1 富媒体引用契约 —— 与后端 `backend/domain/media.py::RichMedia.to_dict()`
 * 字段一一对应。工具（MCP / 内置生成）产出的图片、图表、音频、文档一律以
 * URL 引用下发，绝不含 base64 实体；渲染时按 `api_url` 拉取。
 */
export interface RichMediaRef {
  id: string;
  /** "image" | "diagram" | "audio" | "document" */
  kind: string;
  mime_type: string;
  api_url: string;
  format?: string | null;
  title?: string | null;
  /** "mcp:drawio" | "image_gen" | ... */
  source?: string | null;
  /** 提示前端可提供缩放/全屏等交互（SVG 图表典型场景）。 */
  interactive?: boolean;
}

/** SVG 图表是否应当走可交互查看器。 */
export function isInteractiveDiagram(media: RichMediaRef): boolean {
  return Boolean(media.interactive) && media.mime_type === 'image/svg+xml';
}
