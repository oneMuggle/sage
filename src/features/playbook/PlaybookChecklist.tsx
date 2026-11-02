/**
 * PlaybookChecklist — 当前阶段待补项与退出条件。
 *
 * 所有动作都通过回调交给父组件执行，组件本身不直接调用 API。
 */
import { AlertCircle, CheckCircle2 } from 'lucide-react';

import type { PlaybookAction, PlaybookStageAudit } from '../../shared/api/playbookApi';
import type { PlaybookTranslationKey } from '../../shared/lib/i18n/locales/zh/playbook';
import { Button } from '../../shared/ui/Button';

import { usePlaybookI18n } from './usePlaybookI18n';

export interface PlaybookChecklistProps {
  stage: PlaybookStageAudit | undefined;
  busy: string | null;
  playbookName: string;
  onAction: (action: PlaybookAction) => void;
  onWaive: (stageId: string, artifactId: string) => void;
  onManualDone: (stageId: string, criterionId: string) => void;
}

const ACTION_KEYS: Record<string, PlaybookTranslationKey> = {
  create_folder: 'playbook.checklist.action.create_folder',
  create_doc_stub: 'playbook.checklist.action.create_doc_stub',
  apply_rules: 'playbook.checklist.action.apply_rules',
  seed_milestones: 'playbook.checklist.action.seed_milestones',
  add_todo: 'playbook.checklist.action.add_todo',
  open_doc: 'playbook.checklist.action.open_doc',
};

export function PlaybookChecklist({
  stage,
  busy,
  playbookName,
  onAction,
  onWaive,
  onManualDone,
}: PlaybookChecklistProps) {
  const { t, tf } = usePlaybookI18n();
  if (!stage) return null;
  const actionLabel = (type: string): string => {
    const key = ACTION_KEYS[type];
    return key ? t(key) : t('playbook.checklist.fallbackAction');
  };
  return (
    <>
      <div className="space-y-2" data-testid="playbook-current-stage">
        <div className="text-xs font-medium text-foreground">
          {tf('playbook.checklist.currentStage', { stage: stage.label })}
          {stage.objective ? (
            <span className="ml-2 font-normal text-muted-foreground">{stage.objective}</span>
          ) : null}
        </div>
        {stage.remaining.length === 0 ? (
          <div className="flex items-center gap-1.5 text-xs text-emerald-600">
            <CheckCircle2 className="h-3.5 w-3.5" />
            {t('playbook.checklist.allReady')}
          </div>
        ) : (
          <ul className="space-y-1.5">
            {stage.remaining.map((item) => (
              <li
                key={item.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border px-2 py-1.5 text-xs"
              >
                <span className="flex items-center gap-1.5 text-foreground">
                  <AlertCircle className="h-3.5 w-3.5 text-amber-500" />
                  {tf('playbook.checklist.missing', { label: item.label })}
                </span>
                <span className="flex items-center gap-1.5">
                  {item.missing_action && (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => onAction(item.missing_action as PlaybookAction)}
                      disabled={busy === item.missing_action.type}
                      data-testid={`playbook-missing-action-${item.id}`}
                    >
                      {actionLabel(item.missing_action.type)}
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() =>
                      onAction({
                        type: 'add_todo',
                        payload: {
                          title: tf('playbook.checklist.addTodoTitle', {
                            label: item.label,
                          }),
                          description: tf('playbook.checklist.addTodoDescription', {
                            playbook: playbookName,
                            stage: stage.label,
                          }),
                        },
                      })
                    }
                    disabled={busy === 'add_todo'}
                    data-testid={`playbook-add-todo-${item.id}`}
                  >
                    {t('playbook.checklist.toTodo')}
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => onWaive(stage.id, item.id)}
                    disabled={busy === 'waive'}
                    data-testid={`playbook-waive-${item.id}`}
                  >
                    {t('playbook.checklist.waive')}
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {stage.exit_criteria.length > 0 && (
        <div className="space-y-1.5" data-testid="playbook-exit-criteria">
          <div className="text-xs font-medium text-foreground">
            {t('playbook.checklist.exitCriteria')}
          </div>
          {stage.exit_criteria.map((criterion) => (
            <div
              key={criterion.id ?? criterion.label}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border px-2 py-1.5 text-xs"
            >
              <span className="text-muted-foreground">
                {criterion.status === 'done' ? '✓ ' : '○ '}
                {criterion.label}
              </span>
              {criterion.type === 'manual' && criterion.status !== 'done' && criterion.id && (
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => onManualDone(stage.id, criterion.id as string)}
                  disabled={busy === 'manual-done'}
                  data-testid={`playbook-manual-${criterion.id}`}
                >
                  {t('playbook.checklist.markDone')}
                </Button>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

export default PlaybookChecklist;
