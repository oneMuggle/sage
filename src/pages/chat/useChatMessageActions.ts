import { useCallback, useMemo, useRef, useState } from 'react';
import type { NavigateFunction } from 'react-router-dom';
import { toast } from 'sonner';

import { regenerateInPlace } from '../../features/chat/answerVersions';
import { useQuoteDraft } from '../../features/chat/useQuoteDraft';
import { sessionApi, learnApi, messageApi, memoryApi } from '../../shared/api';
import { orchRunClient } from '../../shared/api/orchRunClient';
import { useI18n } from '../../shared/lib/i18n';
import type { Message as MessageType } from '../../shared/lib/store';

/** t() 结果是静态模板，这里做最小占位符替换（i18n 无内置插值）。 */
export function fill(template: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (acc, [key, value]) => acc.replace(`{${key}}`, String(value)),
    template,
  );
}

export interface UseChatMessageActionsParams {
  currentSessionId: string | null;
  isLoading: boolean;
  messages: MessageType[];
  loadMessages: (sessionId: string) => Promise<void>;
  loadSessions: () => Promise<void>;
  setCurrentSessionId: (id: string | null) => void;
  removeMessage: (id: string) => void;
  sendMessage: (
    content: string,
    sessionId?: string,
    extraRefs?: unknown,
    orchestrateMode?: string,
    extraOptions?: Record<string, unknown>,
  ) => Promise<void>;
  handleSendMessage: (content: string, options?: Record<string, unknown>) => Promise<void>;
  clearTaskBoard: () => void;
  setArchivesOpen: (open: boolean) => void;
  navigate: NavigateFunction;
}

