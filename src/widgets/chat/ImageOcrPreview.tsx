/**
 * 聊天输入区「图片文字」预览（本地 OCR）。
 *
 * 仅在无视觉模型（或用户开启 prefer_local_for_images）时显示；结果只读，
 * 支持复制与重新识别。真正发送时后端会再次走 OCR（进程内按 sha256 命中缓存）。
 */

import { Copy, RefreshCw } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { ocrApi } from '../../shared/api/ocrApi';
import { useI18n } from '../../shared/lib/i18n';

interface PreviewImage {
  name: string;
  dataUrl?: string;
}

interface PreviewItem {
  key: string;
  name: string;
  status: 'loading' | 'ok' | 'empty' | 'failed';
  text?: string;
  engine?: string;
  quality?: string;
  error?: string;
}

export function ImageOcrPreview({
  images,
  enabled,
  onTextsChange,
}: {
  images: PreviewImage[];
  enabled: boolean;
  onTextsChange?: (entries: { dataUrl: string; text: string }[]) => void;
}) {
  const { t } = useI18n();
  const signature = images.map((img) => img.dataUrl ?? '').join('|');
  const targets = useMemo(
    () =>
      images
        .filter((img) => Boolean(img.dataUrl))
        .map((img) => ({ name: img.name, dataUrl: img.dataUrl as string })),
    // signature 是 images 中 dataUrl 的稳定摘要，避免数组身份变化触发重复 OCR
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [signature],
  );
  const [items, setItems] = useState<PreviewItem[]>([]);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!enabled || targets.length === 0) {
      setItems([]);
      return;
    }
    let cancelled = false;
    setItems(
      targets.map((img, index) => ({
        key: `${index}-${img.name}`,
        name: img.name,
        status: 'loading',
      })),
    );
    (async () => {
      for (let index = 0; index < targets.length; index += 1) {
        const target = targets[index];
        try {
          const result = await ocrApi.recognize(target.dataUrl);
          if (cancelled) return;
          const text = (result.text || '').trim();
          setItems((prev) =>
            prev.map((item, idx) =>
              idx === index
                ? {
                    ...item,
                    status: text ? 'ok' : 'empty',
                    text,
                    engine: result.engine,
                    quality: result.quality,
                  }
                : item,
            ),
          );
        } catch (err) {
          if (cancelled) return;
          setItems((prev) =>
            prev.map((item, idx) =>
              idx === index
                ? {
                    ...item,
                    status: 'failed',
                    error: err instanceof Error ? err.message : String(err),
                  }
                : item,
            ),
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [enabled, targets, reloadKey]);

  useEffect(() => {
    if (!onTextsChange) return;
    onTextsChange(
      targets.map((target, index) => ({
        dataUrl: target.dataUrl,
        text: items[index]?.text ?? '',
      })),
    );
  }, [items, targets, onTextsChange]);

  if (!enabled || items.length === 0) return null;

  const updateText = (index: number, value: string) => {
    setItems((prev) =>
      prev.map((item, idx) =>
        idx === index ? { ...item, text: value, status: value.trim() ? 'ok' : 'empty' } : item,
      ),
    );
  };

  const copy = async (index: number, text: string) => {
    try {
      await navigator.clipboard?.writeText(text);
      setCopiedIndex(index);
      window.setTimeout(() => setCopiedIndex(null), 1500);
    } catch {
      // 剪贴板不可用时静默；用户仍可手动选择文本
    }
  };

  return (
    <div
      data-testid="chat-image-ocr-preview"
      className="mx-3 mb-1 rounded-md border border-border bg-bg-subtle p-2 text-xs"
    >
      <div className="mb-1 font-medium text-text">{t('chat.image_ocr_title')}</div>
      <div className="mb-1 text-muted">{t('chat.image_ocr_edit_hint')}</div>
      {items.map((item, index) => (
        <div key={item.key} className="mb-1 last:mb-0">
          <div className="flex items-center gap-2 text-muted">
            <span className="flex-1 truncate">{item.name}</span>
            {item.engine && <span>{item.engine}</span>}
            {item.status === 'ok' && item.text && (
              <button
                type="button"
                onClick={() => copy(index, item.text as string)}
                className="inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5 hover:bg-bg-hover"
              >
                <Copy className="h-3 w-3" aria-hidden="true" />
                {copiedIndex === index ? t('chat.image_ocr_copied') : t('chat.image_ocr_copy')}
              </button>
            )}
            <button
              type="button"
              aria-label={t('chat.image_ocr_retry')}
              onClick={() => setReloadKey((value) => value + 1)}
              className="inline-flex items-center rounded border border-border p-0.5 hover:bg-bg-hover"
            >
              <RefreshCw className="h-3 w-3" aria-hidden="true" />
            </button>
          </div>
          {item.status === 'loading' && (
            <div className="text-muted">{t('chat.image_ocr_loading')}</div>
          )}
          {item.status === 'empty' && <div className="text-muted">{t('chat.image_ocr_empty')}</div>}
          {item.status === 'failed' && (
            <div className="text-warning">
              {t('chat.image_ocr_failed').replace('{error}', item.error ?? '')}
            </div>
          )}
          {item.status === 'ok' && item.text && (
            <textarea
              value={item.text}
              onChange={(event) => updateText(index, event.target.value)}
              rows={Math.min(8, Math.max(2, item.text.split('\n').length))}
              className="mt-1 w-full resize-y rounded border border-border bg-surface p-1 font-sans text-xs text-text"
            />
          )}
        </div>
      ))}
    </div>
  );
}
