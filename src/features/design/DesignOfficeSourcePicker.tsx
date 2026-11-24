/**
 * DesignOfficeSourcePicker — 从 Office 文档库选设计素材。
 *
 * Design Studio 原先只能经 Electron 文件选择器引用本地文件，Web 模式
 * 下没有该能力。这里列出后端 workspace 里已入库的 Word / Excel 文档，
 * 以 doc_id 形式引用；路径解析与 workspace 校验都在服务端完成。
 */
import { FileSpreadsheet, FileText, Loader2, RefreshCw, X } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { listOfficeSources } from '../../entities/design/designApi';
import type { OfficeSourceRef } from '../../entities/design/types';
import { useI18n } from '../../shared/lib/i18n';

export type OfficeSourceDocType = 'word' | 'excel';

interface DesignOfficeSourcePickerProps {
  docType: OfficeSourceDocType;
  onSelect: (source: OfficeSourceRef) => void;
  onClose: () => void;
}

export function DesignOfficeSourcePicker({
  docType,
  onSelect,
  onClose,
}: DesignOfficeSourcePickerProps) {
  const { t } = useI18n();
  const [items, setItems] = useState<OfficeSourceRef[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await listOfficeSources(docType));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [docType]);

  useEffect(() => {
    void load();
  }, [load]);

  const Icon = docType === 'word' ? FileText : FileSpreadsheet;

  return (
    <div className="space-y-2 rounded-md border border-border bg-surface p-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1 text-text">
          <Icon className="h-3 w-3" />
          {t('design.officePicker.title')}
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            aria-label={t('design.officePicker.refresh')}
            className="rounded border border-border p-1 hover:bg-bg-hover disabled:opacity-40"
            disabled={loading}
            onClick={() => void load()}
          >
            <RefreshCw className="h-3 w-3" />
          </button>
          <button
            type="button"
            aria-label={t('design.officePicker.close')}
            className="rounded border border-border p-1 hover:bg-bg-hover"
            onClick={onClose}
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      </div>

      {loading && (
        <div className="flex items-center gap-1 py-2 text-text-muted">
          <Loader2 className="h-3 w-3 animate-spin" />
          {t('design.officePicker.loading')}
        </div>
      )}

      {!loading && error && (
        <div className="py-2 text-text-muted">
          {t('design.officePicker.failed').replace('{error}', error)}
        </div>
      )}

      {!loading && !error && items.length === 0 && (
        <div className="py-2 text-text-muted">{t('design.officePicker.empty')}</div>
      )}

      {!loading && !error && items.length > 0 && (
        <ul className="max-h-60 space-y-1 overflow-y-auto">
          {items.map((item) => (
            <li key={item.doc_id}>
              <button
                type="button"
                className="w-full truncate rounded border border-border px-2 py-1 text-left hover:bg-bg-hover"
                onClick={() => onSelect(item)}
              >
                {item.original_filename || item.generated_filename}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
