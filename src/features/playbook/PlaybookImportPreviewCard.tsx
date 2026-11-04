/**
 * PlaybookImportPreviewCard — 导入前的逐项 diff、冲突策略与保存到规程库选项。
 */
import type {
  PlaybookDiff,
  PlaybookImportPreview,
  PlaybookStageDiff,
} from '../../shared/api/playbookApi';
import { Button } from '../../shared/ui/Button';

import { usePlaybookI18n, type PlaybookI18n } from './usePlaybookI18n';

export interface PlaybookImportPreviewProps {
  preview: PlaybookImportPreview;
  conflict: 'save_as_new' | 'merge' | 'replace';
  onConflictChange: (value: 'save_as_new' | 'merge' | 'replace') => void;
  saveToLibrary: boolean;
  onSaveToLibraryChange: (value: boolean) => void;
  onConfirm: () => void;
  onCancel: () => void;
  importing: boolean;
}

function stageChangeCount(detail: PlaybookStageDiff): number {
  return (
    detail.changed_fields.length +
    detail.artifacts_added.length +
    detail.artifacts_removed.length +
    detail.artifacts_changed.length +
    detail.rules_added.length +
    detail.rules_removed.length +
    detail.milestones_added.length +
    detail.milestones_removed.length +
    detail.criteria_added.length +
    detail.criteria_removed.length +
    detail.criteria_changed.length
  );
}

function summaryCounts(diff: PlaybookDiff, tf: PlaybookI18n['tf']): string[] {
  const counts: string[] = [];
  const push = (key: Parameters<PlaybookI18n['tf']>[0], count: number) => {
    if (count > 0) counts.push(tf(key, { count }));
  };
  push('playbook.import.count.stagesAdded', diff.stages_added.length);
  push('playbook.import.count.stagesRemoved', diff.stages_removed.length);
  push('playbook.import.count.stagesChanged', diff.stages_changed.length);
  push('playbook.import.count.directoriesAdded', diff.directories_added.length);
  push('playbook.import.count.directoriesRemoved', diff.directories_removed.length);
  push('playbook.import.count.directoriesChanged', diff.directories_changed.length);
  push('playbook.import.count.globalRulesAdded', diff.global_rules_added.length);
  push('playbook.import.count.globalRulesRemoved', diff.global_rules_removed.length);
  if (diff.name_changed) counts.push(tf('playbook.import.count.nameChanged'));
  if (diff.description_changed) counts.push(tf('playbook.import.count.descriptionChanged'));
  return counts;
}

function StageDiffList({ detail, tf }: { detail: PlaybookStageDiff; tf: PlaybookI18n['tf'] }) {
  const separator = tf('playbook.import.listSeparator');
  const fieldsSuffix = (fields: string[] | undefined) =>
    fields?.length ? tf('playbook.import.fieldSuffix', { fields: fields.join(separator) }) : '';
  const listClass = {
    added: 'text-emerald-600 dark:text-emerald-400',
    removed: 'text-destructive',
    changed: 'text-amber-600 dark:text-amber-400',
  };
  return (
    <ul className="mt-1 space-y-0.5">
      {detail.changed_fields.length > 0 && (
        <li className={listClass.changed}>
          {tf('playbook.import.stageFields', {
            fields: detail.changed_fields.join(separator),
          })}
        </li>
      )}
      {detail.artifacts_added.map((item) => (
        <li key={`artifact-add-${item.id}`} className={listClass.added}>
          {tf('playbook.import.artifactAdded', { label: item.label })}
        </li>
      ))}
      {detail.artifacts_removed.map((item) => (
        <li key={`artifact-del-${item.id}`} className={listClass.removed}>
          {tf('playbook.import.artifactRemoved', { label: item.label })}
        </li>
      ))}
      {detail.artifacts_changed.map((item) => (
        <li key={`artifact-mod-${item.id}`} className={listClass.changed}>
          {tf('playbook.import.artifactChanged', { label: item.label })}
          {fieldsSuffix(item.fields)}
        </li>
      ))}
      {detail.rules_added.map((label) => (
        <li key={`rule-add-${label}`} className={listClass.added}>
          {tf('playbook.import.ruleAdded', { label })}
        </li>
      ))}
      {detail.rules_removed.map((label) => (
        <li key={`rule-del-${label}`} className={listClass.removed}>
          {tf('playbook.import.ruleRemoved', { label })}
        </li>
      ))}
      {detail.milestones_added.map((title) => (
        <li key={`milestone-add-${title}`} className={listClass.added}>
          {tf('playbook.import.milestoneAdded', { title })}
        </li>
      ))}
      {detail.milestones_removed.map((title) => (
        <li key={`milestone-del-${title}`} className={listClass.removed}>
          {tf('playbook.import.milestoneRemoved', { title })}
        </li>
      ))}
      {detail.criteria_added.map((item) => (
        <li key={`criterion-add-${item.id}`} className={listClass.added}>
          {tf('playbook.import.criterionAdded', { label: item.label })}
        </li>
      ))}
      {detail.criteria_removed.map((item) => (
        <li key={`criterion-del-${item.id}`} className={listClass.removed}>
          {tf('playbook.import.criterionRemoved', { label: item.label })}
        </li>
      ))}
      {detail.criteria_changed.map((item) => (
        <li key={`criterion-mod-${item.id}`} className={listClass.changed}>
          {tf('playbook.import.criterionChanged', { label: item.label })}
          {fieldsSuffix(item.fields)}
        </li>
      ))}
    </ul>
  );
}

