import { X, Loader2 } from 'lucide-react';
import { useEffect } from 'react';

import { useBtwState } from '../../entities/chat/btwState';
import { useI18n } from '../../shared/lib/i18n';

import { useBtwCommand } from './useBtwCommand';

/**
 * /btw 补充消息浮动面板
 *
 * 显示 /btw 命令触发的问题和流式响应
 * 支持点击关闭按钮和 Escape 键关闭
 */
export function BtwOverlay() {
  const { t } = useI18n();
  const { close } = useBtwCommand();
  const { isOpen, question, answer, isLoading } = useBtwState();

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

  return (
    <div
      data-testid="btw-overlay"
      className="fixed bottom-4 right-4 w-96 bg-surface border border-border rounded-lg shadow-lg z-50"
      style={{ maxHeight: '60vh', display: 'flex', flexDirection: 'column' }}
    >
      {/* 头部 */}
      <div className="flex items-center justify-between p-3 border-b border-border">
        <span className="text-sm font-medium text-text">
          {t('chat.btw.title')}
        </span>
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
          <div
            data-testid="btw-loading"
            className="flex items-center gap-2 text-sm text-muted"
          >
            <Loader2 className="w-4 h-4 animate-spin" />
            <span>{t('chat.btw.loading')}</span>
          </div>
        )}
        {answer && (
          <div className="text-sm text-text whitespace-pre-wrap">{answer}</div>
        )}
      </div>
    </div>
  );
}
