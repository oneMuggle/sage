/**
 * WordStyleApplyDialog (M2 · D4) — 给已有 Word 文档套用样式画像。
 *
 * 样式来源二选一：工作区样式模板（style_template_id）或内置命名预设
 * （format_spec_preset），与后端合并链一致。先 dry-run 预览逐样式变更
 * （styles_changed）再应用；默认另存为 `<stem>-styled.docx`（不触碰原
 * 文件），勾选「覆写原文件」时原子替换并回读刷新预览。
 * 挂载点：OfficePreviewPanel Word 工具栏「规则审校」旁。
 */

import { useEffect, useState } from 'react';

import { officeApi } from '../../shared/api/officeApi';
import type {
  WordStyleApplyResult,
  WordStylePreset,
  WordStyleTemplate,
} from '../../shared/api/types';
import { useI18n } from '../../shared/lib/i18n';

export interface WordStyleApplyDialogProps {
  workspacePath: string;
  /** Managed path of the source Word document. */
  managedPath: string;
  /** Fired after a successful apply so the parent can refresh the preview. */
  onApplied?: () => void;
  onClose: () => void;
}

const TEMPLATE_PREFIX = 'template:';
const PRESET_PREFIX = 'preset:';

function ApplyStats({
  result,
  testId,
  sourcePath,
}: {
  result: WordStyleApplyResult;
  testId: string;
  /** Managed path of the source document — output_path equal to it means overwrite. */
  sourcePath?: string;
}) {
  const { t } = useI18n();
  return (
    <div className="space-y-1 rounded border border-border bg-bg p-2 text-xs" data-testid={testId}>
      {result.saved ? (
        <p className="text-success" data-testid={`${testId}-saved`}>
          {result.output_path && result.output_path !== sourcePath
            ? `${t('office.wordStyle.apply.savedCopy')}: ${result.output_path}`
            : t('office.wordStyle.apply.overwritten')}
        </p>
      ) : null}
      {result.styles_changed.length === 0 ? (
        <p className="text-muted">{t('office.wordStyle.apply.noChanges')}</p>
      ) : (
        <div>
          <p className="text-text-secondary">
            {t('office.wordStyle.apply.changesLabel')}: {result.styles_changed.length}
          </p>
          <ul className="mt-1 max-h-40 space-y-0.5 overflow-y-auto text-muted">
            {result.styles_changed.map((change, index) => (
              <li key={`${change.style}-${change.field}-${index}`}>
                {change.style} · {change.field}: {String(change.before ?? '—')} →{' '}
                {String(change.after ?? '—')}
              </li>
            ))}
          </ul>
        </div>
      )}
      {(result.direct_runs_cleared ?? 0) > 0 ? (
        <p className="text-muted">
          {t('office.wordStyle.apply.clearedLabel')}: {result.direct_runs_cleared}
        </p>
      ) : null}
      {result.warnings && result.warnings.length > 0 ? (
        <div>
          <p className="text-text-secondary">{t('office.wordStyle.apply.warningsLabel')}</p>
          <ul className="mt-0.5 space-y-0.5 text-muted">
            {result.warnings.map((warning, index) => (
              <li key={`${warning}-${index}`}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function WordStyleApplyDialog({
  workspacePath,
  managedPath,
  onApplied,
  onClose,
}: WordStyleApplyDialogProps) {
  const { t } = useI18n();
  const [presets, setPresets] = useState<WordStylePreset[]>([]);
  const [templates, setTemplates] = useState<WordStyleTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selection, setSelection] = useState('');
  const [clearDirectFormatting, setClearDirectFormatting] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [preview, setPreview] = useState<WordStyleApplyResult | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [result, setResult] = useState<WordStyleApplyResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setLoadError(null);
      try {
        const [presetRes, templateRes] = await Promise.all([
          officeApi.listWordStylePresets(),
          officeApi.listWordStyleTemplates(workspacePath || undefined),
        ]);
        if (cancelled) return;
        setPresets(presetRes.presets);
        setTemplates(templateRes.templates);
      } catch (e) {
        if (cancelled) return;
        setPresets([]);
        setTemplates([]);
        setLoadError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [workspacePath]);

  // 选择/选项变化后旧的 dry-run 统计失效，清空避免误读。
  const resetOutcome = () => {
    setPreview(null);
    setResult(null);
    setError(null);
  };

  const buildRequest = (dryRun: boolean) => {
    const source = selection.startsWith(TEMPLATE_PREFIX)
      ? { style_template_id: selection.slice(TEMPLATE_PREFIX.length) }
      : selection.startsWith(PRESET_PREFIX)
        ? { format_spec_preset: selection.slice(PRESET_PREFIX.length) }
        : {};
    return {
      ...(workspacePath ? { workspace_path: workspacePath } : {}),
      file_path: managedPath,
      ...source,
      clear_direct_formatting: clearDirectFormatting,
      ...(dryRun ? {} : { overwrite }),
      dry_run: dryRun,
    };
  };

  const handlePreview = async () => {
    if (!selection || previewing || applying) return;
    setPreviewing(true);
    setError(null);
    setResult(null);
    try {
      setPreview(await officeApi.applyWordStyle(buildRequest(true)));
    } catch (e) {
      setPreview(null);
      setError(
        `${t('office.wordStyle.apply.previewFailed')}: ${e instanceof Error ? e.message : String(e)}`,
      );
    } finally {
      setPreviewing(false);
    }
  };

  const handleApply = async () => {
    if (!selection || applying || previewing) return;
    setApplying(true);
    setError(null);
    try {
      const res = await officeApi.applyWordStyle(buildRequest(false));
      setResult(res);
      onApplied?.();
    } catch (e) {
      setError(
        `${t('office.wordStyle.apply.failed')}: ${e instanceof Error ? e.message : String(e)}`,
      );
    } finally {
      setApplying(false);
    }
  };

  return (
    <section className="space-y-3" data-testid="office-word-style-apply-dialog">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-text">{t('office.wordStyle.apply.title')}</h3>
        <button
          type="button"
          onClick={onClose}
          className="rounded border border-border px-2 py-1 text-xs text-text-secondary hover:bg-bg-hover"
          data-testid="office-word-style-apply-close"
        >
          {t('office.wordStyle.apply.close')}
        </button>
      </div>

      {loading ? (
        <p className="text-xs text-muted" data-testid="office-word-style-apply-loading">
          {t('office.wordStyle.apply.loading')}
        </p>
      ) : null}
      {loadError ? (
        <p className="text-xs text-error" data-testid="office-word-style-apply-load-error">
          {t('office.wordStyle.apply.loadFailed')}: {loadError}
        </p>
      ) : null}

      {!loading ? (
        <>
          <label className="block text-xs text-muted">
            {t('office.wordStyle.apply.sourceLabel')}
            <select
              className="mt-1 w-full rounded border border-border bg-surface px-2 py-1.5 text-sm text-text"
              value={selection}
              onChange={(event) => {
                setSelection(event.target.value);
                resetOutcome();
              }}
              data-testid="office-word-style-apply-source"
            >
              <option value="">{t('office.wordStyle.apply.sourcePlaceholder')}</option>
              {presets.length > 0 ? (
                <optgroup label={t('office.wordStyle.apply.presetGroup')}>
                  {presets.map((preset) => (
                    <option key={preset.id} value={`${PRESET_PREFIX}${preset.id}`}>
                      {preset.name}
                    </option>
                  ))}
                </optgroup>
              ) : null}
              {templates.length > 0 ? (
                <optgroup label={t('office.wordStyle.apply.templateGroup')}>
                  {templates.map((template) => (
                    <option key={template.id} value={`${TEMPLATE_PREFIX}${template.id}`}>
                      {template.is_default
                        ? `${template.name} · ${t('office.wordStyle.defaultBadge')}`
                        : template.name}
                    </option>
                  ))}
                </optgroup>
              ) : null}
            </select>
          </label>

          <div className="space-y-1 text-xs text-text-secondary">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={clearDirectFormatting}
                onChange={(event) => {
                  setClearDirectFormatting(event.target.checked);
                  resetOutcome();
                }}
                data-testid="office-word-style-apply-clear-direct"
              />
              {t('office.wordStyle.apply.clearDirect')}
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={overwrite}
                onChange={(event) => {
                  setOverwrite(event.target.checked);
                  resetOutcome();
                }}
                data-testid="office-word-style-apply-overwrite"
              />
              {t('office.wordStyle.apply.overwrite')}
            </label>
            <p className="text-muted">{t('office.wordStyle.apply.overwriteHint')}</p>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void handlePreview()}
              disabled={!selection || previewing || applying}
              className="rounded border border-border px-2 py-1 text-xs text-text-secondary hover:bg-bg-hover disabled:opacity-50"
              data-testid="office-word-style-apply-preview"
            >
              {previewing
                ? t('office.wordStyle.apply.previewing')
                : t('office.wordStyle.apply.preview')}
            </button>
            <button
              type="button"
              onClick={() => void handleApply()}
              disabled={!selection || previewing || applying}
              className="rounded bg-primary px-2 py-1 text-xs text-white hover:opacity-90 disabled:opacity-50"
              data-testid="office-word-style-apply-run"
            >
              {applying ? t('office.wordStyle.apply.applying') : t('office.wordStyle.apply.apply')}
            </button>
          </div>

          {error ? (
            <p className="text-xs text-error" data-testid="office-word-style-apply-error">
              {error}
            </p>
          ) : null}
          {preview ? (
            <ApplyStats
              result={preview}
              testId="office-word-style-apply-preview-result"
              sourcePath={managedPath}
            />
          ) : null}
          {result ? (
            <ApplyStats
              result={result}
              testId="office-word-style-apply-result"
              sourcePath={managedPath}
            />
          ) : null}
        </>
      ) : null}
    </section>
  );
}