export function PlaybookImportPreviewCard({
  preview,
  conflict,
  onConflictChange,
  saveToLibrary,
  onSaveToLibraryChange,
  onConfirm,
  onCancel,
  importing,
}: PlaybookImportPreviewProps) {
  const { t, tf } = usePlaybookI18n();
  const counts = summaryCounts(preview.diff, tf);
  const stageDetails = Object.entries(preview.diff.stage_details ?? {});
  return (
    <div
      className="space-y-2 rounded-md border border-primary/30 bg-primary/5 p-3 text-xs"
      data-testid="playbook-import-preview"
    >
      <div className="font-medium text-foreground">
        {tf('playbook.import.title', { name: preview.playbook.name })}
      </div>
      <div className="text-muted-foreground">
        {tf('playbook.import.summary', {
          stages: preview.playbook.stages.length,
          dirs: preview.scaffold.directories.length,
        })}
      </div>
      <div className="text-muted-foreground">
        {tf('playbook.import.changes', {
          items:
            counts.join(tf('playbook.import.listSeparator')) ||
            t('playbook.import.noStructuralChanges'),
        })}
      </div>
      {stageDetails.length > 0 && (
        <div className="space-y-1" data-testid="playbook-diff-details">
          {stageDetails.map(([stageId, detail]) => (
            <details
              key={stageId}
              className="rounded-md border border-border px-2 py-1"
              data-testid={`playbook-diff-stage-${stageId}`}
            >
              <summary className="cursor-pointer text-muted-foreground">
                {tf('playbook.import.stageSummary', {
                  label: detail.label || stageId,
                  count: stageChangeCount(detail),
                })}
              </summary>
              <StageDiffList detail={detail} tf={tf} />
            </details>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label={t('playbook.import.conflictLabel')}
          value={conflict}
          onChange={(event) =>
            onConflictChange(event.target.value as 'save_as_new' | 'merge' | 'replace')
          }
          className="rounded-md border border-input bg-background px-2 py-1 text-xs"
        >
          <option value="save_as_new">{t('playbook.import.conflict.saveAsNew')}</option>
          <option value="merge">{t('playbook.import.conflict.merge')}</option>
          <option value="replace">{t('playbook.import.conflict.replace')}</option>
        </select>
        <label className="flex items-center gap-1 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={saveToLibrary}
            onChange={(event) => onSaveToLibraryChange(event.target.checked)}
            data-testid="playbook-import-save-library"
          />
          {t('playbook.import.saveToLibrary')}
        </label>
        <Button
          size="sm"
          variant="primary"
          onClick={onConfirm}
          disabled={importing}
          data-testid="playbook-import-confirm"
        >
          {importing ? t('playbook.import.importing') : t('playbook.import.confirm')}
        </Button>
        <Button size="sm" variant="secondary" onClick={onCancel}>
          {t('playbook.import.cancel')}
        </Button>
      </div>
    </div>
  );
}

export default PlaybookImportPreviewCard;
