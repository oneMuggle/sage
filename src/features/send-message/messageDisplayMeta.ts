// src/features/send-message/messageDisplayMeta.ts
//
// 用户消息的展示元数据构建 —— 只影响会话气泡回显，不参与 LLM 上下文。
// 发送时随 chat_stream 的 message_meta 落库到 messages.client_meta，
// 刷新会话后由 get_messages 回读。
import type {
  ChatOfficeRef,
  MessageDisplayFileRef,
  MessageDisplayMeta,
} from '../../shared/api/types';

/**
 * 与后端 attachment_resolver._MENTION_RE 同口径（@ 前为空白/开头），但额外
 * 在中文句读/常见分隔符处截断 —— 中文输入通常不用空格分词，`@README.md，谢谢`
 * 不应把”，谢谢”算进路径。
 * 2026-10-29 修复:
 * - 捕获类排除 `@`（相邻 mention 不会被合并为一条路径）
 * - 改用 lookbehind 作为前缀断言（不消耗字符，允许 `”@path` 这类紧跟引号的场景）
 * - TRAILING_PUNCTUATION 包含引号, 避免 `”@src/App.tsx”` 残留 `”` 到路径中
 */
const FILE_REF_RE =
  /(?:(?<=\s)|(?<=^)|(?<=[\x22(]))@([^\s@，。；：！？、（）()【】「」『』《》,;!?]+)/g;
/** 句末标点与引号不属于路径（中文输入时常见）。 */
const TRAILING_PUNCTUATION = /[.,;:!?，。；：！？)】」》\]'\x22`]+$/;

/**
 * 从消息正文提取 `@path` 文件引用。只保留含 `/` 或 `.` 的 token，
 * 过滤 `@某人` 这类纯文本提及（与后端 attachment_resolver 的噪声过滤一致）。
 */
export function extractFileRefs(content: string): MessageDisplayFileRef[] {
  const refs: MessageDisplayFileRef[] = [];
  const seen = new Set<string>();
  FILE_REF_RE.lastIndex = 0;
  let match: RegExpExecArray | null = FILE_REF_RE.exec(content);
  while (match !== null) {
    const raw = match[1].replace(TRAILING_PUNCTUATION, '');
    if ((raw.includes('.') || raw.includes('/')) && !seen.has(raw)) {
      seen.add(raw);
      refs.push({ path: raw, name: raw.split(/[\\/]/).pop() || raw });
    }
    match = FILE_REF_RE.exec(content);
  }
  return refs;
}

export interface BuildMessageDisplayMetaInput {
  content: string;
  attachments?: readonly { name: string; size: number; type: string; dataUrl?: string }[];
  images?: readonly { name: string; size: number; type: string; dataUrl?: string }[];
  officeRefs?: readonly ChatOfficeRef[];
  knowledgeRefs?: readonly { id: string; title: string }[];
  /** 发送时的工作区根目录；随 office_refs 落库，供历史消息在切换工作区后定位文档。 */
  workspacePath?: string;
}

/** 汇总一条用户消息的全部引用信息；无任何引用时返回 undefined。 */
export function buildMessageDisplayMeta({
  content,
  attachments,
  images,
  officeRefs,
  knowledgeRefs,
  workspacePath,
}: BuildMessageDisplayMetaInput): MessageDisplayMeta | undefined {
  const fileRefs = extractFileRefs(content);
  const meta: MessageDisplayMeta = {
    ...(attachments && attachments.length > 0
      ? { attachments: attachments.map(({ name, size, type }) => ({ name, size, type })) }
      : {}),
    ...(images && images.length > 0
      ? { images: images.map(({ name, size, type }) => ({ name, size, type })) }
      : {}),
    ...(fileRefs.length > 0 ? { file_refs: fileRefs } : {}),
    ...(officeRefs && officeRefs.length > 0
      ? {
          office_refs: officeRefs.map(({ docId, docType, filename }) => ({
            doc_id: docId,
            doc_type: docType,
            filename,
            ...(workspacePath ? { workspace_path: workspacePath } : {}),
          })),
        }
      : {}),
    ...(knowledgeRefs && knowledgeRefs.length > 0
      ? { knowledge_refs: knowledgeRefs.map(({ id, title }) => ({ id, title })) }
      : {}),
  };
  return Object.keys(meta).length > 0 ? meta : undefined;
}
