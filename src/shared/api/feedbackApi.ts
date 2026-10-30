// src/shared/api/feedbackApi.ts
//
// 用户反馈系统的 renderer 侧 client。所有后端 DTO 以 snake_case 直接返回（invokeBackend
// 不翻译响应），renderer 入参统一 camelCase（invokeBackend 的 camelToSnakeKeys 负责
// 翻译 body 输出）。附件上传走 raw-binary IPC，不经 invoke —— 通过 preload 暴露的
// `window.electronAPI.feedback.uploadAttachment` 通道。
//
// 设计见 docs/technical/111-feedback-relay-deployment.md §11.2。

import { invoke } from './desktopInvoke';

// ──────────── 后端 DTO（snake_case，与 backend/api/feedback_routes.py 对齐） ────────────

export interface FeedbackMessageDto {
  id: string;
  conversation_id: string;
  role: string;
  body: string;
  media_ids: string[];
  created_at: number;
  synced_at: number | null;
}

export type FeedbackTag = 'bug' | 'feature' | 'other';

export const FEEDBACK_TAGS: readonly FeedbackTag[] = ['bug', 'feature', 'other'];

export interface FeedbackConversationDto {
  id: string;
  title: string;
  status: string;
  tag: string;
  app_version: string;
  os_info: string;
  remote_ticket_id: string | null;
  remote_ticket_url: string | null;
  last_activity_at: number;
  created_at: number;
  updated_at: number;
}

export interface ConversationDetailDto {
  conversation: FeedbackConversationDto;
  messages: FeedbackMessageDto[];
}

export interface AppendMessageResponseDto {
  id: string;
  conversation_id: string;
  created_at: number;
  received: boolean;
}

export interface AttachmentUploadResultDto {
  id: string;
  conversation_id: string;
}

export interface LogTailDto {
  text: string;
  lines: string[];
}

export interface FeedbackSearchHitDto {
  conversation_id: string;
  conversation_title: string;
  message_id: string;
  role: string;
  body: string;
  created_at: number;
}

export interface SyncStatsDto {
  submitted: number;
  received: number;
  errors: number;
}

// ──────────── 入参（camelCase，invokeBackend 翻译为 snake_case） ────────────

export interface CreateConversationArgs {
  title: string;
  body: string;
  tag?: FeedbackTag;
  id?: string;
  mediaIds?: string[];
}

export interface AppendMessageArgs {
  conversationId: string;
  body: string;
  role?: 'user' | 'admin';
  id?: string;
  mediaIds?: string[];
}

export interface UpdateStatusArgs {
  id: string;
  status: 'open' | 'resolved' | 'closed';
}

// ──────────── 命令封装 ────────────

export async function listConversations(limit: number = 50): Promise<FeedbackConversationDto[]> {
  return invoke<FeedbackConversationDto[]>('feedback_conversations', { limit });
}

export async function getConversation(id: string): Promise<ConversationDetailDto> {
  return invoke<ConversationDetailDto>('feedback_conversation_get', { id });
}

export async function createConversation(
  args: CreateConversationArgs,
): Promise<FeedbackConversationDto> {
  return invoke<FeedbackConversationDto>(
    'feedback_conversation_create',
    args as unknown as Record<string, unknown>,
  );
}

export async function appendMessage(args: AppendMessageArgs): Promise<AppendMessageResponseDto> {
  return invoke<AppendMessageResponseDto>(
    'feedback_message_append',
    args as unknown as Record<string, unknown>,
  );
}

export async function updateConversationStatus(args: UpdateStatusArgs): Promise<void> {
  await invoke<void>(
    'feedback_conversation_status_update',
    args as unknown as Record<string, unknown>,
  );
}

export async function fetchLogTail(maxLines: number = 200): Promise<LogTailDto> {
  return invoke<LogTailDto>('feedback_log_tail', { maxLines });
}

/** 按关键词搜索消息正文。空查询由 backend 直接返回空数组。 */
export async function searchMessages(
  query: string,
  limit: number = 50,
): Promise<FeedbackSearchHitDto[]> {
  return invoke<FeedbackSearchHitDto[]>('feedback_search', { q: query, limit });
}

/**
 * 上传附件（截图 / 日志片段）。
 *
 * 走 raw-binary IPC（`feedback:attachment:upload`），绕过 invoke ——
 * base64 载荷不经 invokeBackend 的 camelToSnakeKeys 翻译（载荷 key 是
 * 文件名 / MIME，非 JS 标识符），也不经后端 LocalAuth 路由（本地 IPC）。
 */
export async function uploadAttachment(payload: {
  conversationId: string;
  filename: string;
  mimeType: string;
  dataBase64: string;
}): Promise<AttachmentUploadResultDto> {
  const bridge = window.electronAPI?.feedback;
  if (!bridge) {
    throw new Error('反馈附件上传仅桌面端可用（Electron IPC 缺失）');
  }
  return bridge.uploadAttachment(payload);
}

/**
 * 触发一次手动同步（提交本地未发 + 拉取管理员回复）。
 * 与上传走同一通道：main 进程本地 IPC，不经后端。
 */
export async function syncNow(): Promise<SyncStatsDto> {
  const bridge = window.electronAPI?.feedback;
  if (!bridge) {
    throw new Error('反馈同步仅桌面端可用（Electron IPC 缺失）');
  }
  return bridge.syncNow();
}

// ──────────── 治理审计 ────────────

export function auditFeedbackApiGovernance(): {
  module: 'src/shared/api/feedbackApi.ts';
  phase: 'P1';
  domain: 'feedback';
  supportsAllSixCommands: boolean;
  supportsAttachmentUpload: boolean;
} {
  return {
    module: 'src/shared/api/feedbackApi.ts',
    phase: 'P1',
    domain: 'feedback',
    supportsAllSixCommands: true,
    supportsAttachmentUpload: true,
  };
}
