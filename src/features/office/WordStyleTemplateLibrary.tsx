/**
 * WordStyleTemplateLibrary (M2) — 工作区样式模板 / 内置版式预设分区。
 *
 * 交互形态沿用 OfficeSpecLibrary：列表 + 默认徽章 + 设为默认/清除默认 + 两段式删除。
 * 数据源为内置预设（只读）与 `/word/style-templates`（工作区模板，可删）。
 * 该分区挂在 TemplateLibrary 文档模板列表上方。
 */

import { useCallback, useEffect, useState } from 'react';

import { officeApi } from '../../shared/api/officeApi';
import type {
  WordStylePreset,
  WordStyleTemplate,
  WordStyleTemplateSourceKind,
} from '../../shared/api/types';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

const SOURCE_KEYS: Record<WordStyleTemplateSourceKind, TranslationKey> = {
  preset: 'office.wordStyle.source.preset',
  rulepack: 'office.wordStyle.source.rulepack',
  manual: 'office.wordStyle.source.manual',
};

export interface WordStyleTemplateLibraryProps {
  workspacePath: string;
}

export function WordStyleTemplateLibrary({ workspacePath }: WordStyleTemplateLibraryProps) {
  const { t } = useI18n();
  const [presets, setPresets] = useState<WordStylePreset[]>([]);
  const [templates, setTemplates] = useState<WordStyleTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [presetRes, templateRes] = await Promise.all([
        officeApi.listWordStylePresets(),
        officeApi.listWordStyleTemplates(workspacePath || undefined),
      ]);
      setPresets(presetRes.presets);
      setTemplates(templateRes.templates);
    } catch (e) {
      setPresets([]);
      setTemplates([]);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [workspacePath]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleActivate = async (template: WordStyleTemplate) => {
    setBusyId(template.id);
    setError(null);
    setMessage(null);
    try {
      await officeApi.activateWordStyleTemplate(template.id, workspacePath);
      setMessage(`${t('office.wordStyle.activated')}「${template.name}」`);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  const handleClearDefault = async () => {
    setBusyId('__clear__');
    setError(null);
    setMessage(null);
    try {
      await officeApi.clearDefaultWordStyleTemplate(workspacePath);
      setMessage(t('office.wordStyle.clearedDefault'));
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (templateId: string) => {
    if (pendingDeleteId !== templateId) {
      setPendingDeleteId(templateId);
      return;
    }
    setBusyId(templateId);
    setError(null);
    setMessage(null);
    try {
      await officeApi.deleteWordStyleTemplate(templateId, workspacePath);
      setMessage(t('office.wordStyle.deleted'));
      setPendingDeleteId(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  const hasDefault = templates.some((tpl) => tpl.is_default);

  return (
    <section
      className="space-y-2 border-b border-border pb-3"
      data-testid="office-word-style-library"
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-medium text-text-secondary">{t('office.wordStyle.title')}</h3>
        <div className="flex items-center gap-2">
          {hasDefault ? (
            <button
              type="button"
              onClick={() => void handleClearDefault()}
              disabled={busyId !== null}
              className="rounded border border-border px-2 py-1 text-xs text-text-secondary hover:bg-bg-hover disabled:opacity-50"
              data-testid="office-word-style-clear-default"
            >
              {t('office.wordStyle.clearDefault')}
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading}
            className="rounded border border-border px-2 py-1 text-xs text-text-secondary hover:bg-bg-hover disabled:opacity-50"
            data-testid="office-word-style-refresh"
          >
            {t('office.wordStyle.refresh')}
          </button>
        </div>
      </div>

      {error ? (
        <p className="text-xs text-error" data-testid="office-word-style-error">
          {error}
        </p>
      ) : null}
      {message ? (
        <p className="text-xs text-success" data-testid="office-word-style-message">
          {message}
        </p>
      ) : null}

      {loading ? (
        <p className="text-xs text-muted" data-testid="office-word-style-loading">
          {t('office.wordStyle.loading')}
        </p>
      ) : (
        <>
          {presets.length > 0 ? (
            <div className="space-y-1">
              <span className="text-xs text-muted">{t('office.wordStyle.presets')}</span>
              <ul className="flex flex-wrap gap-1">
                {presets.map((preset) => (
                  <li
                    key={preset.id}
                    className="rounded border border-border bg-bg px-2 py-1 text-xs text-text-secondary"
                    data-testid={`office-word-style-preset-${preset.id}`}
                  >
                    {preset.name}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="space-y-1">
            <span className="text-xs text-muted">{t('office.wordStyle.templates')}</span>
            {templates.length === 0 ? (
              <p className="text-xs text-muted" data-testid="office-word-style-empty">
                {t('office.wordStyle.empty')}
              </p>
            ) : (
              <ul className="flex flex-col divide-y divide-border rounded border border-border bg-bg">
                {templates.map((tpl) => (
                  <li
                    key={tpl.id}
                    className="flex items-center gap-2 px-3 py-2"
                    data-testid={`office-word-style-template-${tpl.id}`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm text-text">{tpl.name}</span>
                        {tpl.is_default ? (
                          <span
                            className="rounded bg-primary/10 px-1.5 py-0.5 text-xs text-primary"
                            data-testid={`office-word-style-default-badge-${tpl.id}`}
                          >
                            {t('office.wordStyle.defaultBadge')}
                          </span>
                        ) : null}
                      </div>
                      <div className="mt-0.5 truncate text-xs text-muted">
                        {t('office.wordStyle.sourceLabel')} {t(SOURCE_KEYS[tpl.source_kind])}
                        {tpl.source_ref ? ` · ${tpl.source_ref}` : ''}
                      </div>
                    </div>
                    {!tpl.is_default ? (
                      <button
                        type="button"
                        onClick={() => void handleActivate(tpl)}
                        disabled={busyId !== null}
                        className="shrink-0 rounded border border-border px-2 py-1 text-xs text-text-secondary hover:bg-bg-hover disabled:opacity-50"
                        data-testid={`office-word-style-activate-${tpl.id}`}
                      >
                        {t('office.wordStyle.activate')}
                      </button>
                    ) : null}
                    <button
                      type="button"
                      onClick={() => void handleDelete(tpl.id)}
                      disabled={busyId !== null}
                      className="shrink-0 rounded border border-border px-2 py-1 text-xs text-error hover:bg-bg-hover disabled:opacity-50"
                      data-testid={`office-word-style-delete-${tpl.id}`}
                    >
                      {pendingDeleteId === tpl.id
                        ? t('office.wordStyle.confirmDelete')
                        : t('office.wordStyle.delete')}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </section>
  );
}
