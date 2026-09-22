import { BookOpen, ChevronDown, X, Loader2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';

import { useBtwState } from '../../entities/chat/btwState';
import { useI18n } from '../../shared/lib/i18n';

import { useBtwCommand } from './useBtwCommand';

/**
 * /btw 补充消息浮动面板
 *
 * 显示 /btw 命令触发的问题和流式响应
 * 支持点击关闭按钮和 Escape 键关闭
 * R92: 答案下方展示统一参考来源（sources_used，紧凑列表可折叠）
 */
export function BtwOverlay() {
  const { t } = useI18n();
  const { close } = useBtwCommand();
  const { isOpen, question, answer, isLoading, sources } = useBtwState();
  const [sourcesExpanded, setSourcesExpanded] = useState(false);

  // Escape 键关闭
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        close();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, close]);

  // 不显示时不渲染
  if (!isOpen) {
    return null;
  }

  const kindLabel = (kind: string | undefined) =>
    kind === 'wiki'
      ? t('chat.sources_group_wiki')
      : kind === 'memory'
        ? t('chat.sources_group_memory')
        : kind === 'tool'
          ? t('chat.sources_group_tool')
          : t('chat.sources_group_web');

  return (
    <div
      data-testid="btw-overlay"
      className="fixed bottom-4 right-4 w-96 bg-surface border border-border rounded-lg shadow-lg z-50"
      style={{ maxHeight: '60vh', display: 'flex', flexDirection: 'column' }}
    >
      {/* 头部 */}
      <div className="flex items-center justify-between p-3 border-b border-border">
        <span className="text-sm font-medium text-text">{t('chat.btw.title')}</span>
        <button
          data-testid="btw-close"
          onClick={close}
          className="w-6 h-6 flex items-center justify-center rounded hover:bg-bg-hover text-muted hover:text-text transition-colors"
          aria-label={t('chat.btw.close')}
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* 问题区域 */}
      <div className="p-3 border-b border-border bg-bg-subtle">
        <div className="text-xs text-muted mb-1">{t('chat.btw.question')}</div>
        <div className="text-sm text-text">{question}</div>
      </div>

      {/* 答案区域 */}
      <div className="flex-1 overflow-y-auto p-3" style={{ minHeight: '100px' }}>
        {isLoading && !answer && (
          <div data-testid="btw-loading" className="flex items-center gap-2 text-sm text-muted">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span>{t('chat.btw.loading')}</span>
          </div>
        )}
        {answer && (
          // P3: 答案走 markdown 渲染（与主聊天同一插件集；浮层用默认
          // components，保持轻量），替代纯文本 whitespace-pre-wrap
          <div
            data-testid="btw-answer"
            className="text-sm text-text [&_p]:mb-2 [&_p:last-child]:mb-0 [&_code]:px-1 [&_code]:py-0.5 [&_code]:bg-bg-subtle [&_code]:rounded [&_code]:text-xs [&_pre]:bg-bg-subtle [&_pre]:p-2 [&_pre]:rounded [&_pre]:overflow-x-auto [&_a]:text-primary [&_a]:underline [&_ul]:list-disc [&_ul]:ml-5 [&_ol]:list-decimal [&_ol]:ml-5"
          >
            <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
              {answer}
            </ReactMarkdown>
          </div>
        )}

        {/* R92: 统一参考来源（紧凑列表，类主聊天的来源区块但无分组） */}
        {sources.length > 0 && (
          <div className="mt-2 border-t border-border/50 pt-2" data-testid="btw-sources">
            <button
              type="button"
              onClick={() => setSourcesExpanded((v) => !v)}
              className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline"
              data-testid="btw-sources-toggle"
            >
              <BookOpen className="w-3 h-3" />
              {t('chat.sources_count').replace('{n}', String(sources.length))}
              <ChevronDown
                className={`w-3 h-3 transition-transform ${sourcesExpanded ? 'rotate-180' : ''}`}
              />
            </button>
            {sourcesExpanded && (
              <div className="mt-1 space-y-1 text-xs" data-testid="btw-sources-list">
                {sources.map((s, i) => (
                  <div key={`${s.url ?? s.path ?? s.title}-${i}`} className="space-y-0.5">
                    <div className="flex items-start gap-1.5">
                      <span className="px-1 rounded bg-primary/10 text-primary flex-shrink-0">
                        {kindLabel(s.kind)}
                      </span>
                      {s.url ? (
                        <a
                          href={s.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-primary hover:underline break-all"
                        >
                          {s.title || s.url}
                        </a>
                      ) : (
                        <span className="text-text-secondary break-all">
                          {s.title || s.path || s.preview}
                        </span>
                      )}
                    </div>
                    {s.snippet && (
                      <div className="pl-5 text-muted break-all line-clamp-2">{s.snippet}</div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
