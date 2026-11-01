/**
 * PlaybookSpecEditor — 结构化表单 + JSON 高级视图。
 *
 * 表单可编辑名称/描述/阶段/产物，以及阶段规则、推荐里程碑与退出条件；
 * 内容检查等其余字段保留在 JSON 视图中编辑。
 */
import { useState } from 'react';

import type {
  PlaybookArtifactSpec,
  PlaybookSpec,
  PlaybookStageSpec,
} from '../../shared/api/playbookApi';
import { Button } from '../../shared/ui/Button';

import { PlaybookStageSections } from './PlaybookStageSections';
import type {
  ArtifactForm,
  CriterionForm,
  FormState,
  MilestoneForm,
  RuleForm,
  StageForm,
} from './playbookEditorTypes';
import { usePlaybookI18n } from './usePlaybookI18n';

export interface PlaybookSpecEditorProps {
  spec: PlaybookSpec;
  saving: boolean;
  error: string | null;
  onSave: (spec: PlaybookSpec) => void;
  onCancel: () => void;
}

function toForm(spec: PlaybookSpec): FormState {
  return {
    name: spec.name,
    description: spec.description ?? '',
    stages: (spec.stages ?? []).map((stage) => ({
      id: stage.id,
      label: stage.label ?? '',
      objective: stage.objective ?? '',
      artifacts: (stage.artifacts ?? []).map((artifact) => ({
        id: artifact.id,
        label: artifact.label ?? '',
        globs: (artifact.match?.globs ?? []).join(', '),
        targetDir: artifact.target_dir ?? '',
        required: artifact.required !== false,
      })),
      rules: (stage.rules ?? []).map((rule) => ({
        templateKey: String(rule.template_key ?? ''),
        content: String(rule.content ?? ''),
        category: String(rule.category ?? ''),
        triggerPattern: String(rule.trigger_pattern ?? ''),
        priority: Number(rule.priority ?? 5),
      })),
      milestones: (stage.recommended_milestones ?? []).map((item) => ({
        title: String(item.title ?? ''),
        description: String(item.description ?? ''),
      })),
      criteria: (stage.exit_criteria ?? []).map((item) => ({
        id: String(item.id ?? ''),
        label: String(item.label ?? ''),
        type: item.type === 'artifact' ? 'artifact' : 'manual',
        artifactId: String(item.artifact_id ?? ''),
      })),
    })),
  };
}

function toSpec(spec: PlaybookSpec, form: FormState): PlaybookSpec {
  const originalStages = spec.stages ?? [];
  const stages: PlaybookStageSpec[] = form.stages.map((stage, stageIndex) => {
    const original =
      originalStages.find((item) => item.id === stage.id) ?? originalStages[stageIndex];
    const artifacts: PlaybookArtifactSpec[] = stage.artifacts.map((artifact, artifactIndex) => {
      const previous =
        (original?.artifacts ?? []).find((item) => item.id === artifact.id) ??
        (original?.artifacts ?? [])[artifactIndex];
      const globs = artifact.globs
        .split(/[,\n]/)
        .map((item) => item.trim())
        .filter(Boolean);
      return {
        ...(previous ?? {}),
        id: artifact.id || previous?.id || `artifact-${stageIndex + 1}-${artifactIndex + 1}`,
        label: artifact.label,
        required: artifact.required,
        target_dir: artifact.targetDir.trim() || null,
        match: {
          ...(previous?.match ?? {}),
          globs,
          min_bytes: previous?.match?.min_bytes ?? 0,
          min_count: previous?.match?.min_count ?? 1,
          max_age_days: previous?.match?.max_age_days ?? null,
        },
        content_checks: previous?.content_checks ?? [],
        missing_action: previous?.missing_action ?? null,
      } as PlaybookArtifactSpec;
    });
    return {
      ...(original ?? {}),
      id: stage.id || `stage-${stageIndex + 1}`,
      label: stage.label,
      order: stageIndex + 1,
      objective: stage.objective,
      artifacts,
      rules: stage.rules
        .map((rule) =>
          rule.templateKey.trim()
            ? { template_key: rule.templateKey.trim(), priority: rule.priority }
            : {
                content: rule.content.trim(),
                category: rule.category.trim() || 'playbook',
                trigger_pattern: rule.triggerPattern.trim() || 'always',
                priority: rule.priority,
              },
        )
        .filter((rule) => ('content' in rule ? rule.content : rule.template_key)),
      recommended_milestones: stage.milestones
        .filter((milestone) => milestone.title.trim())
        .map((milestone) => ({
          title: milestone.title.trim(),
          description: milestone.description.trim(),
        })),
      exit_criteria: stage.criteria
        .filter((criterion) => criterion.label.trim())
        .map((criterion, criterionIndex) => ({
          id: criterion.id || `criterion-${stageIndex + 1}-${criterionIndex + 1}`,
          label: criterion.label.trim(),
          type: criterion.type,
          ...(criterion.type === 'artifact' && criterion.artifactId.trim()
            ? { artifact_id: criterion.artifactId.trim() }
            : {}),
        })),
    } as PlaybookStageSpec;
  });
  return {
    ...spec,
    name: form.name.trim(),
    description: form.description.trim(),
    stages,
  };
}

