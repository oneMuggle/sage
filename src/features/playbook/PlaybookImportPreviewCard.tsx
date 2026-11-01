/**
 * PlaybookImportPreviewCard — 导入前的逐项 diff、冲突策略与保存到规程库选项。
 */
import type { PlaybookImportPreview, PlaybookStageDiff } from '../../shared/api/playbookApi';
import { Button } from '../../shared/ui/Button';

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

function summaryCounts(preview: PlaybookImportPreview): string[] {
  const { diff } = preview;
  const counts: string[] = [];
  if (diff.stages_added.length) counts.push(`新增阶段 ${diff.stages_added.length}`);
  if (diff.stages_removed.length) counts.push(`删除阶段 ${diff.stages_removed.length}`);
  if (diff.stages_changed.length) counts.push(`阶段调整 ${diff.stages_changed.length}`);
  if (diff.directories_added.length) counts.push(`新增目录 ${diff.directories_added.length}`);
  if (diff.directories_removed.length) counts.push(`删除目录 ${diff.directories_removed.length}`);
  if (diff.directories_changed.length) counts.push(`调整目录 ${diff.directories_changed.length}`);
  if (diff.global_rules_added.length) counts.push(`新增全局规则 ${diff.global_rules_added.length}`);
  if (diff.global_rules_removed.length)
    counts.push(`删除全局规则 ${diff.global_rules_removed.length}`);
  if (diff.name_changed) counts.push('名称变更');
  if (diff.description_changed) counts.push('描述变更');
  return counts;
}

function StageDiffList({ detail }: { detail: PlaybookStageDiff }) {
  return (
    <ul className="mt-1 space-y-0.5">
      {detail.changed_fields.length > 0 && (
        <li className="text-amber-600 dark:text-amber-400">
          ~ 阶段字段：{detail.changed_fields.join('、')}
        </li>
      )}
      {detail.artifacts_added.map((item) => (
        <li key={`artifact-add-${item.id}`} className="text-emerald-600 dark:text-emerald-400">
          + 产物：{item.label}
        </li>
      ))}
      {detail.artifacts_removed.map((item) => (
        <li key={`artifact-del-${item.id}`} className="text-destructive">
          − 产物：{item.label}
        </li>
      ))}
      {detail.artifacts_changed.map((item) => (
        <li key={`artifact-mod-${item.id}`} className="text-amber-600 dark:text-amber-400">
          ~ 产物：{item.label}
          {item.fields?.length ? `（${item.fields.join('、')}）` : ''}
        </li>
      ))}
      {detail.rules_added.map((label) => (
        <li key={`rule-add-${label}`} className="text-emerald-600 dark:text-emerald-400">
          + 规则：{label}
        </li>
      ))}
      {detail.rules_removed.map((label) => (
        <li key={`rule-del-${label}`} className="text-destructive">
          − 规则：{label}
        </li>
      ))}
      {detail.milestones_added.map((title) => (
        <li key={`milestone-add-${title}`} className="text-emerald-600 dark:text-emerald-400">
          + 里程碑：{title}
        </li>
      ))}
      {detail.milestones_removed.map((title) => (
        <li key={`milestone-del-${title}`} className="text-destructive">
          − 里程碑：{title}
        </li>
      ))}
      {detail.criteria_added.map((item) => (
        <li key={`criterion-add-${item.id}`} className="text-emerald-600 dark:text-emerald-400">
          + 退出条件：{item.label}
        </li>
      ))}
      {detail.criteria_removed.map((item) => (
        <li key={`criterion-del-${item.id}`} className="text-destructive">
          − 退出条件：{item.label}
        </li>
      ))}
      {detail.criteria_changed.map((item) => (
        <li key={`criterion-mod-${item.id}`} className="text-amber-600 dark:text-amber-400">
          ~ 退出条件：{item.label}
          {item.fields?.length ? `（${item.fields.join('、')}）` : ''}
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
  const counts = summaryCounts(preview);
  const stageDetails = Object.entries(preview.diff.stage_details ?? {});
  return (
    <div
      className="space-y-2 rounded-md border border-primary/30 bg-primary/5 p-3 text-xs"
      data-testid="playbook-import-preview"
    >
      <div className="font-medium text-foreground">导入预览：{preview.playbook.name}</div>
      <div className="text-muted-foreground">
        阶段 {preview.playbook.stages.length} 个 · 目录 {preview.scaffold.directories.length} 个 ·
        导入不包含对方项目文件内容
      </div>
      <div className="text-muted-foreground">变更：{counts.join('，') || '无结构变更'}</div>
      {stageDetails.length > 0 && (
        <div className="space-y-1" data-testid="playbook-diff-details">
          {stageDetails.map(([stageId, detail]) => (
            <details
              key={stageId}
              className="rounded-md border border-border px-2 py-1"
              data-testid={`playbook-diff-stage-${stageId}`}
            >
              <summary className="cursor-pointer text-muted-foreground">
                阶段「{detail.label || stageId}」：{stageChangeCount(detail)} 项变更
              </summary>
              <StageDiffList detail={detail} />
            </details>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="导入冲突策略"
          value={conflict}
          onChange={(event) =>
            onConflictChange(event.target.value as 'save_as_new' | 'merge' | 'replace')
          }
          className="rounded-md border border-input bg-background px-2 py-1 text-xs"
        >
          <option value="save_as_new">另存为新规程</option>
          <option value="merge">合并到当前规程</option>
          <option value="replace">替换当前规程</option>
        </select>
        <label className="flex items-center gap-1 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={saveToLibrary}
            onChange={(event) => onSaveToLibraryChange(event.target.checked)}
            data-testid="playbook-import-save-library"
          />
          保存到规程库
        </label>
        <Button
          size="sm"
          variant="primary"
          onClick={onConfirm}
          disabled={importing}
          data-testid="playbook-import-confirm"
        >
          {importing ? '导入中…' : '导入并绑定'}
        </Button>
        <Button size="sm" variant="secondary" onClick={onCancel}>
          取消
        </Button>
      </div>
    </div>
  );
}

export default PlaybookImportPreviewCard;
