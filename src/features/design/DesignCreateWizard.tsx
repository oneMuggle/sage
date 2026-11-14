/**
 * DesignCreateWizard — 4 步创建向导（类型 → 设计系统 → 模板 → 项目信息）。
 */
import { ArrowLeft, ArrowRight, Check, Loader2 } from 'lucide-react';
import { useMemo, useState } from 'react';

import { useDesignStore } from '../../entities/design/designStore';
import type { ProjectKind } from '../../entities/design/types';
import { useI18n } from '../../shared/lib/i18n';

interface DesignCreateWizardProps {
  onCancel: () => void;
  onCreated: (projectId: string) => void;
}

const STEP_KEYS = [
  'design.wizard.step1',
  'design.wizard.step2',
  'design.wizard.step3',
  'design.wizard.step4',
] as const;

export function DesignCreateWizard({ onCancel, onCreated }: DesignCreateWizardProps) {
  const { t } = useI18n();
  const systems = useDesignStore((s) => s.systems);
  const templates = useDesignStore((s) => s.templates);
  const createProject = useDesignStore((s) => s.createProject);
  const generate = useDesignStore((s) => s.generate);

  const [step, setStep] = useState(0);
  const [kind, setKind] = useState<ProjectKind>('deck');
  const [systemId, setSystemId] = useState('');
  const [templateId, setTemplateId] = useState('');
  const [name, setName] = useState('');
  const [brief, setBrief] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const kindTemplates = useMemo(
    () => templates.filter((template) => template.kind === kind),
    [templates, kind],
  );

  const canAdvance = (() => {
    switch (step) {
      case 0:
        return true;
      case 1:
        return Boolean(systemId);
      case 2:
        return Boolean(templateId);
      default:
        return name.trim().length > 0 && brief.trim().length > 0;
    }
  })();

  const handleKindChange = (next: ProjectKind) => {
    setKind(next);
    if (templates.some((tpl) => tpl.id === templateId && tpl.kind !== next)) {
      setTemplateId('');
    }
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const project = await createProject({
        name: name.trim(),
        kind,
        system_id: systemId,
        template_id: templateId,
        brief: brief.trim(),
      });
      onCreated(project.id);
      void generate(project.id, brief.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSubmitting(false);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto px-5 py-4">
      <div className="max-w-3xl mx-auto">
        <ol className="flex items-center gap-2 text-ui-xs text-text-secondary">
          {STEP_KEYS.map((key, index) => (
            <li key={key} className="flex items-center gap-2">
              <span
                className={`inline-flex h-5 w-5 items-center justify-center rounded-full border ${
                  index <= step
                    ? 'border-accent text-accent'
                    : 'border-border text-text-tertiary'
                }`}
              >
                {index < step ? <Check className="w-3 h-3" /> : index + 1}
              </span>
              <span className={index === step ? 'text-text' : undefined}>{t(key)}</span>
              {index < STEP_KEYS.length - 1 && <span className="text-text-tertiary">/</span>}
            </li>
          ))}
        </ol>

        <div className="mt-5 rounded-lg border border-border bg-surface p-5">
          {step === 0 && (
            <section>
              <p className="text-ui-sm text-text-secondary">{t('design.wizard.kindHint')}</p>
              <div className="mt-3 grid grid-cols-2 gap-3">
                {(['deck', 'prototype'] as const).map((option) => (
                  <button
                    key={option}
                    type="button"
                    className={`rounded-lg border p-4 text-left text-ui-sm transition ${
                      kind === option
                        ? 'border-accent bg-accent/5 text-text'
                        : 'border-border hover:bg-surface-hover'
                    }`}
                    onClick={() => handleKindChange(option)}
                  >
                    {t(`design.kind.${option}`)}
                  </button>
                ))}
              </div>
            </section>
          )}

          {step === 1 && (
            <section>
              <p className="text-ui-sm text-text-secondary">{t('design.wizard.systemHint')}</p>
              {systems.length === 0 ? (
                <p className="mt-3 text-ui-sm text-text-tertiary">{t('design.wizard.noOptions')}</p>
              ) : (
                <ul className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-2">
                  {systems.map((system) => (
                    <li key={system.id}>
                      <button
                        type="button"
                        className={`w-full rounded-md border p-3 text-left text-ui-sm transition ${
                          systemId === system.id
                            ? 'border-accent bg-accent/5'
                            : 'border-border hover:bg-surface-hover'
                        }`}
                        onClick={() => setSystemId(system.id)}
                      >
                        <p className="font-medium text-text">{system.name}</p>
                        <p className="mt-0.5 text-ui-xs text-text-secondary line-clamp-2">
                          {system.description}
                        </p>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {step === 2 && (
            <section>
              <p className="text-ui-sm text-text-secondary">{t('design.wizard.templateHint')}</p>
              {kindTemplates.length === 0 ? (
                <p className="mt-3 text-ui-sm text-text-tertiary">{t('design.wizard.noOptions')}</p>
              ) : (
                <ul className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-2">
                  {kindTemplates.map((template) => (
                    <li key={template.id}>
                      <button
                        type="button"
                        className={`w-full rounded-md border p-3 text-left text-ui-sm transition ${
                          templateId === template.id
                            ? 'border-accent bg-accent/5'
                            : 'border-border hover:bg-surface-hover'
                        }`}
                        onClick={() => setTemplateId(template.id)}
                      >
                        <p className="font-medium text-text">{template.name}</p>
                        <p className="mt-0.5 text-ui-xs text-text-secondary line-clamp-2">
                          {template.description}
                        </p>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {step === 3 && (
            <section className="space-y-4">
              <div>
                <label className="text-ui-sm font-medium text-text" htmlFor="design-name">
                  {t('design.wizard.name')}
                </label>
                <input
                  id="design-name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder={t('design.wizard.namePlaceholder')}
                  className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-ui-sm outline-none focus:border-accent"
                />
              </div>
              <div>
                <label className="text-ui-sm font-medium text-text" htmlFor="design-brief">
                  {t('design.wizard.brief')}
                </label>
                <p className="mt-0.5 text-ui-xs text-text-secondary">
                  {t('design.wizard.briefHint')}
                </p>
                <textarea
                  id="design-brief"
                  value={brief}
                  onChange={(event) => setBrief(event.target.value)}
                  placeholder={t('design.wizard.briefPlaceholder')}
                  rows={6}
                  className="mt-1 w-full resize-y rounded-md border border-border bg-surface px-3 py-2 text-ui-sm outline-none focus:border-accent"
                />
              </div>
              {error && <p className="text-ui-sm text-red-500">{error}</p>}
            </section>
          )}
        </div>

        <div className="mt-4 flex items-center justify-between">
          <button
            type="button"
            className="px-3 py-1.5 rounded-md text-ui-sm hover:bg-surface-hover"
            onClick={() => (step === 0 ? onCancel() : setStep(step - 1))}
            disabled={submitting}
          >
            <ArrowLeft className="mr-1 inline w-3.5 h-3.5" />
            {step === 0 ? t('design.cancel') : t('design.wizard.prev')}
          </button>
          {step < STEP_KEYS.length - 1 ? (
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-ui-sm text-white disabled:opacity-50"
              onClick={() => setStep(step + 1)}
              disabled={!canAdvance}
            >
              {t('design.wizard.next')}
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          ) : (
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-ui-sm text-white disabled:opacity-50"
              onClick={() => void handleSubmit()}
              disabled={!canAdvance || submitting}
            >
              {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {submitting ? t('design.wizard.creating') : t('design.wizard.create')}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
