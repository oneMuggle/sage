// src/widgets/chat/SelectionQuoteButton.tsx
//
// 对话阅读导航 A4：划词引用浮动按钮（对标 ChatGPT 的"选中 → Ask ChatGPT"）。
//
// - 只在鼠标抬起 / 键盘选择结束时评估选区（拖选过程中不跟随鼠标闪烁）；
// - 选区消失、滚动、窗口缩放、Esc 时隐藏；
// - 按钮 mousedown 阻止默认行为，点击时选区不会先被清掉；
// - portal 到 body，避免被消息列表的滚动容器 / transform 祖先裁剪。

import { Quote } from 'lucide-react';
import { useEffect, useState, type RefObject } from 'react';
import { createPortal } from 'react-dom';

import {
  computeQuoteButtonPosition,
  getQuotableSelection,
} from '../../features/chat/selectionQuote';
import { useI18n } from '../../shared/lib/i18n';
import {
  CONTEXT_MENU_OPEN_EVENT,
  isContextMenuOpen,
} from '../../shared/ui/ContextMenu/contextMenuEvents';

interface SelectionQuoteButtonProps {
  /** 可引用区域所在的根节点（MessageList） */
  rootRef: RefObject<HTMLElement>;
  onQuote: (text: string) => void;
}

interface QuoteButtonState {
  text: string;
  top: number;
  left: number;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatSelectionQuoteButtonAuditSnapshot(opts: {
  active?: boolean;
  textLength?: number;
  top?: number;
  left?: number;
}): string {
  return `selectionQuote|active=${opts.active ? 1 : 0}|len=${opts.textLength ?? 0}|top=${opts.top ?? 0}|left=${opts.left ?? 0}`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatSelectionQuoteButtonAuditJson(opts: {
  active?: boolean;
  textLength?: number;
  top?: number;
  left?: number;
}): string {
  return JSON.stringify({
    active: Boolean(opts.active),
    textLength: opts.textLength ?? 0,
    top: opts.top ?? 0,
    left: opts.left ?? 0,
  });
}

export function SelectionQuoteButton({ rootRef, onQuote }: SelectionQuoteButtonProps) {
  const { t } = useI18n();
  const [state, setState] = useState<QuoteButtonState | null>(null);
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  useEffect(() => {
    let frame = 0;
    const evaluate = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        // 右键菜单打开时让位：菜单自带「引用选区」项，避免双浮层叠加
        if (isContextMenuOpen()) {
          setState(null);
          return;
        }
        const info = getQuotableSelection(window.getSelection(), rootRef.current);
        if (!info) {
          setState(null);
          return;
        }
        setState({ text: info.text, ...computeQuoteButtonPosition(info.rect, window.innerWidth) });
      });
    };
    const hide = () => setState(null);
    const onContextMenuOpen = () => setState(null);
    const onSelectionChange = () => {
      const selection = window.getSelection();
      if (!selection || selection.isCollapsed) hide();
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') hide();
    };
    document.addEventListener('mouseup', evaluate);
    document.addEventListener('keyup', evaluate);
    document.addEventListener('selectionchange', onSelectionChange);
    document.addEventListener('keydown', onKeyDown);
    window.addEventListener(CONTEXT_MENU_OPEN_EVENT, onContextMenuOpen);
    window.addEventListener('scroll', hide, true);
    window.addEventListener('resize', hide);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener('mouseup', evaluate);
      document.removeEventListener('keyup', evaluate);
      document.removeEventListener('selectionchange', onSelectionChange);
      document.removeEventListener('keydown', onKeyDown);
      window.removeEventListener(CONTEXT_MENU_OPEN_EVENT, onContextMenuOpen);
      window.removeEventListener('scroll', hide, true);
      window.removeEventListener('resize', hide);
    };
  }, [rootRef]);

  if (!state) return null;

  return createPortal(
    <>
      <button
        type="button"
        data-testid="selection-quote-button"
        title={t('chat.quote_selection_hint')}
        aria-label={t('chat.quote_selection_hint')}
        style={{
          position: 'fixed',
          top: state.top,
          left: state.left,
          transform: 'translateX(-50%)',
        }}
        className="z-50 inline-flex items-center gap-1 px-2 py-1 text-xs rounded-radius-sm border border-border bg-surface text-text shadow-md hover:bg-bg-hover"
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => {
          onQuote(state.text);
          window.getSelection()?.removeAllRanges();
          setState(null);
        }}
      >
        <Quote className="w-3 h-3" />
        {t('chat.quote_selection')}
      </button>
      <span
        data-testid="selection-quote-copy-snapshot"
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => {
          /* v8 ignore start */
          setCopiedSnapshot(true);
          void navigator.clipboard?.writeText(
            formatSelectionQuoteButtonAuditSnapshot({
              active: true,
              textLength: state.text.length,
              top: state.top,
              left: state.left,
            }),
          );
          /* v8 ignore stop */
        }}
      >
        {copiedSnapshot ? '已复制快照' : ''}
      </span>
      <span
        data-testid="selection-quote-copy-json"
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => {
          /* v8 ignore start */
          setCopiedJson(true);
          void navigator.clipboard?.writeText(
            formatSelectionQuoteButtonAuditJson({
              active: true,
              textLength: state.text.length,
              top: state.top,
              left: state.left,
            }),
          );
          /* v8 ignore stop */
        }}
      >
        {copiedJson ? '已复制JSON' : ''}
      </span>
    </>,
    document.body,
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditSelectionQuoteButtonGovernance(
  state: {
    selectionLength?: number;
    maxQuoteChars?: number;
  } = {},
): {
  module: 'src/widgets/chat/SelectionQuoteButton.tsx';
  phase: 'P150';
  selectionLength: number;
  maxQuoteChars: number;
  healthy: boolean;
} {
  const selectionLength =
    typeof state.selectionLength === 'number' && Number.isFinite(state.selectionLength)
      ? Math.max(0, Math.trunc(state.selectionLength))
      : 48;
  const maxQuoteChars =
    typeof state.maxQuoteChars === 'number' && Number.isFinite(state.maxQuoteChars)
      ? Math.max(100, Math.min(10000, Math.trunc(state.maxQuoteChars)))
      : 2000;
  return {
    module: 'src/widgets/chat/SelectionQuoteButton.tsx',
    phase: 'P150',
    selectionLength,
    maxQuoteChars,
    healthy: selectionLength > 0 && selectionLength <= maxQuoteChars,
  };
}
