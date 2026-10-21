/** r74 — 附件自动索引触发条件单测（mock attachmentRagClient + sonner）。 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const indexAttachmentMock = vi.fn();
const toastInfo = vi.fn();
const toastWarning = vi.fn();

vi.mock('../attachmentRagClient', () => ({
  attachmentRagClient: {
    indexAttachment: (...args: unknown[]) => indexAttachmentMock(...args),
  },
}));
vi.mock('sonner', () => ({
  toast: { info: (...a: unknown[]) => toastInfo(...a), warning: (...a: unknown[]) => toastWarning(...a) },
}));

import { isAttachmentIndexReady, maybeIndexAttachment } from '../attachmentAutoIndex';
import { saveAttachmentRagConfig } from '../attachmentRagConfig';

const ENABLED_CFG = {
  enabled: true,
  embed: { base_url: 'https://e/v1', api_key: 'k', model: 'emb', dim: 512 },
  top_k: 3,
};

describe('attachmentAutoIndex', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it('配置未启用 → 不索引', () => {
    expect(isAttachmentIndexReady()).toBe(false);
    expect(maybeIndexAttachment('m1')).toBe(false);
    expect(indexAttachmentMock).not.toHaveBeenCalled();
  });

  it('启用但端点不全 → 不索引', () => {
    saveAttachmentRagConfig({ ...ENABLED_CFG, embed: { ...ENABLED_CFG.embed, base_url: '' } });
    expect(maybeIndexAttachment('m1')).toBe(false);
  });

  it('就绪 → 发起索引并回传 media id', () => {
    saveAttachmentRagConfig(ENABLED_CFG);
    indexAttachmentMock.mockResolvedValue({ media_id: 'm1', page_path: 'p', chunks: 3, dim: 512 });
    expect(maybeIndexAttachment('m1')).toBe(true);
    expect(indexAttachmentMock).toHaveBeenCalledWith(
      'm1',
      { base_url: 'https://e/v1', api_key: 'k', model: 'emb', dim: 512 },
    );
  });

  it('索引失败 → toast 警告（不影响发送）', async () => {
    saveAttachmentRagConfig(ENABLED_CFG);
    indexAttachmentMock.mockRejectedValue(new Error('down'));
    expect(maybeIndexAttachment('m1')).toBe(true);
    await new Promise((r) => setTimeout(r, 0));
    expect(toastWarning).toHaveBeenCalled();
  });
});
