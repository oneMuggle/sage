import { describe, expect, it } from 'vitest';

import { inferCapabilities, isEmbeddingModelId } from '../modelCapabilities';

describe('inferCapabilities', () => {
  it.each([
    'gpt-4o',
    'gpt-4.1',
    'gpt-4-turbo',
    'gpt-5',
    'o3-mini',
    'claude-3-5-sonnet-20241022',
    'claude-sonnet-4-20250514',
    'claude-opus-4-1',
    'gemini-2.5-pro',
    'qwen2.5-vl-72b-instruct',
    'glm-4v',
    'internvl2-26b',
    'llava-1.6-34b',
    'minicpm-v-2.6',
    'gemma3-27b',
    'phi4-multimodal',
    'moondream2',
    'bakllava',
  ])('marks mainstream multimodal model %s as vision-capable', (modelId) => {
    expect(inferCapabilities(modelId)).toContain('vision');
  });

  it.each([
    'gpt-3.5-turbo',
    'gpt-3-ada',
    'text-davinci-003',
    'claude-2.1',
    'claude-instant-1.2',
    'text-moderation-latest',
  ])('does not mark legacy text model %s as vision-capable', (modelId) => {
    expect(inferCapabilities(modelId)).not.toContain('vision');
  });

  it('returns exactly [embedding] for embedding models (not a chat candidate)', () => {
    expect(inferCapabilities('text-embedding-3-small')).toEqual(['embedding']);
    expect(inferCapabilities('nomic-embed-text')).toEqual(['embedding']);
  });

  it('still marks whisper / dall-e / tts families with their own capabilities', () => {
    expect(inferCapabilities('whisper-1')).toEqual(expect.arrayContaining(['chat', 'asr']));
    expect(inferCapabilities('dall-e-3')).toEqual(expect.arrayContaining(['chat', 'image_gen']));
    expect(inferCapabilities('tts-1')).toEqual(expect.arrayContaining(['chat', 'tts']));
  });

  it('always includes chat for ordinary text models', () => {
    expect(inferCapabilities('qwen2.5-14b-instruct')).toContain('chat');
  });
});

describe('isEmbeddingModelId', () => {
  it('detects embedding and vector model ids', () => {
    expect(isEmbeddingModelId('text-embedding-3-large')).toBe(true);
    expect(isEmbeddingModelId('bge-embed-v1')).toBe(true);
    expect(isEmbeddingModelId('vector-search-v2')).toBe(true);
  });

  it('returns false for chat models', () => {
    expect(isEmbeddingModelId('gpt-4o')).toBe(false);
    expect(isEmbeddingModelId('claude-3-5-sonnet-20241022')).toBe(false);
  });
});
