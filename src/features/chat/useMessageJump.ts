// src/features/chat/useMessageJump.ts
//
// 对话阅读导航 A1：MessageList 侧的定位消费逻辑。
//
// 流程：目标消息出现在 messages 中 → 若在尾窗之外，先把渲染窗口扩到能覆盖它
// → 下一帧（让 Chat 页的粘底滚动 effect 先跑完）滚动到视口中部 → 同步派发
// 一次 scroll 事件，使粘底状态立即变为"不在底部"（否则后续流式 token 会把
// 视图拉回底部）→ 高亮 1.6s → 消费请求并把窗口固化为扩大后的大小。
//
// 第二轮 B3 / B4：请求带 highlightQuery 时，定位后用 CSS Custom Highlight API 高亮
// 检索词，并优先把（当前）命中滚到视口中部（见 textHighlight.ts）。

import { useEffect, useState, type RefObject } from 'react';

import { useMessageJumpStore } from './messageJumpStore';
import { highlightFindMatches, highlightSearchHits, scrollRangeIntoView } from './textHighlight';

/** 定位后高亮持续时间 */
export const JUMP_FLASH_MS = 1600;

/** 标题比较用的归一化：去掉链接/图片/行内代码/强调标记与结尾的 # 序列 */
export function normalizeHeadingText(text: string): string {
  return text
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/<[^>]+>/g, '')
    .replace(/[`*_~]/g, '')
    .replace(/\s+#+\s*$/, '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

/** 在消息元素内找大纲条目对应的 h2/h3：先按文本匹配，再按序号兜底 */
export function findHeadingElement(
  root: Element,
  headingText?: string,
  headingIndex?: number,
): HTMLElement | null {
  const headings = Array.from(root.querySelectorAll<HTMLElement>('h2, h3'));
  if (headingText) {
    const want = normalizeHeadingText(headingText);
    const hit = headings.find((h) => normalizeHeadingText(h.textContent ?? '') === want);
    if (hit) return hit;
  }
  if (headingIndex != null && headingIndex >= 0 && headingIndex < headings.length) {
    return headings[headingIndex];
  }
  return null;
}

/** 最近的纵向可滚动祖先（Chat 页的消息滚动容器） */
export function findScrollParent(el: Element): HTMLElement | null {
  let node = el.parentElement;
  while (node) {
    const { overflowY } = window.getComputedStyle(node);
    if (overflowY === 'auto' || overflowY === 'scroll') return node;
    node = node.parentElement;
  }
  return null;
}

function escapeAttr(value: string): string {
  return typeof CSS !== 'undefined' && typeof CSS.escape === 'function'
    ? CSS.escape(value)
    : value.replace(/["\\]/g, '\\$&');
}

interface UseMessageJumpOptions {
  /** MessageList 的根节点（消息元素带 data-message-id） */
  rootRef: RefObject<HTMLElement>;
  messages: ReadonlyArray<{ id: string }>;
  windowSize: number;
  setWindowSize: (updater: (prev: number) => number) => void;
}

export function useMessageJump({
  rootRef,
  messages,
  windowSize,
  setWindowSize,
}: UseMessageJumpOptions): { effectiveWindow: number; flashId: string | null } {
  const pending = useMessageJumpStore((s) => s.pending);
  // 本列表已处理过的请求 nonce。"已处理"与扩窗、高亮在同一批 React 状态里提交；
  // 全局请求随后才清掉 —— 若先清请求（zustand 同步渲染）再扩窗，目标消息会先被
  // 尾窗裁掉再重新挂载，滚动位置随之错乱。
  const [handledNonce, setHandledNonce] = useState<number | null>(null);
  const [flash, setFlash] = useState<{ id: string; nonce: number } | null>(null);

  const active = pending && pending.nonce !== handledNonce ? pending : null;
  const targetIndex = active ? messages.findIndex((m) => m.id === active.messageId) : -1;
  const required = targetIndex >= 0 ? messages.length - targetIndex : 0;
  const effectiveWindow = Math.max(windowSize, required);

  useEffect(() => {
    if (!active || targetIndex < 0) return;
    const { nonce, messageId, headingText, headingIndex, highlightQuery, highlightIndex } = active;
    const frame = requestAnimationFrame(() => {
      const root = rootRef.current;
      const el = root?.querySelector<HTMLElement>(`[data-message-id="${escapeAttr(messageId)}"]`);
      // 目标尚未挂载：保留请求，等下一次渲染或 TTL 过期
      if (!root || !el) return;
      const target =
        headingText || headingIndex != null
          ? (findHeadingElement(el, headingText, headingIndex) ?? el)
          : el;
      const scroller = findScrollParent(el);
      const findMode = highlightIndex != null;
      let hit: Range | null = null;
      if (highlightQuery) {
        hit = findMode
          ? highlightFindMatches(root, el, highlightQuery, highlightIndex)
          : highlightSearchHits(el, highlightQuery);
      }
      if (!hit || !scrollRangeIntoView(hit, scroller)) {
        if (typeof target.scrollIntoView === 'function') {
          target.scrollIntoView({ block: 'center' });
        }
      }
      scroller?.dispatchEvent(new Event('scroll'));
      setWindowSize((prev) => Math.max(prev, required));
      // 会话内查找逐条翻页时只突出当前命中，不再闪烁整条消息
      if (!findMode) setFlash({ id: messageId, nonce });
      setHandledNonce(nonce);
    });
    return () => cancelAnimationFrame(frame);
  }, [active, targetIndex, required, rootRef, setWindowSize]);

  useEffect(() => {
    if (handledNonce != null) useMessageJumpStore.getState().consume(handledNonce);
  }, [handledNonce]);

  useEffect(() => {
    if (!flash) return;
    const timer = setTimeout(() => setFlash(null), JUMP_FLASH_MS);
    return () => clearTimeout(timer);
  }, [flash]);

  return { effectiveWindow, flashId: flash?.id ?? null };
}
