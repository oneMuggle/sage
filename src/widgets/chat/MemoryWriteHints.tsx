// src/widgets/chat/MemoryWriteHints.tsx
//
// 对标 S2 (2026-09-13, docs/plans 竞品对标): 聊天内联"🧠 记住了"提示。
// 对标 ChatGPT "Memory updated" 徽章 —— 每轮流结束后拉取本会话新增的记忆
// 写入（GET /memory/recent-writes 游标增量），在消息区底部渲染可撤销的
// 小条；撤销走 POST /memory/undo-write（按台账 kind 路由到记忆层 / 画像库）。
//
// 设计约束:
// - 纯增强信息: 拉取失败静默；不阻塞、不 toast。
// - 流结束跳变检测复用 ContextMeter 的 streaming.messageId 非空→null 模式。
// - 记忆提取是后台异步的（流结束后才落库），所以流结束后做 3 次短退避轮询。
// - 切换会话时清空，并重置游标（游标是会话维度的）。

import { Brain, Undo2, X } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import {
  useChatStreamStore,
  selectSessionSlots,
} from '../../features/send-message/chatStreamStore';
import { memoryApi } from '../../shared/api';
import type { MemoryWriteRecord } from '../../shared/api/types';
import { useI18n } from '../../shared/lib/i18n';

/** 流结束后的轮询节奏（毫秒）：提取是异步的，需要给后台几秒落库时间 */
const POLL_DELAYS_MS = [1200, 3000, 6000] as const;
const MAX_VISIBLE = 3;

interface MemoryWriteHintsProps {
  sessionId: string | null;
}

export function MemoryWriteHints({ sessionId }: MemoryWriteHintsProps) {
  const { t } = useI18n();
  const [items, setItems] = useState<MemoryWriteRecord[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const cursorRef = useRef<number>(0);
  const timersRef = useRef<number[]>([]);
  const sessionRef = useRef<string | null>(sessionId);

  const streamingMessageId = useChatStreamStore(
    (s) => selectSessionSlots(s, sessionId).streaming?.messageId ?? null,
  );
  const prevStreamingIdRef = useRef<string | null>(null);

  const clearTimers = (): void => {
    for (const id of timersRef.current) window.clearTimeout(id);
    timersRef.current = [];
  };

  const pull = useCallback(async (sid: string): Promise<void> => {
    const res = await memoryApi.getRecentWrites(sid, cursorRef.current, 10);
    // 会话已切换 → 丢弃迟到响应
    if (sessionRef.current !== sid) return;
    if (res.latest_seq > cursorRef.current) cursorRef.current = res.latest_seq;
    if (res.items.length === 0) return;
    setItems((prev) => {
      const seen = new Set(prev.map((p) => p.id));
      const merged = [...prev, ...res.items.filter((i) => !seen.has(i.id))];
      return merged.slice(-MAX_VISIBLE);
    });
  }, []);

  // 会话切换: 清空可见项 + 把游标推进到"现在"（历史写入不再弹出）
  useEffect(() => {
    sessionRef.current = sessionId;
    clearTimers();
    setItems([]);
    cursorRef.current = 0;
    if (!sessionId) return;
    void memoryApi.getRecentWrites(sessionId, 0, 1).then((res) => {
      if (sessionRef.current === sessionId) cursorRef.current = res.latest_seq;
    });
    return clearTimers;
  }, [sessionId]);

  // 流结束跳变 → 退避轮询增量
  useEffect(() => {
    const prev = prevStreamingIdRef.current;
    prevStreamingIdRef.current = streamingMessageId;
    if (prev !== null && streamingMessageId === null && sessionId) {
      clearTimers();
      for (const delay of POLL_DELAYS_MS) {
        timersRef.current.push(
          window.setTimeout(() => {
            void pull(sessionId);
          }, delay),
        );
      }
    }
  }, [streamingMessageId, sessionId, pull]);

  const dismiss = (id: string): void => {
    setItems((prev) => prev.filter((i) => i.id !== id));
  };

  const undo = async (rec: MemoryWriteRecord): Promise<void> => {
    if (!sessionId || busyId) return;
    setBusyId(rec.id);
    try {
      await memoryApi.undoWrite(sessionId, rec.id);
      dismiss(rec.id);
    } catch {
      // 404 = 已被删除，也算撤销成功；其它错误保留条目让用户重试
      dismiss(rec.id);
    } finally {
      setBusyId(null);
    }
  };

  if (!sessionId || items.length === 0) return null;

  return (
    <div className="px-4 pb-2 flex flex-col gap-1" data-testid="memory-write-hints">
      {items.map((rec) => (
        <div
          key={rec.id}
          className="flex items-center gap-2 px-2.5 py-1.5 rounded border border-border bg-surface text-xs text-text-secondary"
          data-testid="memory-write-hint"
        >
          <Brain className="w-3.5 h-3.5 text-accent shrink-0" aria-hidden />
          <span className="shrink-0 font-medium text-text">
            {rec.kind === 'profile' ? t('chat.memory_saved_profile') : t('chat.memory_saved')}
          </span>
          <span className="min-w-0 truncate" title={rec.content}>
            {rec.content}
          </span>
          <span className="flex-1" />
          <button
            type="button"
            onClick={() => void undo(rec)}
            disabled={busyId === rec.id}
            className="flex items-center gap-1 px-1.5 py-0.5 rounded border border-border hover:bg-bg-hover disabled:opacity-50 shrink-0"
            data-testid="memory-write-undo"
          >
            <Undo2 className="w-3 h-3" aria-hidden />
            {t('chat.memory_undo')}
          </button>
          <button
            type="button"
            onClick={() => dismiss(rec.id)}
            className="p-0.5 rounded hover:bg-bg-hover shrink-0"
            aria-label={t('chat.memory_dismiss')}
          >
            <X className="w-3 h-3" aria-hidden />
          </button>
        </div>
      ))}
    </div>
  );
}
