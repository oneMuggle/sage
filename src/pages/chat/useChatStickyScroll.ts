import { useEffect, useLayoutEffect, useRef, useState } from 'react';

import { useChatStreamStore, type TaskBoardState } from '../../features/send-message/chatStreamStore';
import { restoreRunToBoard } from '../../features/send-message/orchestrationEvents';
import { orchRunClient } from '../../shared/api/orchRunClient';
import type { Message as MessageType } from '../../shared/lib/store';

const BOTTOM_THRESHOLD_PX = 96;

export function useChatStickyScroll({
  currentSessionId,
  messages,
  streamingMessageId,
  taskBoard,
}: {
  currentSessionId: string | null;
  messages: MessageType[];
  streamingMessageId: string | null;
  taskBoard: TaskBoardState | null | undefined;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const wasAtBottomRef = useRef(true);
  const lastMsgLengthRef = useRef(0);
  const scrollRafRef = useRef<number | null>(null);
  const programmaticTopRef = useRef<number | null>(null);
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);
  const lastMsg = messages[messages.length - 1];
  const previousMessagesRef = useRef<typeof messages>([]);

  useEffect(() => {
    wasAtBottomRef.current = true;
    lastMsgLengthRef.current = 0;
    previousMessagesRef.current = [];
    setShowJumpToLatest(false);
  }, [currentSessionId]);

  useLayoutEffect(() => {
    const prevLength = lastMsgLengthRef.current;
    const currentLength = messages.length;
    const previousMessages = previousMessagesRef.current;
    const addedUserMessage =
      currentLength > prevLength &&
      messages.slice(previousMessages.length).some((message) => message.role === 'user');
    lastMsgLengthRef.current = currentLength;
    previousMessagesRef.current = messages;

    if (!addedUserMessage && !wasAtBottomRef.current) return;
    if (scrollRafRef.current !== null) return;

    scrollRafRef.current = requestAnimationFrame(() => {
      scrollRafRef.current = null;
      const el = scrollRef.current;
      if (!el) return;
      const top = el.scrollHeight;
      programmaticTopRef.current = top;
      el.scrollTop = top;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- messages 本身不加入 deps
  }, [
    messages.length,
    lastMsg?.content,
    lastMsg?.reasoning_content,
    lastMsg?.tool_calls?.length,
    streamingMessageId,
  ]);

  useEffect(
    () => () => {
      if (scrollRafRef.current !== null) {
        cancelAnimationFrame(scrollRafRef.current);
        scrollRafRef.current = null;
      }
    },
    [],
  );

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const onScroll = () => {
      if (programmaticTopRef.current !== null && el.scrollTop !== programmaticTopRef.current) {
        programmaticTopRef.current = null;
        if (scrollRafRef.current !== null) {
          cancelAnimationFrame(scrollRafRef.current);
          scrollRafRef.current = null;
        }
      }
      const distance = el.scrollHeight - el.clientHeight - el.scrollTop;
      const atBottom = distance <= BOTTOM_THRESHOLD_PX;
      wasAtBottomRef.current = atBottom;
      setShowJumpToLatest(!atBottom && Boolean(streamingMessageId));
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
    return () => {
      el.removeEventListener('scroll', onScroll);
    };
  }, [streamingMessageId]);

  useEffect(() => {
    if (taskBoard && !taskBoard.dispatchedAt && scrollRef.current) {
      const planCard = scrollRef.current.querySelector('[data-testid="plan-card"]');
      if (planCard && typeof planCard.scrollIntoView === 'function') {
        planCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅跟踪 runId + dispatchedAt 变化
  }, [taskBoard?.runId, taskBoard?.dispatchedAt]);

  useEffect(() => {
    if (!currentSessionId) return;
    let cancelled = false;
    const { getState } = useChatStreamStore;
    const slots = getState().sessions[currentSessionId];
    if (slots?.streaming || slots?.taskBoard) return;
    orchRunClient
      .listSessionRuns(currentSessionId)
      .then((resp) => {
        if (cancelled) return;
        const run = resp.runs[0];
        if (!run) return;
        const restored = restoreRunToBoard(run);
        if (!restored) return;
        const board: TaskBoardState = {
          runId: run.run_id,
          plan: restored.plan,
          statuses: restored.statuses,
          progress: restored.progress,
          dispatchedAt: restored.dispatchedAt,
          endedAt: restored.endedAt,
        };
        useChatStreamStore.getState().setTaskBoard(currentSessionId, board);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [currentSessionId]);

  const scrollToLatest = () => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    wasAtBottomRef.current = true;
    setShowJumpToLatest(false);
  };

  return {
    scrollRef,
    showJumpToLatest,
    scrollToLatest,
  };
}
