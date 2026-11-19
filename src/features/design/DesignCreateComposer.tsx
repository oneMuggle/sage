/**
 * DesignCreateComposer — 单屏创作器。
 *
 * 用户只需选一个意图 chip（可选）并写 brief，设计系统 / 模板 / 项目名
 * 由服务端默认值补齐；「高级选项」里才暴露完整选择。
 */
import { ArrowLeft, ChevronDown, Loader2, Sparkles } from 'lucide-react';
import { useMemo, useState } from 'react';

import { useDesignStore } from '../../entities/design/designStore';
import type { ProjectKind } from '../../entities/design/types';
import { useI18n } from '../../shared/lib/i18n';

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
  const [error, setError] = useState<string | null>(null);

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
          <p className="mt-1 text-ui-xs text-text-tertiary">{t('design.composer.presetsHint')}</p>
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
                      : 'border-border text-text-secondary hover:bg-surface-hover'
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
          <label htmlFor="design-brief" className="text-ui-sm font-medium text-text">
            {t('design.composer.brief')}
          </label>
          <p className="mt-0.5 text-ui-xs text-text-secondary">{t('design.composer.briefHint')}</p>
          <textarea
            id="design-brief"
            value={brief}
            onChange={(event) => setBrief(event.target.value)}
            placeholder={t('design.composer.briefPlaceholder')}
            rows={7}
            className="mt-2 w-full resize-y rounded-md border border-border bg-surface px-3 py-2 text-ui-sm outline-none focus:border-accent"
          />
        </section>

        <button
          type="button"
          aria-expanded={advanced}
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-ui-xs text-text-secondary hover:bg-surface-hover"
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
                        : 'border-border text-text-secondary hover:bg-surface-hover'
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
          </section>
        )}

        {error && <p className="text-ui-sm text-red-500">{error}</p>}

        <div className="flex items-center justify-between">
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-ui-sm hover:bg-surface-hover"
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
