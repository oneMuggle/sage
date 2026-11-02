/**
 * TOC 大纲组件 —— 监听 heading 滚动位置，高亮当前活跃项，点击跳转。
 *
 * 设计取舍：
 * - IntersectionObserver 监听 `[id^="${prefix}-"]` 的 h* 元素。
 * - activeId 由父组件通过 `onActiveChange` 接收（宿主可联动状态 / URL hash）。
 * - 点击用 `element.scrollIntoView({ block: 'start' })` 而非 hash change ——
 *   避免污染 URL，且能精确停靠到 heading 顶（容器 scrollTop 协调留给宿主）。
 * - 缩进用 CSS padding-left 实现，不依赖 Tailwind 类。
 */

import { useEffect, useRef, useState } from 'react';

import type { TocEntry } from './outline';
import { useMdI18n } from './useMdI18n';
import './outline.css';

export interface MarkdownOutlineProps {
  /** TOC 条目（来自 buildMarkdownOutline） */
  entries: TocEntry[];
  /** 锚点 id 前缀（与 Markdown 组件的 headingAnchorPrefix 一致） */
  prefix?: string;
  /** 当前活跃 heading id（外部联动） */
  activeId?: string;
  /** 活跃项变化回调（IntersectionObserver 驱动） */
  onActiveChange?: (id: string) => void;
  /** 滚动容器 —— observer 的 root；默认 document */
  scrollContainerRef?: React.RefObject<HTMLElement>;
  /** 是否自动启动 IntersectionObserver（默认 true） */
  observe?: boolean;
}

/**
 * TOC 大纲 UI —— 缩进列表，activeId 高亮。
 */
export function MarkdownOutline({
  entries,
  prefix = 'md',
  activeId: controlledActiveId,
  onActiveChange,
  scrollContainerRef,
  observe = true,
}: MarkdownOutlineProps) {
  const t = useMdI18n();
  const [internalActiveId, setInternalActiveId] = useState<string | undefined>();
  const activeId = controlledActiveId ?? internalActiveId;
  const observerRef = useRef<IntersectionObserver | null>(null);

  useEffect(() => {
    if (!observe || typeof document === 'undefined') return;
    const root = scrollContainerRef?.current ?? document.documentElement;
    const selector = `[id^="${prefix}-"]`;
    const elements = Array.from(root.querySelectorAll(selector)).filter(
      (el) => el.tagName.match(/^H[1-6]$/),
    );
    if (elements.length === 0) return;

    const observer = new IntersectionObserver(
      (intersections) => {
        // 找最高位可见的 heading（threshold 0.01 = 稍微进入视口即算可见）
        const visible = intersections
          .filter((i) => i.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) {
          const id = (visible[0].target as HTMLElement).id;
          setInternalActiveId(id);
          onActiveChange?.(id);
        }
      },
      {
        root: scrollContainerRef?.current ?? null,
        rootMargin: '0px 0px -70% 0px',
        threshold: [0, 0.01, 0.1],
      },
    );

    elements.forEach((el) => observer.observe(el));
    observerRef.current = observer;
    return () => observer.disconnect();
  }, [entries, prefix, observe, scrollContainerRef, onActiveChange]);

  if (entries.length === 0) {
    return (
      <nav className="md-outline" aria-label={t('md.outline.title')}>
        <div className="md-outline-empty">{t('md.outline.empty')}</div>
      </nav>
    );
  }

  const handleClick = (id: string) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.scrollIntoView({ block: 'start', behavior: 'smooth' });
    setInternalActiveId(id);
    onActiveChange?.(id);
  };

  return (
    <nav className="md-outline" aria-label={t('md.outline.title')}>
      <ol className="md-outline-list">
        {entries.map((entry) => (
          <li
            key={entry.id}
            className="md-outline-item"
            data-depth={entry.depth}
            data-active={entry.id === activeId ? '' : undefined}
          >
            <button
              type="button"
              className="md-outline-link"
              onClick={() => handleClick(entry.id)}
              title={entry.text}
            >
              {entry.text}
            </button>
          </li>
        ))}
      </ol>
    </nav>
  );
}
