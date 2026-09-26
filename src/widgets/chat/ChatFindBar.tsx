// 对话阅读体验 B4（docs/mcp-chat-reading-nav-optimization.md §10.3 / §10.4）：会话内查找栏。
//
// Layout 在 Ctrl/Cmd+F 时派发可取消的 CHAT_FIND_EVENT；本组件挂载时（聊天页有消息）
// 接管并 preventDefault()，否则 Layout 回落为聚焦侧栏会话搜索。
// 命中按消息顺序排列：打开时停在最新（最靠下）的命中，Enter 跳到更早的命中，
// Shift+Enter 跳到更新的命中。定位复用 A1 通道（requestMessageJump 携带
// highlightQuery / highlightIndex），尾窗外的消息会自动扩窗。
import { ChevronDown, ChevronUp, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';

import {
  buildFindMatches,
  CHAT_FIND_EVENT,
  type FindableMessage,
} from '../../features/chat/chatFind';
import { requestMessageJump } from '../../features/chat/messageJumpStore';
import { clearFindHighlights } from '../../features/chat/textHighlight';
import { useI18n } from '../../shared/lib/i18n';

/** 输入防抖：长会话里逐字重算命中列表没有必要 */
const FIND_DEBOUNCE_MS = 150;

const ICON_BUTTON =
  'p-1 rounded hover:bg-bg-hover disabled:opacity-40 disabled:hover:bg-transparent';

interface ChatFindBarProps {
  messages: ReadonlyArray<FindableMessage>;
}

/** 常驻外壳：只监听打开事件；关闭时不渲染任何内容 */
export function ChatFindBar({ messages }: ChatFindBarProps) {
  // 0 = 关闭；每次 Ctrl+F 递增，已打开时用于重新聚焦输入框
  const [openNonce, setOpenNonce] = useState(0);

  useEffect(() => {
    const onOpen = (event: Event) => {
      event.preventDefault();
      setOpenNonce((n) => n + 1);
    };
    window.addEventListener(CHAT_FIND_EVENT, onOpen);
    return () => window.removeEventListener(CHAT_FIND_EVENT, onOpen);
  }, []);

  const close = useCallback(() => setOpenNonce(0), []);

  if (openNonce === 0) return null;
  return <ChatFindPanel messages={messages} focusNonce={openNonce} onClose={close} />;
}

interface ChatFindPanelProps extends ChatFindBarProps {
  focusNonce: number;
  onClose: () => void;
}

function ChatFindPanel({ messages, focusNonce, onClose }: ChatFindPanelProps) {
  const { t } = useI18n();
  const [input, setInput] = useState('');
  const [query, setQuery] = useState('');
  const [current, setCurrent] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);

  // 打开或再次 Ctrl+F：聚焦并全选，方便直接输入新的查找词
  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [focusNonce]);

  useEffect(() => {
    const timer = setTimeout(() => setQuery(input.trim()), FIND_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [input]);

  const matches = useMemo(
    () => (query ? buildFindMatches(messages, query) : []),
    [query, messages],
  );
  // 只在查找词变化或用户翻页时跳转 —— 流式输出会不断换新 messages，不能因此
  // 把视图拉走。跳转时经 ref 读取最新的命中列表与查找词。
  const matchesRef = useRef(matches);
  matchesRef.current = matches;
  const queryRef = useRef(query);
  queryRef.current = query;

  const goTo = useCallback((index: number) => {
    const list = matchesRef.current;
    if (list.length === 0) {
      setCurrent(-1);
      clearFindHighlights();
      return;
    }
    const next = ((index % list.length) + list.length) % list.length;
    setCurrent(next);
    const { messageId, occurrence } = list[next];
    requestMessageJump({ messageId, highlightQuery: queryRef.current, highlightIndex: occurrence });
  }, []);

  // 查找词变化：停在最新（最靠下）的命中
  useEffect(() => {
    goTo(matchesRef.current.length - 1);
  }, [query, goTo]);

  // 命中变少（切换会话、删除消息）时把当前序号收回范围内
  useEffect(() => {
    if (current >= matches.length) setCurrent(matches.length - 1);
  }, [current, matches.length]);

  // 关闭或离开聊天页（卸载）时清掉残留高亮
  useEffect(() => () => clearFindHighlights(), []);

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    // 输入法组词中的 Enter / Esc 属于输入法，不当作查找操作
    if (event.nativeEvent.isComposing) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      onClose();
    } else if (event.key === 'Enter') {
      event.preventDefault();
      const typed = input.trim();
      // 防抖尚未生效时先提交查找词（随后自动停在最新命中）
      if (typed !== query) setQuery(typed);
      else goTo(event.shiftKey ? current + 1 : current - 1);
    }
  };

  const noMatches = matches.length === 0;
  const status = !noMatches
    ? `${current + 1}/${matches.length}`
    : query
      ? t('chat.find_no_results')
      : '';

  return (
    <div className="sticky top-0 z-20 h-0">
      <div
        role="search"
        aria-label={t('chat.find_label')}
        data-testid="chat-find-bar"
        className="absolute right-4 top-2 flex items-center gap-1 pl-2 pr-1 py-1 rounded-radius-sm border border-border bg-surface shadow-md"
      >
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={t('chat.find_placeholder')}
          title={t('chat.find_hint')}
          aria-label={t('chat.find_placeholder')}
          data-testid="chat-find-input"
          className="w-48 bg-transparent text-xs outline-none placeholder:text-muted"
        />
        <span
          className="min-w-[3rem] text-right text-[11px] text-muted tabular-nums"
          aria-live="polite"
          data-testid="chat-find-count"
        >
          {status}
        </span>
        <button
          type="button"
          onClick={() => goTo(current - 1)}
          disabled={noMatches}
          className={ICON_BUTTON}
          title={`${t('chat.find_prev')} · Enter`}
          aria-label={t('chat.find_prev')}
          data-testid="chat-find-prev"
        >
          <ChevronUp className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          onClick={() => goTo(current + 1)}
          disabled={noMatches}
          className={ICON_BUTTON}
          title={`${t('chat.find_next')} · Shift+Enter`}
          aria-label={t('chat.find_next')}
          data-testid="chat-find-next"
        >
          <ChevronDown className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          onClick={onClose}
          className={ICON_BUTTON}
          title={`${t('chat.find_close')} · Esc`}
          aria-label={t('chat.find_close')}
          data-testid="chat-find-close"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}
