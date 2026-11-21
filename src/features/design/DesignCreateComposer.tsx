/**
 * DesignCreateComposer — 单屏创作器。
 *
 * 用户只需选一个意图 chip（可选）并写 brief，设计系统 / 模板 / 项目名
 * 由服务端默认值补齐；「高级选项」里才暴露完整选择。
 */
import { ArrowLeft, ChevronDown, FileText, Loader2, Sparkles, Wand2 } from 'lucide-react';
import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import { extractOutline } from '../../entities/design/designApi';
import { useDesignStore } from '../../entities/design/designStore';
import type { ProjectKind } from '../../entities/design/types';
import { useI18n } from '../../shared/lib/i18n';
import { HtmlPreviewHost } from '../../widgets/chat/preview/HtmlPreviewHost';

import { applyTokensCss } from './designTweaks';

interface DesignCreateComposerProps {
  onCancel: () => void;
  onCreated: (projectId: string) => void;
}

interface Preset {
  key:
    | 'design.preset.pitch'
    | 'design.preset.weekly'
    | 'design.preset.landing'
    | 'design.preset.dashboard'
    | 'design.preset.pricing';
  kind: ProjectKind;
  templateId: string;
}

const PRESETS: Preset[] = [
  { key: 'design.preset.pitch', kind: 'deck', templateId: 'pitch-deck' },
  { key: 'design.preset.weekly', kind: 'deck', templateId: 'weekly-report' },
  { key: 'design.preset.landing', kind: 'prototype', templateId: 'landing-page' },
  { key: 'design.preset.dashboard', kind: 'prototype', templateId: 'dashboard' },
  { key: 'design.preset.pricing', kind: 'prototype', templateId: 'pricing' },
];

type QuickAudience = 'investor' | 'team' | 'customer' | 'general';
type QuickLength = 'short' | 'medium' | 'long' | 'single';
type QuickTone = 'professional' | 'friendly' | 'bold';

const AUDIENCE_KEYS = {
  investor: 'design.composer.quickAudience.investor',
  team: 'design.composer.quickAudience.team',
  customer: 'design.composer.quickAudience.customer',
  general: 'design.composer.quickAudience.general',
} as const;

const LENGTH_KEYS = {
  short: 'design.composer.quickLength.short',
  medium: 'design.composer.quickLength.medium',
  long: 'design.composer.quickLength.long',
  single: 'design.composer.quickLength.single',
} as const;

const TONE_KEYS = {
  professional: 'design.composer.quickTone.professional',
  friendly: 'design.composer.quickTone.friendly',
  bold: 'design.composer.quickTone.bold',
} as const;

