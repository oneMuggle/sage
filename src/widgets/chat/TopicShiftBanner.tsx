// src/widgets/chat/TopicShiftBanner.tsx
//
// Task 11 (2026-09-17): topic shift 横幅 — 后端 chat_stream_create 在
// detect_topic_shift 触发 advance_segment 时,经 SSE 推送
// `state: 'topic_shifted'` 事件;本组件展示 "已自动隔离旧上下文" 提示
// 并提供"恢复完整上下文"入口(回退到上一个 segment,merge 上下文)。
//
// 设计要点:
// - 10s 自动消失 + 用户手动关闭 (×);后端 SSE 不会再次推送同类事件
//   (每次 advance_segment 只触发一次,无重试机制),所以这里由前端
//   useState 持有可见性,组件卸载即消失,不污染 store。
// - "恢复完整上下文" 调 sessionApi.retreatSegment → 后端
//   /sessions/{id}/segments/retreat → MessageRepository.retreat_segment
//   删除最后一个 topic_separator;onRetreat 由 Chat.tsx 传入,负责
//   重新拉取消息列表(loadMessages),让 UI 反映合并后的完整上下文。
// - 与 InterruptedRunBanner 同处一栏,样式不争抢空间;横幅栏只有
//   一行,所有交互按钮 shrink-0 防止窄屏挤压文字。

import { useEffect, useState } from 'react';

import { sessionApi } from '../../shared/api/sessionApi';

interface TopicShiftBannerProps {
  sessionId: string;
  reason: string;
  onRetreat: () => void;
}

const AUTO_DISMISS_MS = 10_000;

export function TopicShiftBanner({ sessionId, reason, onRetreat }: TopicShiftBannerProps) {
  const [visible, setVisible] = useState(true);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setVisible(false), AUTO_DISMISS_MS);
    return () => clearTimeout(t);
  }, []);

  if (!visible) return null;

  const handleRetreat = async () => {
    if (pending) return;
    setPending(true);
    try {
      await sessionApi.retreatSegment(sessionId);
      onRetreat();
    } catch {
      // 失败时保留横幅让用户重试;不在此处弹出 toast,避免打断主流程
    } finally {
      setPending(false);
      setVisible(false);
    }
  };

  return (
    <div
      data-testid="topic-shift-banner"
      className="flex items-center gap-2 px-5 py-2 bg-info/10 border-b border-border text-xs shrink-0"
    >
      <span className="text-info shrink-0">
        检测到新话题，已自动隔离旧上下文
        {reason ? `（${reason}）` : ''}
      </span>
      <button
        onClick={handleRetreat}
        disabled={pending}
        data-testid="topic-shift-retreat"
        className="px-2 py-0.5 border border-border rounded-radius-sm hover:bg-bg-hover transition-colors disabled:opacity-50"
      >
        {pending ? '恢复中…' : '恢复完整上下文'}
      </button>
      <button
        className="ml-auto text-text-secondary hover:text-text shrink-0"
        aria-label="忽略话题切换提示"
        data-testid="topic-shift-dismiss"
        onClick={() => setVisible(false)}
      >
        ×
      </button>
    </div>
  );
}
