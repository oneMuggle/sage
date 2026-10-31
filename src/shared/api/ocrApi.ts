/**
 * 本地 OCR API（后端 backend/api/ocr_routes.py → /api/v1/ocr/*）
 *
 * 聊天输入框用它判断「没有视觉模型时是否仍可上传图片」；设置页后续可用
 * 同一能力端点展示引擎/模型状态。
 */

import { backendRequest } from './backendRequest';

export interface OcrEngineStatus {
  name: string;
  available: boolean;
  reason: string;
}

export interface OcrCapabilities {
  enabled: boolean;
  engine: string;
  selected_engine: string | null;
  available: boolean;
  reason: string;
  lang: string;
  prefer_local_for_images: boolean;
  engines: OcrEngineStatus[];
  languages?: string[] | null;
}

export interface OcrLine {
  text: string;
  confidence: number;
  bbox: number[] | null;
}

export interface OcrImageResult {
  text: string;
  lines: OcrLine[];
  engine: string;
  lang: string;
  duration_ms: number;
  image_sha256: string;
  cached: boolean;
  quality: 'ok' | 'low_confidence' | 'empty' | 'failed';
  error: string | null;
}

export interface OcrBatchSubmitResult {
  job_id: string;
  total: number;
}

export interface OcrBatchCaseResult extends OcrImageResult {
  index: number;
}

export interface OcrBatchStatus {
  job_id: string;
  status: 'pending' | 'running' | 'completed' | 'cancelled' | 'failed';
  total: number;
  completed: number;
  failed: number;
  error: string | null;
  results: Array<OcrBatchCaseResult | null>;
}

export const ocrApi = {
  capabilities(): Promise<OcrCapabilities> {
    return backendRequest<OcrCapabilities>({
      method: 'GET',
      path: '/api/v1/ocr/capabilities',
    });
  },

  recognize(image: string, lang?: string): Promise<OcrImageResult> {
    return backendRequest<OcrImageResult>({
      method: 'POST',
      path: '/api/v1/ocr/image',
      body: { image, ...(lang ? { lang } : {}) },
    });
  },

  reload(): Promise<OcrCapabilities> {
    return backendRequest<OcrCapabilities>({
      method: 'POST',
      path: '/api/v1/ocr/reload',
    });
  },

  batch(images: string[], lang?: string): Promise<OcrBatchSubmitResult> {
    return backendRequest<OcrBatchSubmitResult>({
      method: 'POST',
      path: '/api/v1/ocr/batch',
      body: { images, ...(lang ? { lang } : {}) },
    });
  },

  batchStatus(jobId: string): Promise<OcrBatchStatus> {
    return backendRequest<OcrBatchStatus>({
      method: 'GET',
      path: `/api/v1/ocr/batch/${encodeURIComponent(jobId)}`,
    });
  },

  batchCancel(jobId: string): Promise<{ ok: boolean }> {
    return backendRequest<{ ok: boolean }>({
      method: 'POST',
      path: `/api/v1/ocr/batch/${encodeURIComponent(jobId)}/cancel`,
    });
  },
};
