/** r67 — 附件检索注入配置存取单测。 */
import { beforeEach, describe, expect, it } from 'vitest';

import {
  ATTACHMENT_RAG_STORAGE_KEY,
  DEFAULT_ATTACHMENT_RAG_CONFIG,
  loadAttachmentRagConfig,
  saveAttachmentRagConfig,
} from '../attachmentRagConfig';

describe('attachmentRagConfig', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('缺省返回 disabled 默认配置（零行为变化）', () => {
    const cfg = loadAttachmentRagConfig();
    expect(cfg.enabled).toBe(false);
    expect(cfg).toEqual(DEFAULT_ATTACHMENT_RAG_CONFIG);
  });

  it('保存后读取一致', () => {
    const cfg = {
      enabled: true,
      embed: { base_url: 'https://e/v1', api_key: 'k', model: 'emb', dim: 512 },
      top_k: 3,
    };
    saveAttachmentRagConfig(cfg);
    expect(loadAttachmentRagConfig()).toEqual(cfg);
    expect(
      JSON.parse(window.localStorage.getItem(ATTACHMENT_RAG_STORAGE_KEY) ?? '{}').enabled,
    ).toBe(true);
  });

  it('损坏 JSON 回退默认', () => {
    window.localStorage.setItem(ATTACHMENT_RAG_STORAGE_KEY, '{broken');
    const cfg = loadAttachmentRagConfig();
    expect(cfg.enabled).toBe(false);
    expect(cfg).toEqual(DEFAULT_ATTACHMENT_RAG_CONFIG);
  });

  it('部分字段缺失时逐字段兜底', () => {
    window.localStorage.setItem(
      ATTACHMENT_RAG_STORAGE_KEY,
      JSON.stringify({ enabled: true, embed: { base_url: 'https://x' } }),
    );
    const cfg = loadAttachmentRagConfig();
    expect(cfg.enabled).toBe(true);
    expect(cfg.embed.base_url).toBe('https://x');
    expect(cfg.embed.api_key).toBe('');
    expect(cfg.embed.dim).toBe(DEFAULT_ATTACHMENT_RAG_CONFIG.embed.dim);
    expect(cfg.top_k).toBe(DEFAULT_ATTACHMENT_RAG_CONFIG.top_k);
  });
});
