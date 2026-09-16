/**
 * PdfFormFillDialog — P2-D (office-p2d)。
 *
 * PDF AcroForm 表单填写：read-form 列出字段（名称/类型/必填/只读），
 * 用户填值后 fill-form 产出 `<stem>-filled.pdf`（落源文件旁，受管布局）。
 * 失败直接在对话框内展示后端错误（XFA 表单暂不支持填写，给明确文案）。
 */

import { useState } from 'react';
import { toast } from 'sonner';

import { officeApi } from '../../shared/api/officeApi';
import type { OfficePdfFormField } from '../../shared/api/types';
import { useI18n } from '../../shared/lib/i18n';

export interface PdfFormFillDialogProps {
  workspacePath: string;
  /** Managed path of the source PDF. */
  managedPath: string;
  /** Fired after a successful fill so the parent can refresh the list. */
  onFilled?: () => void;
  onClose: () => void;
}

export function PdfFormFillDialog({
  workspacePath,
  managedPath,
  onFilled,
  onClose,
}: PdfFormFillDialogProps) {
  const { t } = useI18n();
  const [fields, setFields] = useState<OfficePdfFormField[] | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [flatten, setFlatten] = useState(false);
  const [loading, setLoading] = useState(false);
  const [filling, setFilling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await officeApi.readPdfForm({
        workspace_path: workspacePath,
        file_path: managedPath,
      });
      setFields(res.fields);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleFill = async () => {
    if (filling) return;
    setFilling(true);
    try {
      const stem = managedPath.slice(managedPath.lastIndexOf('/') + 1).replace(/\.[^.]+$/, '');
      const res = await officeApi.fillPdfForm({
        workspace_path: workspacePath,
        template_path: managedPath,
        output_filename: `${stem}-filled.pdf`,
        data: values,
        flatten,
      });
      toast.success(`${t('office.form.fillSuccess')}（${res.filled_count}）: ${res.filename}`);
      onFilled?.();
      onClose();
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`${t('office.form.fillFailed')}: ${msg}`);
    } finally {
      setFilling(false);
    }
  };

  const inputClass = 'w-full px-3 py-1.5 text-sm border border-border rounded bg-surface text-text';

  return (
    <div
      className="border border-border rounded-lg bg-surface overflow-hidden"
      data-testid="office-pdf-form-dialog"
    >
      <div className="flex items-center gap-2 px-4 py-3 border-b border-border bg-bg-subtle">
        <span className="font-medium text-sm">{t('office.form.title')}</span>
        <button
          type="button"
          onClick={onClose}
          className="ml-auto px-2 py-1 rounded border border-border text-xs text-text-secondary hover:bg-bg-hover transition-colors"
          aria-label={t('office.form.close')}
        >
          {t('office.form.close')}
        </button>
      </div>

      <div className="p-4 space-y-3">
        {fields === null && !loading && (
          <button
            type="button"
            onClick={() => void load()}
            className="w-full px-4 py-2 bg-primary text-text-inverse rounded text-sm font-medium hover:bg-primary-hover"
            data-testid="office-pdf-form-load"
          >
            {t('office.form.load')}
          </button>
        )}
        {loading && <p className="text-xs text-muted">{t('office.form.loading')}</p>}
        {error && (
          <div className="px-3 py-2 bg-error/10 border border-error/30 rounded text-sm text-error">
            {error}
          </div>
        )}
        {fields !== null && fields.length === 0 && (
          <p className="text-sm text-muted" data-testid="office-pdf-form-empty">
            {t('office.form.noFields')}
          </p>
        )}
        {fields !== null && fields.length > 0 && (
          <>
            <ul className="space-y-2" data-testid="office-pdf-form-fields">
              {fields.map((f) => (
                <li key={f.name} className="space-y-1">
                  <label className="block text-xs text-muted break-all">
                    {f.name}
                    {f.required && <span className="text-error"> *</span>}
                    {f.read_only && ` · ${t('office.form.readOnly')}`}
                  </label>
                  <input
                    type="text"
                    disabled={f.read_only}
                    value={values[f.name] ?? (f.value == null ? '' : String(f.value))}
                    onChange={(e) => setValues((prev) => ({ ...prev, [f.name]: e.target.value }))}
                    className={inputClass}
                    data-testid={`office-pdf-form-field-${f.name}`}
                  />
                </li>
              ))}
            </ul>
            <label className="flex items-center gap-2 text-xs text-text-secondary">
              <input
                type="checkbox"
                checked={flatten}
                onChange={(e) => setFlatten(e.target.checked)}
                className="accent-primary"
                data-testid="office-pdf-form-flatten"
              />
              {t('office.form.flatten')}
            </label>
            <button
              type="button"
              onClick={() => void handleFill()}
              disabled={filling}
              className="w-full px-4 py-2 bg-primary text-text-inverse rounded text-sm font-medium hover:bg-primary-hover disabled:opacity-50"
              data-testid="office-pdf-form-submit"
            >
              {filling ? t('office.form.filling') : t('office.form.fill')}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
