/**
 * 聊天附件 PDF 原文预览（2026-11-15）。
 *
 * 附件卡片 / 引用页码点击后打开：经 IPC 取媒体 blob（Electron 下 <iframe>
 * 无法携带 local-auth Bearer 头），交给 Chromium 内置 PDF 阅读器；
 * 带页码时用 `#page=N` 直接定位。
 */

import { X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';

import { fetchMediaBlobUrl, revokeMediaBlobUrl } from '../../shared/api/mediaApi';
import { useI18n } from '../../shared/lib/i18n';

interface MediaPdfPreviewProps {
  mediaId: string;
  filename: string;
  /** 1 起始页码；不传则打开第一页 */
  page?: number;
  onClose: () => void;
}

export function MediaPdfPreview({ mediaId, filename, page, onClose }: MediaPdfPreviewProps) {
  const { t } = useI18n();
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let created: string | null = null;
    setBlobUrl(null);
    setFailed(false);
    fetchMediaBlobUrl(mediaId, 'application/pdf')
      .then((url) => {
        if (cancelled) {
          revokeMediaBlobUrl(url);
          return;
        }
        created = url;
        setBlobUrl(url);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
      if (created) revokeMediaBlobUrl(created);
    };
  }, [mediaId]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  const pageLabel = page
    ? ` · ${t('chat.attachment_status.pages').replace('{n}', String(page))}`
    : '';

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={filename}
      data-testid="media-pdf-preview"
      onClick={onClose}
    >
      <div
        className="flex h-[88vh] w-[92vw] max-w-6xl flex-col overflow-hidden rounded-lg border border-border bg-surface shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
          <span className="truncate text-ui-sm font-medium" title={filename}>
            {filename}
            {pageLabel}
          </span>
          <button
            type="button"
            data-testid="media-pdf-preview-close"
            aria-label={t('chat.attachment_status.preview_close')}
            onClick={onClose}
            className="shrink-0 rounded p-1 text-muted hover:bg-bg-hover hover:text-text transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 bg-bg-subtle">
          {failed ? (
            <div className="flex h-full items-center justify-center text-ui-sm text-muted">
              {t('chat.attachment_status.preview_failed')}
            </div>
          ) : blobUrl ? (
            <iframe
              data-testid="media-pdf-iframe"
              title={filename}
              src={page ? `${blobUrl}#page=${page}` : blobUrl}
              className="h-full w-full border-0"
            />
          ) : (
            <div className="flex h-full items-center justify-center text-ui-sm text-muted">
              {t('chat.attachment_status.preview_loading')}
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