export function DesignCreateComposer({ onCancel, onCreated }: DesignCreateComposerProps) {
  const { t } = useI18n();
  const systems = useDesignStore((s) => s.systems);
  const templates = useDesignStore((s) => s.templates);
  const createProject = useDesignStore((s) => s.createProject);
  const generate = useDesignStore((s) => s.generate);

  const [kind, setKind] = useState<ProjectKind>('deck');
  const [templateId, setTemplateId] = useState<string | undefined>();
  const [systemId, setSystemId] = useState<string | undefined>();
  const [selectedPreset, setSelectedPreset] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [brief, setBrief] = useState('');
  const [advanced, setAdvanced] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [importingOutline, setImportingOutline] = useState(false);
  const [quickBriefOpen, setQuickBriefOpen] = useState(false);
  const [quickAudience, setQuickAudience] = useState<QuickAudience>('general');
  const [quickLength, setQuickLength] = useState<QuickLength>('medium');
  const [quickTone, setQuickTone] = useState<QuickTone>('professional');
  const [error, setError] = useState<string | null>(null);

  const canPickFile = typeof window !== 'undefined' && Boolean(window.electronAPI?.selectFile);

  const handleImportOutline = async () => {
    const picker = window.electronAPI?.selectFile;
    if (!picker) return;
    const path = await picker({
      title: t('design.composer.importOutline'),
      filters: [{ name: 'Word', extensions: ['docx'] }],
    });
    if (!path) return;
    setImportingOutline(true);
    try {
      const outline = await extractOutline(path);
      setBrief((prev) => (prev.trim() ? `${prev}\n\n${outline.outline_md}` : outline.outline_md));
      toast.success(
        t('design.composer.outlineLoaded').replace('{count}', String(outline.slide_count)),
      );
    } catch (err) {
      toast.error(
        t('design.composer.outlineFailed').replace(
          '{error}',
          err instanceof Error ? err.message : String(err),
        ),
      );
    } finally {
      setImportingOutline(false);
    }
  };

  const availablePresets = useMemo(
    () =>
      PRESETS.filter((preset) =>
        templates.some((tpl) => tpl.id === preset.templateId && tpl.kind === preset.kind),
      ),
    [templates],
  );
  const kindTemplates = useMemo(
    () => templates.filter((tpl) => tpl.kind === kind),
    [templates, kind],
  );
  const previewTemplate = kindTemplates.find((tpl) => tpl.id === templateId) ?? kindTemplates[0];
  const directionSystems = systems.filter((system) => system.tokens_css.trim()).slice(0, 3);

  const applyQuickBrief = () => {
    const kindLabel = kind === 'deck' ? t('design.kind.deck') : t('design.kind.prototype');
    const sentence = t('design.composer.quickBriefTemplate')
      .replace('{audience}', t(AUDIENCE_KEYS[quickAudience]))
      .replace('{length}', t(LENGTH_KEYS[quickLength]))
      .replace('{kindLabel}', kindLabel)
      .replace('{tone}', t(TONE_KEYS[quickTone]));
    setBrief((prev) => (prev.trim() ? `${prev}\n\n${sentence}` : sentence));
    setQuickBriefOpen(false);
  };

  const handlePreset = (preset: Preset) => {
    if (selectedPreset === preset.key) {
      setSelectedPreset(null);
      setKind('deck');
      setTemplateId(undefined);
      return;
    }
    setSelectedPreset(preset.key);
    setKind(preset.kind);
    setTemplateId(preset.templateId);
  };

  const handleKindChange = (next: ProjectKind) => {
    setKind(next);
    setSelectedPreset(null);
    if (templateId && !templates.some((tpl) => tpl.id === templateId && tpl.kind === next)) {
      setTemplateId(undefined);
    }
  };

  const handleTemplateChange = (value: string) => {
    setTemplateId(value || undefined);
    setSelectedPreset(null);
    const template = templates.find((tpl) => tpl.id === value);
    if (template) setKind(template.kind);
  };

  const canSubmit = brief.trim().length > 0 && !submitting;

  const handleSubmit = async () => {
    const trimmed = brief.trim();
    if (!trimmed || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const project = await createProject({
        name: name.trim() || undefined,
        kind,
        system_id: systemId,
        template_id: templateId,
        brief: trimmed,
      });
      onCreated(project.id);
      void generate(project.id, trimmed);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto px-5 py-4">
      <div className="mx-auto max-w-3xl space-y-4">
        <section>
          <h2 className="text-ui-md font-medium text-text">{t('design.composer.title')}</h2>
          <p className="mt-1 text-ui-xs text-text-muted">{t('design.composer.presetsHint')}</p>
          {availablePresets.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2">
              {availablePresets.map((preset) => (
                <button
                  key={preset.key}
                  type="button"
                  aria-pressed={selectedPreset === preset.key}
                  className={`rounded-full border px-3 py-1 text-ui-xs transition ${
                    selectedPreset === preset.key
                      ? 'border-accent bg-accent/5 text-accent'
                      : 'border-border text-text-secondary hover:bg-bg-hover'
                  }`}
                  onClick={() => handlePreset(preset)}
                >
                  {t(preset.key)}
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="rounded-lg border border-border bg-surface p-4">
          <div className="flex items-start justify-between gap-2">
            <div>
              <label htmlFor="design-brief" className="text-ui-sm font-medium text-text">
                {t('design.composer.brief')}
              </label>
              <p className="mt-0.5 text-ui-xs text-text-secondary">
                {t('design.composer.briefHint')}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <button
                type="button"
                className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-ui-xs hover:bg-bg-hover"
                onClick={() => setQuickBriefOpen((prev) => !prev)}
              >
                <Wand2 className="h-3 w-3" />
                {t('design.composer.quickBrief')}
              </button>
              <button
                type="button"
                className="inline-flex shrink-0 items-center gap-1 rounded-md border border-border px-2 py-1 text-ui-xs hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40"
                disabled={!canPickFile || importingOutline}
                title={
                  canPickFile
                    ? t('design.composer.importOutline')
                    : t('design.resources.filePickerUnavailable')
                }
                onClick={() => void handleImportOutline()}
              >
                {importingOutline ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <FileText className="h-3 w-3" />
                )}
                {t('design.composer.importOutline')}
              </button>
            </div>
          </div>
          <textarea
            id="design-brief"
            value={brief}
            onChange={(event) => setBrief(event.target.value)}
            placeholder={t('design.composer.briefPlaceholder')}
            rows={7}
            className="mt-2 w-full resize-y rounded-md border border-border bg-surface px-3 py-2 text-ui-sm outline-none focus:border-accent"
          />
          {quickBriefOpen && (
            <div className="mt-3 space-y-2 rounded-md border border-border p-3 text-ui-xs">
              <div className="grid grid-cols-3 gap-2">
                <label className="block">
                  <span className="text-text-muted">{t('design.composer.quickAudience')}</span>
                  <select
                    value={quickAudience}
                    onChange={(event) => setQuickAudience(event.target.value as QuickAudience)}
                    className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1 outline-none focus:border-accent"
                  >
                    {(Object.keys(AUDIENCE_KEYS) as QuickAudience[]).map((value) => (
                      <option key={value} value={value}>
                        {t(AUDIENCE_KEYS[value])}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  <span className="text-text-muted">{t('design.composer.quickLength')}</span>
                  <select
                    value={quickLength}
                    onChange={(event) => setQuickLength(event.target.value as QuickLength)}
                    className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1 outline-none focus:border-accent"
                  >
                    {(Object.keys(LENGTH_KEYS) as QuickLength[]).map((value) => (
                      <option key={value} value={value}>
                        {t(LENGTH_KEYS[value])}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  <span className="text-text-muted">{t('design.composer.quickTone')}</span>
                  <select
                    value={quickTone}
                    onChange={(event) => setQuickTone(event.target.value as QuickTone)}
                    className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1 outline-none focus:border-accent"
                  >
                    {(Object.keys(TONE_KEYS) as QuickTone[]).map((value) => (
                      <option key={value} value={value}>
                        {t(TONE_KEYS[value])}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="flex justify-end">
                <button
                  type="button"
                  className="rounded-md bg-accent px-3 py-1 text-ui-xs text-white"
                  onClick={applyQuickBrief}
                >
                  {t('design.composer.quickFill')}
                </button>
              </div>
            </div>
          )}
        </section>

        <button
          type="button"
          aria-expanded={advanced}
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-ui-xs text-text-secondary hover:bg-bg-hover"
          onClick={() => setAdvanced((prev) => !prev)}
        >
          <ChevronDown className={`h-3.5 w-3.5 transition ${advanced ? 'rotate-180' : ''}`} />
          {t('design.composer.advanced')}
        </button>

        {advanced && (
          <section className="space-y-3 rounded-lg border border-border bg-surface p-4">
            <div>
              <label className="text-ui-sm font-medium text-text" htmlFor="design-name">
                {t('design.composer.name')}
              </label>
              <input
                id="design-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t('design.composer.namePlaceholder')}
                className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-ui-sm outline-none focus:border-accent"
              />
            </div>
            <div>
              <span className="text-ui-sm font-medium text-text">{t('design.composer.kind')}</span>
              <div className="mt-1 flex gap-2">
                {(['deck', 'prototype'] as const).map((option) => (
                  <button
                    key={option}
                    type="button"
                    aria-pressed={kind === option}
                    className={`rounded-md border px-3 py-1 text-ui-xs transition ${
                      kind === option
                        ? 'border-accent bg-accent/5 text-accent'
                        : 'border-border text-text-secondary hover:bg-bg-hover'
                    }`}
                    onClick={() => handleKindChange(option)}
                  >
                    {t(`design.kind.${option}`)}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="text-ui-sm font-medium text-text" htmlFor="design-system">
                {t('design.composer.system')}
              </label>
              <select
                id="design-system"
                value={systemId ?? ''}
                onChange={(event) => setSystemId(event.target.value || undefined)}
                className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-ui-sm outline-none focus:border-accent"
              >
                <option value="">{t('design.composer.systemAuto')}</option>
                {systems.map((system) => (
                  <option key={system.id} value={system.id}>
                    {system.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-ui-sm font-medium text-text" htmlFor="design-template">
                {t('design.composer.template')}
              </label>
              <select
                id="design-template"
                value={templateId ?? ''}
                onChange={(event) => handleTemplateChange(event.target.value)}
                className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-ui-sm outline-none focus:border-accent"
              >
                <option value="">{t('design.composer.templateAuto')}</option>
                {kindTemplates.map((template) => (
                  <option key={template.id} value={template.id}>
                    {template.name}
                  </option>
                ))}
              </select>
            </div>
            {previewTemplate?.example_html && directionSystems.length > 1 && (
              <div>
                <span className="text-ui-sm font-medium text-text">
                  {t('design.composer.directionTitle')}
                </span>
                <p className="mt-0.5 text-ui-xs text-text-muted">
                  {t('design.composer.directionHint')}
                </p>
                <div className="mt-2 grid grid-cols-3 gap-2">
                  {directionSystems.map((system) => {
                    const selected = systemId === system.id;
                    return (
                      <button
                        key={system.id}
                        type="button"
                        aria-pressed={selected}
                        className={`overflow-hidden rounded-md border text-left transition ${
                          selected ? 'border-accent' : 'border-border hover:border-accent/60'
                        }`}
                        onClick={() => setSystemId(selected ? undefined : system.id)}
                      >
                        <div className="pointer-events-none">
                          <HtmlPreviewHost
                            html={applyTokensCss(
                              previewTemplate.example_html ?? '',
                              system.tokens_css,
                            )}
                            name={`${system.id}-${previewTemplate.id}.html`}
                            heightClassName="h-28"
                          />
                        </div>
                        <div
                          className={`border-t border-border px-2 py-1 text-ui-xs ${
                            selected ? 'text-accent' : 'text-text-secondary'
                          }`}
                        >
                          {system.name}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
            {previewTemplate?.example_html && (
              <div>
                <span className="text-ui-sm font-medium text-text">
                  {t('design.composer.templatePreview')}
                </span>
                <div className="mt-1 overflow-hidden rounded-md border border-border">
                  <HtmlPreviewHost
                    html={previewTemplate.example_html}
                    name={`${previewTemplate.id}-example.html`}
                    heightClassName="h-56"
                  />
                </div>
              </div>
            )}
          </section>
        )}

        {error && <p className="text-ui-sm text-red-500">{error}</p>}

        <div className="flex items-center justify-between">
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-ui-sm hover:bg-bg-hover"
            onClick={onCancel}
            disabled={submitting}
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            {t('design.cancel')}
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-md bg-accent px-4 py-1.5 text-ui-sm text-white disabled:opacity-50"
            onClick={() => void handleSubmit()}
            disabled={!canSubmit}
          >
            {submitting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            {submitting ? t('design.composer.creating') : t('design.composer.create')}
          </button>
        </div>
      </div>
    </div>
  );
}
