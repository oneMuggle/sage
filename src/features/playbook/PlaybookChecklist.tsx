/**
 * PlaybookChecklist — 当前阶段待补项、退出条件与归类建议。
 *
 * 所有动作都通过回调交给父组件执行，组件本身不直接调用 API。
 */
import { AlertCircle, CheckCircle2 } from 'lucide-react';

import type { PlaybookAction, PlaybookStageAudit } from '../../shared/api/playbookApi';
import { Button } from '../../shared/ui/Button';

export interface PlaybookChecklistProps {
  stage: PlaybookStageAudit | undefined;
  classification: Array<{
    from: string;
    to: string;
    artifact_id: string;
    label: string;
    stage_id: string;
    reason: string;
  }>;
  busy: string | null;
  playbookName: string;
  onAction: (action: PlaybookAction) => void;
  onWaive: (stageId: string, artifactId: string) => void;
  onManualDone: (stageId: string, criterionId: string) => void;
}

const ACTION_LABELS: Record<string, string> = {
  create_folder: '创建目录',
  create_doc_stub: '生成骨架',
  apply_rules: '写入规则',
  seed_milestones: '创建里程碑',
  add_todo: '转为待办',
  open_doc: '打开文档',
};

export function PlaybookChecklist({
  stage,
  classification,
  busy,
  playbookName,
  onAction,
  onWaive,
  onManualDone,
}: PlaybookChecklistProps) {
  if (!stage) return null;
  return (
    <>
      <div className="space-y-2" data-testid="playbook-current-stage">
        <div className="text-xs font-medium text-foreground">
          当前阶段：{stage.label}
          {stage.objective ? (
            <span className="ml-2 font-normal text-muted-foreground">
              {stage.objective}
            </span>
          ) : null}
        </div>
        {stage.remaining.length === 0 ? (
          <div className="flex items-center gap-1.5 text-xs text-emerald-600">
            <CheckCircle2 className="h-3.5 w-3.5" />
            本阶段必需要素已齐备
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
                  待补：{item.label}
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
                      {ACTION_LABELS[item.missing_action.type] ?? '处理'}
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() =>
                      onAction({
                        type: 'add_todo',
                        payload: {
                          title: '补齐：' + item.label,
                          description:
                            '项目规程 ' + playbookName + ' · 阶段 ' + stage.label,
                        },
                      })
                    }
                    disabled={busy === 'add_todo'}
                    data-testid={`playbook-add-todo-${item.id}`}
                  >
                    转待办
                  </Button>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => onWaive(stage.id, item.id)}
                    disabled={busy === 'waive'}
                    data-testid={`playbook-waive-${item.id}`}
                  >
                    豁免
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {stage.exit_criteria.length > 0 && (
        <div className="space-y-1.5" data-testid="playbook-exit-criteria">
          <div className="text-xs font-medium text-foreground">退出条件</div>
          {stage.exit_criteria.map((criterion) => (
            <div
              key={criterion.id ?? criterion.label}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border px-2 py-1.5 text-xs"
            >
              <span className="text-muted-foreground">
                {criterion.status === 'done' ? '✓ ' : '○ '}
                {criterion.label}
              </span>
              {criterion.type === 'manual' &&
                criterion.status !== 'done' &&
                criterion.id && (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => onManualDone(stage.id, criterion.id as string)}
                    disabled={busy === 'manual-done'}
                    data-testid={`playbook-manual-${criterion.id}`}
                  >
                    标记完成
                  </Button>
                )}
            </div>
          ))}
        </div>
      )}

      {classification.length > 0 && (
        <div className="space-y-1.5" data-testid="playbook-classification">
          <div className="text-xs font-medium text-foreground">归类建议（需逐项确认）</div>
          {classification.map((item) => (
            <div
              key={`${item.from}-${item.to}`}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border px-2 py-1.5 text-xs"
            >
              <span className="text-muted-foreground">
                {item.from} → {item.to}
              </span>
              <Button
                size="sm"
                variant="secondary"
                onClick={() =>
                  onAction({
                    type: 'move_file',
                    payload: { from: item.from, to: item.to },
                  })
                }
                disabled={busy === 'move_file'}
                data-testid={`playbook-move-${item.artifact_id}`}
              >
                移动
              </Button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

export default PlaybookChecklist;