export function PlaybookSpecEditor({
  spec,
  saving,
  error,
  onSave,
  onCancel,
}: PlaybookSpecEditorProps) {
  const { t, tf } = usePlaybookI18n();
  const [mode, setMode] = useState<'form' | 'json'>('form');
  const [form, setForm] = useState<FormState>(() => toForm(spec));
  const [jsonDraft, setJsonDraft] = useState(() => JSON.stringify(spec, null, 2));
  const [localError, setLocalError] = useState<string | null>(null);

  const updateStage = (index: number, patch: Partial<StageForm>) => {
    setForm((prev) => ({
      ...prev,
      stages: prev.stages.map((stage, stageIndex) =>
        stageIndex === index ? { ...stage, ...patch } : stage,
      ),
    }));
  };

  const updateArtifact = (
    stageIndex: number,
    artifactIndex: number,
    patch: Partial<ArtifactForm>,
  ) => {
    setForm((prev) => ({
      ...prev,
      stages: prev.stages.map((stage, index) =>
        index === stageIndex
          ? {
              ...stage,
              artifacts: stage.artifacts.map((artifact, artifactIndex2) =>
                artifactIndex2 === artifactIndex ? { ...artifact, ...patch } : artifact,
              ),
            }
          : stage,
      ),
    }));
  };

  const updateRule = (stageIndex: number, ruleIndex: number, patch: Partial<RuleForm>) => {
    setForm((prev) => ({
      ...prev,
      stages: prev.stages.map((stage, index) =>
        index === stageIndex
          ? {
              ...stage,
              rules: stage.rules.map((rule, ruleIndex2) =>
                ruleIndex2 === ruleIndex ? { ...rule, ...patch } : rule,
              ),
            }
          : stage,
      ),
    }));
  };

  const updateMilestone = (
    stageIndex: number,
    milestoneIndex: number,
    patch: Partial<MilestoneForm>,
  ) => {
    setForm((prev) => ({
      ...prev,
      stages: prev.stages.map((stage, index) =>
        index === stageIndex
          ? {
              ...stage,
              milestones: stage.milestones.map((milestone, milestoneIndex2) =>
                milestoneIndex2 === milestoneIndex ? { ...milestone, ...patch } : milestone,
              ),
            }
          : stage,
      ),
    }));
  };

  const updateCriterion = (
    stageIndex: number,
    criterionIndex: number,
    patch: Partial<CriterionForm>,
  ) => {
    setForm((prev) => ({
      ...prev,
      stages: prev.stages.map((stage, index) =>
        index === stageIndex
          ? {
              ...stage,
              criteria: stage.criteria.map((criterion, criterionIndex2) =>
                criterionIndex2 === criterionIndex ? { ...criterion, ...patch } : criterion,
              ),
            }
          : stage,
      ),
    }));
  };

  const handleSave = () => {
    setLocalError(null);
    if (mode === 'json') {
      try {
        const parsed = JSON.parse(jsonDraft) as PlaybookSpec;
        onSave(parsed);
      } catch (err) {
        setLocalError(
          tf('playbook.editor.error.json', {
            message: err instanceof Error ? err.message : String(err),
          }),
        );
      }
      return;
    }
    if (!form.name.trim()) {
      setLocalError(t('playbook.editor.error.name'));
      return;
    }
    for (const stage of form.stages) {
      if (!stage.label.trim()) {
        setLocalError(t('playbook.editor.error.stageName'));
        return;
      }
      for (const artifact of stage.artifacts) {
        if (!artifact.label.trim() || !artifact.globs.trim()) {
          setLocalError(t('playbook.editor.error.artifact'));
          return;
        }
      }
    }
    onSave(toSpec(spec, form));
  };

  return (
    <div className="space-y-3 rounded-md border border-border p-3" data-testid="playbook-editor">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs font-medium text-foreground">{t('playbook.editor.title')}</div>
        <div className="flex gap-1">
          <Button
            size="sm"
            variant={mode === 'form' ? 'primary' : 'secondary'}
            onClick={() => setMode('form')}
            data-testid="playbook-editor-mode-form"
          >
            {t('playbook.editor.form')}
          </Button>
          <Button
            size="sm"
            variant={mode === 'json' ? 'primary' : 'secondary'}
            onClick={() => {
              setJsonDraft(JSON.stringify(toSpec(spec, form), null, 2));
              setMode('json');
            }}
            data-testid="playbook-editor-mode-json"
          >
            JSON
          </Button>
        </div>
      </div>

      {mode === 'form' ? (
        <div className="space-y-3" data-testid="playbook-editor-form">
          <label className="block text-xs text-muted-foreground">
            {t('playbook.editor.name')}
            <input
              value={form.name}
              onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
              className="mt-1 w-full rounded-md border border-input bg-background px-2 py-1 text-xs text-foreground"
              data-testid="playbook-editor-name"
            />
          </label>
          <label className="block text-xs text-muted-foreground">
            {t('playbook.editor.description')}
            <textarea
              value={form.description}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, description: event.target.value }))
              }
              rows={2}
              className="mt-1 w-full rounded-md border border-input bg-background px-2 py-1 text-xs text-foreground"
            />
          </label>
          {form.stages.map((stage, stageIndex) => (
            <div
              key={stage.id || stageIndex}
              role="group"
              aria-label={tf('playbook.editor.stageGroup', { n: stageIndex + 1 })}
              className="space-y-2 rounded-md border border-border p-2"
            >
              <div className="flex flex-wrap items-center gap-2">
                <input
                  value={stage.label}
                  onChange={(event) => updateStage(stageIndex, { label: event.target.value })}
                  aria-label={tf('playbook.editor.stageName', { n: stageIndex + 1 })}
                  placeholder={t('playbook.editor.stagePlaceholder')}
                  className="flex-1 rounded-md border border-input bg-background px-2 py-1 text-xs"
                />
                <input
                  value={stage.objective}
                  onChange={(event) => updateStage(stageIndex, { objective: event.target.value })}
                  aria-label={tf('playbook.editor.stageObjective', { n: stageIndex + 1 })}
                  placeholder={t('playbook.editor.stageObjectivePlaceholder')}
                  className="flex-[2] rounded-md border border-input bg-background px-2 py-1 text-xs"
                />
                <Button
                  size="sm"
                  variant="secondary"
                  aria-label={tf('playbook.editor.deleteStage', { n: stageIndex + 1 })}
                  onClick={() =>
                    setForm((prev) => ({
                      ...prev,
                      stages: prev.stages.filter((_, index) => index !== stageIndex),
                    }))
                  }
                >
                  {t('playbook.editor.delete')}
                </Button>
              </div>
              <PlaybookStageSections
                stage={stage}
                stageIndex={stageIndex}
                updateStage={updateStage}
                updateArtifact={updateArtifact}
                updateRule={updateRule}
                updateMilestone={updateMilestone}
                updateCriterion={updateCriterion}
              />
            </div>
          ))}
          <Button
            size="sm"
            variant="secondary"
            onClick={() =>
              setForm((prev) => ({
                ...prev,
                stages: [
                  ...prev.stages,
                  {
                    id: `stage-${prev.stages.length + 1}`,
                    label: '',
                    objective: '',
                    artifacts: [],
                    rules: [],
                    milestones: [],
                    criteria: [],
                  },
                ],
              }))
            }
          >
            {t('playbook.editor.addStage')}
          </Button>
        </div>
      ) : (
        <textarea
          value={jsonDraft}
          onChange={(event) => setJsonDraft(event.target.value)}
          rows={14}
          spellCheck={false}
          className="w-full rounded-md border border-input bg-background px-2 py-1 font-mono text-xs text-foreground"
          data-testid="playbook-spec-editor"
        />
      )}

      {(localError || error) && (
        <div className="text-xs text-destructive">{localError || error}</div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="primary"
          onClick={handleSave}
          disabled={saving}
          data-testid="playbook-save-spec"
        >
          {saving ? t('playbook.editor.saving') : t('playbook.editor.save')}
        </Button>
        <Button size="sm" variant="secondary" onClick={onCancel}>
          {t('playbook.editor.cancel')}
        </Button>
      </div>
    </div>
  );
}

export default PlaybookSpecEditor;
