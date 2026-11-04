/**
 * PDF 批处理 OCR 预览。
 *
 * 用户对输入区的 PDF 附件点击「识别 PDF 文字」后，前端把 PDF data URL 交给
 * `/api/v1/ocr/batch/pdf`，服务端逐页光栅化并复用 OCR 批处理队列；本组件
 * 轮询任务状态并展示每页文本，支持复制、重试与关闭。
 */

import { Copy, FileText, RefreshCw, X } from 'lucide-react';
import { useEffect, useState } from 'react';

import {
  ocrApi,
  type OcrBatchCaseResult,
  type OcrBatchStatus,
} from '../../shared/api/ocrApi';
import { copyToClipboard } from '../../shared/lib/clipboard';
import { useI18n } from '../../shared/lib/i18n';

export interface PdfOcrTarget {
  name: string;
  dataUrl: string;
}

interface PdfOcrPreviewProps {
  target: PdfOcrTarget | null;
  onClose: () => void;
}

const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled']);

export function PdfOcrPreview({ target, onClose }: PdfOcrPreviewProps) {
  const { t } = useI18n();
  const [status, setStatus] = useState<OcrBatchStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!target) {
      setStatus(null);
      setError(null);
      return;
    }

    let cancelled = false;
    let jobId: string | null = null;
    let finished = false;
    setStatus(null);
    setError(null);

    (async () => {
      try {
        const submitted = await ocrApi.batchPdf(target.dataUrl);
        if (cancelled) {
          void ocrApi.batchCancel(submitted.job_id).catch(() => undefined);
          return;
        }
        jobId = submitted.job_id;
        while (!cancelled) {
          const next = await ocrApi.batchStatus(jobId);
          if (cancelled) return;
          setStatus(next);
          if (TERMINAL_STATUSES.has(next.status)) {
            finished = true;
            return;
          }
          await new Promise((resolve) => {
            window.setTimeout(resolve, 300);
          });
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    })();

    return () => {
      cancelled = true;
      if (jobId && !finished) {
        void ocrApi.batchCancel(jobId).catch(() => undefined);
      }
    };
  }, [target, reloadKey]);

  if (!target) return null;

  const results = (status?.results ?? []).filter(
    (item): item is OcrBatchCaseResult => Boolean(item),
  );
  const done = status?.completed ?? 0;
  const total = status?.total ?? 0;
  const isTerminal = status ? TERMINAL_STATUSES.has(status.status) : false;

  const copy = (text: string) =>
    copyToClipboard(text, {
      successMessage: t('chat.pdf_ocr_copied'),
      errorMessage: t('contextMenu.common.copyFailed'),
    });

  return (
    <div
      data-testid="chat-pdf-ocr-preview"
      className="mx-3 mb-1 rounded-md border border-border bg-bg-subtle p-2 text-xs"
    >
      <div className="flex items-center gap-2">
        <FileText className="h-3.5 w-3.5 shrink-0 text-muted" aria-hidden="true" />
        <span className="flex-1 truncate text-text" title={target.name}>
          {target.name}
        </span>
        {status && (
          <span className="text-muted">
            {t('chat.pdf_ocr_progress')
              .replace('{done}', String(done))
              .replace('{total}', String(total))}
          </span>
        )}
        <button
          type="button"
          aria-label={t('chat.pdf_ocr_retry')}
          data-testid="pdf-ocr-retry"
          onClick={() => setReloadKey((value) => value + 1)}
          className="inline-flex items-center rounded border border-border p-0.5 hover:bg-bg-hover"
        >
          <RefreshCw className="h-3 w-3" aria-hidden="true" />
        </button>
        <button
          type="button"
          aria-label={t('chat.pdf_ocr_close')}
          data-testid="pdf-ocr-close"
          onClick={onClose}
          className="inline-flex items-center rounded border border-border p-0.5 hover:bg-bg-hover"
        >
          <X className="h-3 w-3" aria-hidden="true" />
        </button>
      </div>

      <div className="mt-1 max-h-64 space-y-2 overflow-auto">
        {error && (
          <div className="text-warning">
            {t('chat.pdf_ocr_failed').replace('{error}', error)}
          </div>
        )}
        {!error && !status && (
          <div className="text-muted">{t('chat.pdf_ocr_loading')}</div>
        )}
        {status?.status === 'failed' && (
          <div className="text-warning">
            {t('chat.pdf_ocr_failed').replace('{error}', status.error ?? '')}
          </div>
        )}
        {isTerminal && !error && results.length === 0 && status?.status !== 'failed' && (
          <div className="text-muted">{t('chat.pdf_ocr_empty')}</div>
        )}
        {results.map((item) => (
          <div key={item.index}>
            <div className="flex items-center gap-2 text-muted">
              <span className="flex-1">#{item.index + 1}</span>
              {item.text && (
                <button
                  type="button"
                  data-testid={`pdf-ocr-copy-${item.index}`}
                  onClick={() => copy(item.text)}
                  className="inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5 hover:bg-bg-hover"
                >
                  <Copy className="h-3 w-3" aria-hidden="true" />
                  {t('chat.pdf_ocr_copy')}
                </button>
              )}
            </div>
            {item.error ? (
              <div className="text-warning">
                {t('chat.pdf_ocr_failed').replace('{error}', item.error)}
              </div>
            ) : (
              <pre className="mt-0.5 whitespace-pre-wrap break-words font-sans text-text">
                {item.text || t('chat.pdf_ocr_empty')}
              </pre>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
