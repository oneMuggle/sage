/**
 * PlaybookImportPreviewCard — 导入前的结构摘要、冲突策略与保存到规程库选项。
 */
import type { PlaybookImportPreview } from '../../shared/api/playbookApi';
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
  return (
    <div
      className="space-y-2 rounded-md border border-primary/30 bg-primary/5 p-3 text-xs"
      data-testid="playbook-import-preview"
    >
      <div className="font-medium text-foreground">导入预览：{preview.playbook.name}</div>
      <div className="text-muted-foreground">
        阶段 {preview.playbook.stages.length} 个 · 目录{' '}
        {preview.scaffold.directories.length} 个 · 导入不包含对方项目文件内容
      </div>
      {Object.entries(preview.diff).length > 0 && (
        <div className="text-muted-foreground">
          变更：
          {Object.entries(preview.diff)
            .filter(([, value]) => Array.isArray(value) && value.length > 0)
            .map(([key, value]) => `${key} ${(value as unknown[]).length} 项`)
            .join('，') || '无结构变更'}
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
