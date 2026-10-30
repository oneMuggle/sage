// src/features/feedback/feedbackStore.ts
//
// 用户反馈系统的 renderer 全局状态。Zustand module-singleton —— FeedbackHub、
// 菜单入口、同步徽标共享同一份 state，避免列表与详情重复拉取。
//
// 设计见 docs/plans/2026-10-29_direct-feedback-channel.md §4。

import { create } from 'zustand';

import * as feedbackApi from '../../shared/api/feedbackApi';
import type {
  AppendMessageArgs,
  ConversationDetailDto,
  CreateConversationArgs,
  FeedbackConversationDto,
  FeedbackMessageDto,
  SyncStatsDto,
} from '../../shared/api/feedbackApi';

type ConversationStatus = 'open' | 'resolved' | 'closed';

interface FeedbackLoadingState {
  list: boolean;
  /** 按会话 ID 的详情加载态 */
  detail: Record<string, boolean>;
  create: boolean;
  send: boolean;
  sync: boolean;
}

interface FeedbackErrorState {
  list: string | null;
  detail: Record<string, string | null>;
  submit: string | null;
}

interface FeedbackState {
  conversations: FeedbackConversationDto[];
  detailById: Record<string, ConversationDetailDto>;
  currentId: string | null;
  logTail: string | null;
  syncStats: SyncStatsDto | null;

  loading: FeedbackLoadingState;
  errors: FeedbackErrorState;

  refreshList: () => Promise<void>;
  openConversation: (id: string) => Promise<void>;
  selectConversation: (id: string | null) => void;
  createAndOpen: (args: CreateConversationArgs) => Promise<string | null>;
  sendMessage: (args: Omit<AppendMessageArgs, 'conversationId'>) => Promise<boolean>;
  setStatus: (id: string, status: ConversationStatus) => Promise<boolean>;
  refreshLogTail: () => Promise<void>;
  triggerSync: () => Promise<void>;
  reset: () => void;
}

const initialLoading = (): FeedbackLoadingState => ({
  list: false,
  detail: {},
  create: false,
  send: false,
  sync: false,
});

