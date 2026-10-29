// src/features/send-message/pendingComposerOptions.ts
//
// 新会话页（Welcome）→ 聊天页（Chat）首条消息的附件/引用载荷。
// WelcomeInputCard 收集的本地附件与 office 引用通过 router state 传递，
// 由 Chat 页在创建/复用会话后调用 handleSendMessage 完成上传与发送。
import type { ChatOfficeRef } from '../../shared/api/types';

export interface PendingComposerOptions {
  /** 待上传的文档附件（含 dataUrl；发送后由 Chat 上传为 media id） */
  attachments?: { name: string; size: number; type: string; dataUrl?: string }[];
  /** 聊天图片（base64 data URL；后端限 4 张 / 单张 5MiB） */
  images?: { name: string; size: number; type: string; dataUrl?: string }[];
  /** `@` 菜单选择的 Office 引用 */
  officeRefs?: readonly ChatOfficeRef[];
  /** 知识库引用（当前仅展示，不发往后端） */
  knowledgeRefs?: { id: string; title: string }[];
}
