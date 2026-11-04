/** 规程编辑器阶段字段分区（2026-11-01，从 PlaybookSpecEditor 拆出）。 */
import { Button } from '../../shared/ui/Button';

import type {
  ArtifactForm,
  CriterionForm,
  MilestoneForm,
  RuleForm,
  StageForm,
} from './playbookEditorTypes';
import { usePlaybookI18n } from './usePlaybookI18n';

export interface PlaybookStageSectionsProps {
  stage: StageForm;
  stageIndex: number;
  updateStage: (index: number, patch: Partial<StageForm>) => void;
  updateArtifact: (stageIndex: number, artifactIndex: number, patch: Partial<ArtifactForm>) => void;
  updateRule: (stageIndex: number, ruleIndex: number, patch: Partial<RuleForm>) => void;
  updateMilestone: (
    stageIndex: number,
    milestoneIndex: number,
    patch: Partial<MilestoneForm>,
  ) => void;
  updateCriterion: (
    stageIndex: number,
    criterionIndex: number,
    patch: Partial<CriterionForm>,
  ) => void;
}

export function PlaybookStageSections({
  stage,
  stageIndex,
  updateStage,
  updateArtifact,
  updateRule,
  updateMilestone,
  updateCriterion,
}: PlaybookStageSectionsProps) {
  const { t, tf } = usePlaybookI18n();
  return (
    <>
      {stage.artifacts.map((artifact, artifactIndex) => (
        <div key={artifact.id || artifactIndex} className="space-y-1 border-t border-border pt-2">
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={artifact.label}
              onChange={(event) =>
                updateArtifact(stageIndex, artifactIndex, {
                  label: event.target.value,
                })
              }
              aria-label={tf('playbook.editor.artifactName', {
                n: stageIndex + 1,
                m: artifactIndex + 1,
              })}
              placeholder={t('playbook.editor.artifactPlaceholder')}
              className="flex-1 rounded-md border border-input bg-background px-2 py-1 text-xs"
            />
            <input
              value={artifact.targetDir}
              onChange={(event) =>
                updateArtifact(stageIndex, artifactIndex, {
                  targetDir: event.target.value,
                })
              }
              aria-label={tf('playbook.editor.artifactTarget', {
                n: stageIndex + 1,
                m: artifactIndex + 1,
              })}
              placeholder={t('playbook.editor.artifactTargetPlaceholder')}
              className="flex-1 rounded-md border border-input bg-background px-2 py-1 text-xs"
            />
            <label className="flex items-center gap-1 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={artifact.required}
                onChange={(event) =>
                  updateArtifact(stageIndex, artifactIndex, {
                    required: event.target.checked,
                  })
                }
                aria-label={tf('playbook.editor.artifactRequired', {
                  n: stageIndex + 1,
                  m: artifactIndex + 1,
                })}
              />
              {t('playbook.editor.required')}
            </label>
          </div>
          <input
            value={artifact.globs}
            onChange={(event) =>
              updateArtifact(stageIndex, artifactIndex, {
                globs: event.target.value,
              })
            }
            aria-label={tf('playbook.editor.globs', {
              n: stageIndex + 1,
              m: artifactIndex + 1,
            })}
            placeholder={t('playbook.editor.globsPlaceholder')}
            className="w-full rounded-md border border-input bg-background px-2 py-1 font-mono text-xs"
            data-testid={`playbook-editor-globs-${artifact.id || artifactIndex}`}
          />
        </div>
      ))}
      <Button
        size="sm"
        variant="secondary"
        onClick={() =>
          updateStage(stageIndex, {
            artifacts: [
              ...stage.artifacts,
              {
                id: `artifact-${stageIndex + 1}-${stage.artifacts.length + 1}`,
                label: '',
                globs: '',
                targetDir: '',
                required: true,
              },
            ],
          })
        }
      >
        {t('playbook.editor.addArtifact')}
      </Button>

      <div
        className="space-y-1.5 border-t border-border pt-2"
        data-testid={`playbook-editor-rules-${stage.id || stageIndex}`}
      >
        <div className="text-xs font-medium text-muted-foreground">
          {t('playbook.editor.rules')}
        </div>
        {stage.rules.map((rule, ruleIndex) => (
          <div key={ruleIndex} className="space-y-1 rounded-md border border-border p-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <input
                value={rule.templateKey}
                onChange={(event) =>
                  updateRule(stageIndex, ruleIndex, { templateKey: event.target.value })
                }
                aria-label={tf('playbook.editor.ruleTemplate', {
                  n: stageIndex + 1,
                  m: ruleIndex + 1,
                })}
                placeholder={t('playbook.editor.ruleTemplatePlaceholder')}
                className="flex-1 rounded-md border border-input bg-background px-2 py-1 text-xs"
              />
              <input
                value={rule.category}
                onChange={(event) =>
                  updateRule(stageIndex, ruleIndex, { category: event.target.value })
                }
                aria-label={tf('playbook.editor.ruleCategory', {
                  n: stageIndex + 1,
                  m: ruleIndex + 1,
                })}
                placeholder={t('playbook.editor.ruleCategoryPlaceholder')}
                className="w-24 rounded-md border border-input bg-background px-2 py-1 text-xs"
              />
              <input
                type="number"
                value={rule.priority}
                onChange={(event) =>
                  updateRule(stageIndex, ruleIndex, {
                    priority: Number(event.target.value) || 5,
                  })
                }
                aria-label={tf('playbook.editor.rulePriority', {
                  n: stageIndex + 1,
                  m: ruleIndex + 1,
                })}
                className="w-16 rounded-md border border-input bg-background px-2 py-1 text-xs"
              />
              <Button
                size="sm"
                variant="secondary"
                aria-label={tf('playbook.editor.deleteRule', {
                  n: stageIndex + 1,
                  m: ruleIndex + 1,
                })}
                onClick={() =>
                  updateStage(stageIndex, {
                    rules: stage.rules.filter((_, index) => index !== ruleIndex),
                  })
                }
              >
                {t('playbook.editor.delete')}
              </Button>
            </div>
            <input
              value={rule.content}
              onChange={(event) =>
                updateRule(stageIndex, ruleIndex, { content: event.target.value })
              }
              aria-label={tf('playbook.editor.ruleContent', {
                n: stageIndex + 1,
                m: ruleIndex + 1,
              })}
              placeholder={t('playbook.editor.ruleContentPlaceholder')}
              className="w-full rounded-md border border-input bg-background px-2 py-1 text-xs"
            />
            <input
              value={rule.triggerPattern}
              onChange={(event) =>
                updateRule(stageIndex, ruleIndex, {
                  triggerPattern: event.target.value,
                })
              }
              aria-label={tf('playbook.editor.ruleTrigger', {
                n: stageIndex + 1,
                m: ruleIndex + 1,
              })}
              placeholder={t('playbook.editor.ruleTriggerPlaceholder')}
              className="w-full rounded-md border border-input bg-background px-2 py-1 font-mono text-xs"
            />
          </div>
        ))}
        <Button
          size="sm"
          variant="secondary"
          onClick={() =>
            updateStage(stageIndex, {
              rules: [
                ...stage.rules,
                {
                  templateKey: '',
                  content: '',
                  category: 'playbook',
                  triggerPattern: 'always',
                  priority: 5,
                },
              ],
            })
          }
        >
          {t('playbook.editor.addRule')}
        </Button>
      </div>

      <div
        className="space-y-1.5 border-t border-border pt-2"
        data-testid={`playbook-editor-milestones-${stage.id || stageIndex}`}
      >
        <div className="text-xs font-medium text-muted-foreground">
          {t('playbook.editor.milestones')}
        </div>
        {stage.milestones.map((milestone, milestoneIndex) => (
          <div key={milestoneIndex} className="flex flex-wrap items-center gap-1.5">
            <input
              value={milestone.title}
              onChange={(event) =>
                updateMilestone(stageIndex, milestoneIndex, {
                  title: event.target.value,
                })
              }
              aria-label={tf('playbook.editor.milestoneTitle', {
                n: stageIndex + 1,
                m: milestoneIndex + 1,
              })}
              placeholder={t('playbook.editor.milestoneTitlePlaceholder')}
              className="flex-1 rounded-md border border-input bg-background px-2 py-1 text-xs"
            />
            <input
              value={milestone.description}
              onChange={(event) =>
                updateMilestone(stageIndex, milestoneIndex, {
                  description: event.target.value,
                })
              }
              aria-label={tf('playbook.editor.milestoneDescription', {
                n: stageIndex + 1,
                m: milestoneIndex + 1,
              })}
              placeholder={t('playbook.editor.milestoneDescriptionPlaceholder')}
              className="flex-[2] rounded-md border border-input bg-background px-2 py-1 text-xs"
            />
            <Button
              size="sm"
              variant="secondary"
              aria-label={tf('playbook.editor.deleteMilestone', {
                n: stageIndex + 1,
                m: milestoneIndex + 1,
              })}
              onClick={() =>
                updateStage(stageIndex, {
                  milestones: stage.milestones.filter((_, index) => index !== milestoneIndex),
                })
              }
            >
              {t('playbook.editor.delete')}
            </Button>
          </div>
        ))}
        <Button
          size="sm"
          variant="secondary"
          onClick={() =>
            updateStage(stageIndex, {
              milestones: [...stage.milestones, { title: '', description: '' }],
            })
          }
        >
          {t('playbook.editor.addMilestone')}
        </Button>
      </div>

      <div
        className="space-y-1.5 border-t border-border pt-2"
        data-testid={`playbook-editor-criteria-${stage.id || stageIndex}`}
      >
        <div className="text-xs font-medium text-muted-foreground">
          {t('playbook.editor.criteria')}
        </div>
        {stage.criteria.map((criterion, criterionIndex) => (
          <div key={criterionIndex} className="flex flex-wrap items-center gap-1.5">
            <input
              value={criterion.id}
              onChange={(event) =>
                updateCriterion(stageIndex, criterionIndex, {
                  id: event.target.value,
                })
              }
              aria-label={tf('playbook.editor.criterionId', {
                n: stageIndex + 1,
                m: criterionIndex + 1,
              })}
              placeholder={t('playbook.editor.criterionIdPlaceholder')}
              className="w-32 rounded-md border border-input bg-background px-2 py-1 text-xs"
            />
            <input
              value={criterion.label}
              onChange={(event) =>
                updateCriterion(stageIndex, criterionIndex, {
                  label: event.target.value,
                })
              }
              aria-label={tf('playbook.editor.criterionLabel', {
                n: stageIndex + 1,
                m: criterionIndex + 1,
              })}
              placeholder={t('playbook.editor.criterionLabelPlaceholder')}
              className="flex-1 rounded-md border border-input bg-background px-2 py-1 text-xs"
            />
            <select
              value={criterion.type}
              onChange={(event) =>
                updateCriterion(stageIndex, criterionIndex, {
                  type: event.target.value as CriterionForm['type'],
                })
              }
              aria-label={tf('playbook.editor.criterionType', {
                n: stageIndex + 1,
                m: criterionIndex + 1,
              })}
              className="rounded-md border border-input bg-background px-2 py-1 text-xs"
            >
              <option value="manual">{t('playbook.editor.criterionTypeManual')}</option>
              <option value="artifact">{t('playbook.editor.criterionTypeArtifact')}</option>
            </select>
            {criterion.type === 'artifact' && (
              <input
                value={criterion.artifactId}
                onChange={(event) =>
                  updateCriterion(stageIndex, criterionIndex, {
                    artifactId: event.target.value,
                  })
                }
                aria-label={tf('playbook.editor.criterionArtifact', {
                  n: stageIndex + 1,
                  m: criterionIndex + 1,
                })}
                placeholder={t('playbook.editor.criterionArtifactPlaceholder')}
                className="w-32 rounded-md border border-input bg-background px-2 py-1 text-xs"
              />
            )}
            <Button
              size="sm"
              variant="secondary"
              aria-label={tf('playbook.editor.deleteCriterion', {
                n: stageIndex + 1,
                m: criterionIndex + 1,
              })}
              onClick={() =>
                updateStage(stageIndex, {
                  criteria: stage.criteria.filter((_, index) => index !== criterionIndex),
                })
              }
            >
              {t('playbook.editor.delete')}
            </Button>
          </div>
        ))}
        <Button
          size="sm"
          variant="secondary"
          onClick={() =>
            updateStage(stageIndex, {
              criteria: [...stage.criteria, { id: '', label: '', type: 'manual', artifactId: '' }],
            })
          }
        >
          {t('playbook.editor.addCriterion')}
        </Button>
      </div>
    </>
  );
}

export default PlaybookStageSections;
