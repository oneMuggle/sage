/**
 * r74: 附件上传后自动建立向量索引（opt-in）。
 *
 * 仅当 GeneralTab「超长文档检索注入」配置启用时触发（fire-and-forget：
 * 索引失败只 toast 提示，绝不阻断消息发送——与 R37 fail-safe 同口径）。
 */

import { toast } from 'sonner';

import { attachmentRagClient } from './attachmentRagClient';
import {
  loadAttachmentRagConfig,
  type AttachmentEmbedConfig,
} from './attachmentRagConfig';

/** 判断当前配置是否足以发起索引（开关开 + 端点四要素齐全）。 */
export function isAttachmentIndexReady(): boolean {
  const cfg = loadAttachmentRagConfig();
  return (
    cfg.enabled &&
    cfg.embed.base_url.trim() !== '' &&
    cfg.embed.model.trim() !== '' &&
    Number.isFinite(cfg.embed.dim) &&
    cfg.embed.dim > 0
  );
}

/**
 * 上传成功后按需索引。调用方 fire-and-forget（不 await）。
 * 返回是否发起了索引（测试断言用）。
 */
export function maybeIndexAttachment(mediaId: string): boolean {
  if (!isAttachmentIndexReady()) return false;
  const cfg = loadAttachmentRagConfig();
  const embed: AttachmentEmbedConfig = {
    base_url: cfg.embed.base_url.trim(),
    api_key: cfg.embed.api_key,
    model: cfg.embed.model.trim(),
    dim: cfg.embed.dim,
  };
  void attachmentRagClient
    .indexAttachment(mediaId, embed)
    .then((report) => {
      if (report.chunks > 0) {
        toast.info(`附件已建立检索索引（${report.chunks} 片段）`);
      }
    })
    .catch(() => {
      toast.warning('附件检索索引失败（不影响本次发送）');
    });
  return true;
}