const initialErrors = (): FeedbackErrorState => ({
  list: null,
  detail: {},
  submit: null,
});

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export const useFeedbackStore = create<FeedbackState>((set, get) => ({
  conversations: [],
  detailById: {},
  currentId: null,
  logTail: null,
  syncStats: null,
  loading: initialLoading(),
  errors: initialErrors(),

  refreshList: async () => {
    if (get().loading.list) return;
    set((s) => ({
      loading: { ...s.loading, list: true },
      errors: { ...s.errors, list: null },
    }));
    try {
      const list = await feedbackApi.listConversations(50);
      set((s) => ({ conversations: list, loading: { ...s.loading, list: false } }));
    } catch (err) {
      set((s) => ({
        loading: { ...s.loading, list: false },
        errors: { ...s.errors, list: errorMessage(err) },
      }));
    }
  },

  openConversation: async (id) => {
    const cached = get().detailById[id];
    if (cached && !get().loading.detail[id]) {
      set({ currentId: id });
      return;
    }
    set((s) => ({
      currentId: id,
      loading: { ...s.loading, detail: { ...s.loading.detail, [id]: true } },
      errors: { ...s.errors, detail: { ...s.errors.detail, [id]: null } },
    }));
    try {
      const detail = await feedbackApi.getConversation(id);
      set((s) => ({
        detailById: { ...s.detailById, [id]: detail },
        loading: { ...s.loading, detail: { ...s.loading.detail, [id]: false } },
      }));
    } catch (err) {
      set((s) => ({
        loading: { ...s.loading, detail: { ...s.loading.detail, [id]: false } },
        errors: {
          ...s.errors,
          detail: { ...s.errors.detail, [id]: errorMessage(err) },
        },
      }));
    }
  },

  selectConversation: (id) => {
    set({ currentId: id });
  },

  createAndOpen: async (args) => {
    if (get().loading.create) return null;
    set((s) => ({ loading: { ...s.loading, create: true } }));
    try {
      const created = await feedbackApi.createConversation(args);
      set((s) => ({
        conversations: [created, ...s.conversations.filter((c) => c.id !== created.id)],
        loading: { ...s.loading, create: false },
      }));
      await get().openConversation(created.id);
      return created.id;
    } catch (err) {
      set((s) => ({
        loading: { ...s.loading, create: false },
        errors: { ...s.errors, submit: errorMessage(err) },
      }));
      return null;
    }
  },

  sendMessage: async (args) => {
    const currentId = get().currentId;
    if (!currentId || get().loading.send) return false;
    set((s) => ({
      loading: { ...s.loading, send: true },
      errors: { ...s.errors, submit: null },
    }));
    try {
      const resp = await feedbackApi.appendMessage({ ...args, conversationId: currentId });
      const appended: FeedbackMessageDto = {
        id: resp.id,
        conversation_id: resp.conversation_id,
        role: args.role ?? 'user',
        body: args.body,
        media_ids: args.mediaIds ?? [],
        created_at: resp.created_at,
        synced_at: null,
      };
      const prevDetail = get().detailById[currentId];
      set((s) => ({
        detailById: prevDetail
          ? {
              ...s.detailById,
              [currentId]: {
                ...prevDetail,
                messages: [...prevDetail.messages, appended],
              },
            }
          : s.detailById,
        conversations: s.conversations.map((c) =>
          c.id === currentId ? { ...c, last_activity_at: resp.created_at } : c,
        ),
        loading: { ...s.loading, send: false },
      }));
      // 详情未缓存（用户直接从菜单发起后续消息）→ 补拉一次
      if (!prevDetail) await get().openConversation(currentId);
      return true;
    } catch (err) {
      set((s) => ({
        loading: { ...s.loading, send: false },
        errors: { ...s.errors, submit: errorMessage(err) },
      }));
      return false;
    }
  },

  setStatus: async (id, status) => {
    try {
      await feedbackApi.updateConversationStatus({ id, status });
      set((s) => {
        const detail = s.detailById[id];
        return {
          conversations: s.conversations.map((c) => (c.id === id ? { ...c, status } : c)),
          detailById: detail
            ? {
                ...s.detailById,
                [id]: { ...detail, conversation: { ...detail.conversation, status } },
              }
            : s.detailById,
        };
      });
      return true;
    } catch (err) {
      set((s) => ({ errors: { ...s.errors, submit: errorMessage(err) } }));
      return false;
    }
  },

  refreshLogTail: async () => {
    try {
      const tail = await feedbackApi.fetchLogTail(200);
      set({ logTail: tail.text });
    } catch (err) {
      set((s) => ({ errors: { ...s.errors, submit: errorMessage(err) } }));
    }
  },

  triggerSync: async () => {
    if (get().loading.sync) return;
    set((s) => ({ loading: { ...s.loading, sync: true } }));
    try {
      const stats = await feedbackApi.syncNow();
      set((s) => ({ syncStats: stats, loading: { ...s.loading, sync: false } }));
      // 同步可能拉回管理员回复 → 丢弃当前详情缓存并重载
      const currentId = get().currentId;
      if (currentId) {
        set((s) => {
          const next = { ...s.detailById };
          delete next[currentId];
          return { detailById: next };
        });
      }
      await get().refreshList();
      if (currentId) await get().openConversation(currentId);
    } catch (err) {
      set((s) => ({
        loading: { ...s.loading, sync: false },
        errors: { ...s.errors, submit: errorMessage(err) },
      }));
    }
  },

  reset: () => {
    set({
      conversations: [],
      detailById: {},
      currentId: null,
      logTail: null,
      syncStats: null,
      loading: initialLoading(),
      errors: initialErrors(),
    });
  },
}));

// ──────────── 治理审计 ────────────

export interface FeedbackStoreAuditSnapshot {
  conversationCount: number;
  cachedDetailCount: number;
  currentId: string | null;
  loadingList: boolean;
  loadingDetailCount: number;
  errorCount: number;
  signature: string;
}

export function buildFeedbackStoreAuditSnapshot(
  state?: Partial<FeedbackState>,
): FeedbackStoreAuditSnapshot {
  const s = state ?? useFeedbackStore.getState();
  const conversations = s.conversations ?? [];
  const detailById = s.detailById ?? {};
  const loading = s.loading ?? initialLoading();
  const errors = s.errors ?? initialErrors();
  const loadingDetailCount = Object.values(loading.detail).filter(Boolean).length;
  const errorCount =
    (errors.list ? 1 : 0) +
    Object.values(errors.detail).filter((m) => typeof m === 'string' && m.length > 0).length +
    (errors.submit ? 1 : 0);
  return {
    conversationCount: conversations.length,
    cachedDetailCount: Object.keys(detailById).length,
    currentId: s.currentId ?? null,
    loadingList: loading.list,
    loadingDetailCount,
    errorCount,
    signature: `${conversations.length}|${Object.keys(detailById).length}|${
      s.currentId ?? '-'
    }|${loading.list}|${loadingDetailCount}|${errorCount}`,
  };
}

export function buildFeedbackStoreAuditJson(state?: Partial<FeedbackState>): string {
  return JSON.stringify(buildFeedbackStoreAuditSnapshot(state), null, 2);
}

export function auditFeedbackStoreGovernance(): {
  module: 'src/features/feedback/feedbackStore.ts';
  phase: 'P1';
  domain: 'feedback';
  hasStoreHook: boolean;
} {
  return {
    module: 'src/features/feedback/feedbackStore.ts',
    phase: 'P1',
    domain: 'feedback',
    hasStoreHook: typeof useFeedbackStore === 'function',
  };
}
