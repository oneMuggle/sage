// src/widgets/chat/ChatSessionNotices.tsx
//
// Issue 1 (2026-10-29) 顺带把 Chat.tsx 的会话级提示组装逻辑抽出来。
//
// 拆分动机：
//   1. Chat.tsx 已逼近 800 行架构门禁；四类通知（临时错误 / 会话失败 /
//      运行中断 / 话题切换）的组装逻辑占 ~60 行，是独立关注点。
//   2. 四类通知各有各的"已忽略"会话集合（dismissed errors / interrupts /
//      failures），放在页面组件里让页面承担了不属于它的状态职责。
//
// 本组件只负责"决定显示哪些通知"并渲染 ChatNoticeStack；具体横幅的
// 交互（重试 / 忽略 / 恢复）仍由各横幅组件自己承担。

import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import type { Message } from '../../shared/lib/store';

import { ChatInlineError } from './ChatInlineError';
import { CHAT_NOTICE_PRIORITY, ChatNoticeStack } from './ChatNoticeStack';
import { INTERRUPTED_RUN_ERROR, InterruptedRunBanner } from './InterruptedRunBanner';
import { SessionFailedBanner } from './SessionFailedBanner';
import { TopicShiftBanner } from './TopicShiftBanner';

/** 聊天页消费会话列表时只需要这两个字段，做窄化避免耦合整个 Session 类型 */
export interface ChatSessionNoticeTarget {
  run_status?: string | null;
  last_error?: string | null;
}

interface ChatSessionNoticesProps {
  currentSessionId: string | null;
  currentSession: ChatSessionNoticeTarget | undefined;
  /** 本次会话内的临时错误（R17-D：只渲染归属当前会话的） */
  error: string | null;
  errorSessionId: string | null;
  messages: Message[];
  /** 话题切换提示的原因文案，null 表示无切换 */
  shiftInfo: { reason: string } | null;
  /** 正在流式输出时隐藏话题切换横幅（迁移前行为） */
  isLoading: boolean;
  onClearError: () => void;
  onSendMessage: (content: string, sessionId?: string) => void;
  onRetreat: () => void;
}

export function ChatSessionNotices({
  currentSessionId,
  currentSession,
  error,
  errorSessionId,
  messages,
  shiftInfo,
  isLoading,
  onClearError,
  onSendMessage,
  onRetreat,
}: ChatSessionNoticesProps) {
  const [dismissedInterrupts, setDismissedInterrupts] = useState<Set<string>>(new Set());
  const [dismissedFailures, setDismissedFailures] = useState<Set<string>>(new Set());

  // 切换会话时重置"已忽略"集合：每个会话的忽略是独立的，
  // 否则在 A 关闭横幅后切到 B 再切回 A，A 的横幅会永久消失。
  useEffect(() => {
    setDismissedInterrupts(new Set<string>());
    setDismissedFailures(new Set<string>());
  }, [currentSessionId]);

  // 重发最后一条 user 消息 —— 中断恢复与失败恢复共用同一动作。
  const retryLastUserMessage = useCallback(() => {
    if (!currentSessionId) return;
    const lastUser = [...messages].reverse().find((m) => m.role === 'user');
    if (!lastUser) {
      toast.error('找不到可重发的消息');
      return;
    }
    onSendMessage(lastUser.content, currentSessionId);
  }, [currentSessionId, messages, onSendMessage]);

  // L16: 应用重启把滞留 running 的会话标记成固定文案，属"可一键恢复"的特殊终态
  const interruptedRun =
    currentSession?.run_status === 'failed' && currentSession?.last_error === INTERRUPTED_RUN_ERROR;
  const showInterruptBanner =
    currentSessionId != null && interruptedRun && !dismissedInterrupts.has(currentSessionId);

  // Issue 1: 其余一切失败终态 —— 展示真实失败原因，与中断横幅互斥
  const sessionFailed =
    currentSession?.run_status === 'failed' &&
    currentSession?.last_error != null &&
    currentSession.last_error !== '' &&
    currentSession.last_error !== INTERRUPTED_RUN_ERROR;
  const showSessionFailedBanner =
    currentSessionId != null && sessionFailed && !dismissedFailures.has(currentSessionId);

  const showTopicShiftBanner = currentSessionId != null && shiftInfo != null && !isLoading;

  return (
    <ChatNoticeStack
      notices={[
        error != null &&
          error !== '' &&
          errorSessionId === currentSessionId && {
            key: 'error',
            priority: CHAT_NOTICE_PRIORITY.error,
            node: (
              <ChatInlineError
                error={error}
                onRetry={() => {
                  onClearError();
                  const lastUser = [...messages].reverse().find((m) => m.role === 'user');
                  if (lastUser && currentSessionId) onSendMessage(lastUser.content, currentSessionId);
                }}
                onClose={onClearError}
              />
            ),
          },
        showSessionFailedBanner && {
          key: 'session-failed',
          priority: CHAT_NOTICE_PRIORITY.sessionFailed,
          node: (
            <SessionFailedBanner
              reason={currentSession?.last_error ?? ''}
              onRetry={retryLastUserMessage}
              onDismiss={() =>
                setDismissedFailures((prev) => new Set(prev).add(currentSessionId ?? ''))
              }
            />
          ),
        },
        showInterruptBanner && {
          key: 'interrupted',
          priority: CHAT_NOTICE_PRIORITY.interrupted,
          node: (
            <InterruptedRunBanner
              onRetry={retryLastUserMessage}
              onDismiss={() =>
                setDismissedInterrupts((prev) => new Set(prev).add(currentSessionId ?? ''))
              }
            />
          ),
        },
        showTopicShiftBanner && {
          key: 'topic-shift',
          priority: CHAT_NOTICE_PRIORITY.topicShift,
          node: (
            <TopicShiftBanner
              sessionId={currentSessionId!}
              reason={shiftInfo!.reason}
              onRetreat={() => void onRetreat()}
            />
          ),
        },
      ]}
    />
  );
}
