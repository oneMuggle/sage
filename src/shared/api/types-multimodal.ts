/**
 * Multimodal types — mirrors backend MediaRef and related structures.
 * Used by TTS, ASR, image generation, and chat attachment upload.
 */

/** Media kind (mirrors backend MediaKind enum) */
export type MediaKind = 'image' | 'audio';

/** MediaRef — mirrors backend dataclass (dataclasses.asdict output) */
export interface MediaRef {
  id: string;
  kind: MediaKind;
  mime_type: string;
  file_path: string;
  file_size: number;
  created_at: string;
  source: string; // "tts" | "asr" | "image_gen" | "chat_upload"
  metadata: Record<string, unknown>;
}

/** Response from POST /api/v1/chat/attachments */
export interface AttachmentUploadResponse {
  media_ref: MediaRef;
  api_url: string;
}

/** Tool output shape for text_to_speech */
export interface TTSToolOutput {
  media_ref: MediaRef;
  api_url: string;
}

/** Tool output shape for generate_image */
export interface ImageGenToolOutput {
  media_refs: MediaRef[];
  api_urls: string[];
}

/** MediaReference for Message.tool_calls[].metadata */
export interface MediaRefMetadata {
  mediaRefs?: MediaRef[];
  apiUrls?: string[];
  /** Legacy: base64 inline image (diagram tools) */
  imageData?: string;
  imageFormat?: string;
}
