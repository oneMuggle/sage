/**
 * 超长文档检索注入（RAG 切片 4a/4b，r67）配置。
 *
 * 存 localStorage（聊天行为级配置，与主题/模板记忆同口径）：
 *   sage:chat-attachment-rag = {"enabled":boolean,"embed":{...},"top_k":number}
 * Chat.tsx 发送时读取；GeneralTab 提供编辑面板。缺省 disabled。
 */

export interface AttachmentEmbedConfig {
  base_url: string;
  api_key: string;
  model: string;
  dim: number;
}

export interface AttachmentRagConfig {
  enabled: boolean;
  embed: AttachmentEmbedConfig;
  top_k: number;
}

export const ATTACHMENT_RAG_STORAGE_KEY = 'sage:chat-attachment-rag';

export const DEFAULT_ATTACHMENT_RAG_CONFIG: AttachmentRagConfig = {
  enabled: false,
  embed: { base_url: '', api_key: '', model: '', dim: 1536 },
  top_k: 6,
};

/** 读取配置；缺省/损坏时返回默认（enabled=false 保证零行为变化）。 */
export function loadAttachmentRagConfig(): AttachmentRagConfig {
  try {
    const raw = window.localStorage.getItem(ATTACHMENT_RAG_STORAGE_KEY);
    if (!raw) return { ...DEFAULT_ATTACHMENT_RAG_CONFIG };
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) {
      return { ...DEFAULT_ATTACHMENT_RAG_CONFIG };
    }
    const p = parsed as Partial<AttachmentRagConfig>;
    const embed = p.embed ?? DEFAULT_ATTACHMENT_RAG_CONFIG.embed;
    return {
      enabled: p.enabled === true,
      embed: {
        base_url: String(embed.base_url ?? ''),
        api_key: String(embed.api_key ?? ''),
        model: String(embed.model ?? ''),
        dim: Number(embed.dim) || DEFAULT_ATTACHMENT_RAG_CONFIG.embed.dim,
      },
      top_k: Number(p.top_k) || DEFAULT_ATTACHMENT_RAG_CONFIG.top_k,
    };
  } catch {
    return { ...DEFAULT_ATTACHMENT_RAG_CONFIG };
  }
}

export function saveAttachmentRagConfig(config: AttachmentRagConfig): void {
  try {
    window.localStorage.setItem(ATTACHMENT_RAG_STORAGE_KEY, JSON.stringify(config));
  } catch {
    // ignore — localStorage 不可用时静默
  }
}
