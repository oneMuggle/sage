/**
 * 共享的模型能力推断 —— 基于 model id 字符串子串匹配。
 *
 * 合并原 `providerRegistry.ts` 与 `manage-endpoints/api.ts` 两份不一致的实现：
 * - `providerRegistry.ts:116` 仅识别 `vision` / `4o` 两个 marker，导致 `claude-3-5-sonnet`
 *   `gpt-4.1` `gemini-2.5-pro` 等主流多模态模型被误判为不支持视觉；
 * - `api.ts:371` 覆盖较全但未被生产路径使用。
 *
 * 本模块是端点发现（`/v1/models`）阶段的**启发式**判定，非厂商权威声明。
 * 权威能力以 model-catalog `getEffective().capabilities` 为准；本推断仅作
 * catalog 缺失时的回退路径。消费方应通过 `visionCapability.ts` 的
 * `resolveVisionSupport` 做分层解析，而不是直接读 `inferCapabilities` 结果。
 *
 * 设计要点：
 * - 返回类型与 `ModelCapability` 一致，调用方无需改动；
 * - negative marker 先于 positive 判定，避免 `text-embedding-3-small` / `whisper-*`
 *   / `dall-e-*` / `tts-*` 被 vision 关键词误命中；
 * - embedding 模型短路回 `['embedding']`，防止端点发现阶段把 embedding 模型
 *   当成 chat 候选（与 `api.ts` 的 `isEmbeddingModel` 防御一致）。
 */

import type { ModelCapability } from '../../entities/setting/types';

/**
 * 已知「纯文本 / 非对话 / 非视觉」模型族。必须先于 vision 关键词判定，
 * 否则 `text-embedding-3-*` / `whisper-*` / `dall-e-*` / `tts-*` / `asr-*`
 * 等会被 vision 关键词误判。
 */
const NON_VISION_MARKERS: readonly string[] = [
  'embedding',
  'embed-',
  'moderation',
  'dall-e',
  'whisper',
  'tts-',
  'asr-',
  'rerank',
  'minilm',
  'imagen',
  'veo',
  'claude-2',
  'claude-instant', // Anthropic legacy（不支持 vision）
  'gpt-3.5', // GPT-3.5 系列不支持 image input
  'gpt-3',
  'gpt-3-',
  'text-davinci',
  'text-curie',
  'text-babbage',
  'text-ada',
];

/**
 * 已知支持 image input 的模型族 marker。覆盖 OpenAI / Anthropic / Gemini /
 * Qwen / GLM / InternVL / LLaVA / MiniCPM-V / Gemma / Phi-4 / Ollama 主流
 * 多模态变体。`gpt-4` 覆盖 gpt-4 / gpt-4-turbo / gpt-4o / gpt-4.1 / gpt-4-vision；
 * `o1`/`o3`/`o4`/`o5` 为多模态推理系列。
 */
const VISION_MARKERS: readonly string[] = [
  // OpenAI
  'gpt-4',
  'gpt-5',
  'o1',
  'o3',
  'o4',
  'o5',
  // Anthropic（claude-3+ 全家族支持 vision）
  'claude-3',
  'claude-4',
  'claude-5',
  'claude-sonnet',
  'claude-opus',
  'claude-haiku',
  // Gemini（生成式模型全部支持）
  'gemini',
  // 第三方 VL 家族（OpenAI 兼容端点）
  'vl', // qwen-vl / qwen2-vl / qwen2.5-vl / deepseek-vl / glm-4v
  '4v', // llava-1.6-4v 等
  'internvl',
  'llava',
  'minicpm-v',
  'gemma3',
  'phi4',
  // Ollama-specific
  'moondream',
  'bakllava',
  // Generic fallback
  'vision',
  'image',
];

/**
 * 纯模型 id 是否为纯 embedding 类模型（不做 chat 用途）。
 *
 * 与 `api.ts` 的 `isEmbeddingModel` 对齐；单独导出供调用方做 chat 候选过滤。
 */
export function isEmbeddingModelId(modelId: string): boolean {
  const lower = modelId.toLowerCase();
  return (
    lower.includes('embed') || lower.includes('text-embedding') || lower.includes('vector')
  );
}

/**
 * 从 model id 字符串启发式推断模型能力。
 *
 * @param modelId 上游 `/v1/models` 返回的模型 id，如 `"gpt-4o"` / `"claude-3-5-sonnet"` /
 *   `"qwen2.5-vl-72b"` / `"text-embedding-3-small"`。
 * @returns 能力数组。embedding 模型返回 `['embedding']`；其它模型至少含 `'chat'`，
 *   命中 vision marker 的附加 `'vision'`。
 */
export function inferCapabilities(modelId: string): ModelCapability[] {
  const lower = modelId.toLowerCase();
  const caps: ModelCapability[] = ['chat'];

  // embedding 短路 —— 不进入 vision 判定，避免 `bge-m3` 之类误命中 `gem` 子串
  if (isEmbeddingModelId(modelId)) {
    return ['embedding'];
  }

  const isNonVision = NON_VISION_MARKERS.some((m) => lower.includes(m));
  if (!isNonVision && VISION_MARKERS.some((m) => lower.includes(m))) {
    caps.push('vision');
  }

  if (/tts-|speech-|voice-/.test(lower)) {
    caps.push('tts');
  }
  if (/whisper|asr-|transcri/.test(lower)) {
    caps.push('asr');
  }
  if (/dall|image-gen|stable-diffusion|sdxl|flux/.test(lower)) {
    caps.push('image_gen');
  }

  return caps;
}