export function useChatMessageActions({
  currentSessionId,
  isLoading,
  messages,
  loadMessages,
  loadSessions,
  setCurrentSessionId,
  removeMessage,
  sendMessage,
  handleSendMessage,
  clearTaskBoard,
  setArchivesOpen,
  navigate,
}: UseChatMessageActionsParams) {
  const { t } = useI18n();
  const messagesRef = useRef(messages);
  messagesRef.current = messages;

  const handleCompact = useCallback(async () => {
    if (!currentSessionId || isLoading) return;
    try {
      const result = await sessionApi.compact(currentSessionId);
      if (result.ok && result.compacted) {
        toast.success(
          fill(t('chat.compact_success'), {
            before: result.before,
            after: result.after,
            removed: result.removed,
          }),
          { action: { label: '查看归档', onClick: () => setArchivesOpen(true) } },
        );
        await loadMessages(currentSessionId);
      } else if (result.ok) {
        toast.info(t('chat.compact_skipped'));
      } else {
        toast.error(
          fill(t('chat.compact_failed'), { message: result.message ?? result.error ?? '' }),
        );
      }
    } catch (e) {
      toast.error(
        fill(t('chat.compact_failed'), { message: e instanceof Error ? e.message : String(e) }),
      );
    }
  }, [currentSessionId, isLoading, loadMessages, setArchivesOpen, t]);

  const handleLearn = useCallback(async () => {
    if (!currentSessionId || isLoading) return;
    try {
      toast.info(t('chat.learn_reviewing'));
      await learnApi.trigger(currentSessionId);
      toast.success(t('chat.learn_queued'));
      navigate('/skills?tab=drafts');
    } catch (e) {
      toast.error(
        fill(t('chat.learn_failed'), { error: e instanceof Error ? e.message : String(e) }),
      );
    }
  }, [currentSessionId, isLoading, navigate, t]);

  const handleFork = useCallback(
    async (messageId: string) => {
      if (!currentSessionId || isLoading) return;
      try {
        const forked = await sessionApi.fork(currentSessionId, messageId);
        toast.success(t('chat.fork_success'));
        void loadSessions();
        setCurrentSessionId(forked.id);
      } catch (e) {
        toast.error(
          fill(t('chat.fork_failed'), { message: e instanceof Error ? e.message : String(e) }),
        );
      }
    },
    [currentSessionId, isLoading, loadSessions, setCurrentSessionId, t],
  );

  const [rewindTarget, setRewindTarget] = useState<{ messageId: string; createdAt: number } | null>(
    null,
  );
  const handleRewind = useCallback(
    (messageId: string) => {
      if (!currentSessionId || isLoading) return;
      const target = messagesRef.current.find((m) => m.id === messageId);
      if (!target) return;
      setRewindTarget({ messageId, createdAt: target.created_at });
    },
    [currentSessionId, isLoading],
  );
  const handleRewindForked = useCallback(
    async (forkedId: string) => {
      toast.success(t('chat.rewind_success'));
      setRewindTarget(null);
      void loadSessions();
      setCurrentSessionId(forkedId);
    },
    [loadSessions, setCurrentSessionId, t],
  );

  const [editResendTarget, setEditResendTarget] = useState<{
    messageId: string;
    text: string;
    nonce: number;
  } | null>(null);
  const { quotedDraft, quoteText } = useQuoteDraft();
  const cancelEditResend = useCallback(() => setEditResendTarget(null), []);
  const editResendNotice = useMemo(
    () => (editResendTarget ? { onCancel: cancelEditResend } : null),
    [cancelEditResend, editResendTarget],
  );

  const handleStartEditResend = useCallback((messageId: string) => {
    const target = messagesRef.current.find((m) => m.id === messageId);
    if (!target || target.role !== 'user') return;
    setEditResendTarget({
      messageId,
      text: target.content,
      nonce: Date.now(),
    });
  }, []);

  const handleSendMessageWithEditResend = useCallback(
    async (content: string, options?: Parameters<typeof handleSendMessage>[1]) => {
      if (!editResendTarget) {
        await handleSendMessage(content, options);
        return;
      }
      const target = editResendTarget;
      setEditResendTarget(null);
      if (!currentSessionId || isLoading) {
        await handleSendMessage(content, options);
        return;
      }
      try {
        const forked = await sessionApi.fork(currentSessionId, target.messageId, undefined, {
          beforeMessage: true,
        });
        toast.success(t('chat.edit_resend_forked'));
        void loadSessions();
        setCurrentSessionId(forked.id);
        await sendMessage(content, forked.id);
      } catch (e) {
        toast.error(
          fill(t('chat.fork_failed'), { message: e instanceof Error ? e.message : String(e) }),
        );
        await handleSendMessage(content, options);
      }
    },
    [
      currentSessionId,
      editResendTarget,
      handleSendMessage,
      isLoading,
      loadSessions,
      sendMessage,
      setCurrentSessionId,
      t,
    ],
  );

  const handleRegenerate = useCallback(
    async (assistantMessageId: string) => {
      if (!currentSessionId || isLoading) return;
      const msgs = messagesRef.current;
      const idx = msgs.findIndex((m) => m.id === assistantMessageId);
      if (idx < 0) return;
      if (regenerateInPlace(msgs, idx, currentSessionId, { removeMessage, sendMessage })) return;
      let userIdx = -1;
      for (let i = idx - 1; i >= 0; i--) {
        if (msgs[i].role === 'user') {
          userIdx = i;
          break;
        }
      }
      if (userIdx < 0) return;
      const userMsg = msgs[userIdx];
      try {
        const forked = await sessionApi.fork(currentSessionId, userMsg.id, undefined, {
          beforeMessage: true,
        });
        toast.success(t('chat.regenerate_forked'));
        void loadSessions();
        setCurrentSessionId(forked.id);
        await sendMessage(userMsg.content, forked.id);
      } catch (e) {
        toast.error(
          fill(t('chat.fork_failed'), { message: e instanceof Error ? e.message : String(e) }),
        );
      }
    },
    [currentSessionId, isLoading, loadSessions, removeMessage, sendMessage, setCurrentSessionId, t],
  );

  const handleAnswerVersionChange = useCallback(() => {
    if (currentSessionId) void loadMessages(currentSessionId);
  }, [currentSessionId, loadMessages]);

  const handleContinue = useCallback(() => {
    if (!currentSessionId || isLoading) return;
    void sendMessage(t('chat.continue_prompt'), currentSessionId);
  }, [currentSessionId, isLoading, sendMessage, t]);

  const handleDeleteMessage = useCallback(
    async (messageId: string) => {
      try {
        await messageApi.delete(messageId);
        removeMessage(messageId);
      } catch (e) {
        toast.error(e instanceof Error ? e.message : String(e));
      }
    },
    [removeMessage],
  );

  const handleQuote = useCallback(
    (message: MessageType) => quoteText(message.content),
    [quoteText],
  );

  const handleSaveToMemory = useCallback(
    async (message: MessageType) => {
      try {
        await memoryApi.saveMemory(message.content, 'semantic', 5, ['来自对话']);
        toast.success(t('chat.save_to_memory_success'));
      } catch (e) {
        toast.error(
          fill(t('chat.save_to_memory_failed'), {
            error: e instanceof Error ? e.message : String(e),
          }),
        );
      }
    },
    [t],
  );

  const handleCancelRun = useCallback(
    async (runId: string) => {
      try {
        await orchRunClient.cancelRun(runId);
      } catch {
        // 409 等照常清理
      }
      clearTaskBoard();
    },
    [clearTaskBoard],
  );

  const handleRerunFailed = useCallback(
    async (runId: string, taskIds?: string[]) => {
      if (!currentSessionId) return;
      try {
        const res = await orchRunClient.rerunFailed(runId, taskIds);
        const sid = res.session_id ?? currentSessionId;
        await sendMessage(res.goal, sid, undefined, 'force_multi', {
          planOverride: res.plan_override,
        });
      } catch {
        toast.error('重跑失败任务请求失败（run 未终态或无失败任务）');
      }
    },
    [currentSessionId, sendMessage],
  );

  return {
    handleCompact,
    handleLearn,
    handleFork,
    rewindTarget,
    setRewindTarget,
    handleRewind,
    handleRewindForked,
    editResendTarget,
    editResendNotice,
    quotedDraft,
    quoteText,
    handleStartEditResend,
    handleSendMessageWithEditResend,
    handleRegenerate,
    handleAnswerVersionChange,
    handleContinue,
    handleDeleteMessage,
    handleQuote,
    handleSaveToMemory,
    handleCancelRun,
    handleRerunFailed,
  };
}
