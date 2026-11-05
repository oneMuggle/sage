/**
 * OfficeDuplicateDialog — 导入侧重复检测的决策弹窗 (AI workbench, Phase 0).
 *
 * 导入批次在读取前先问后端「这批文件的字节是否已经对应某个已有文档」。
 * 命中时批次暂停，由本弹窗让用户在三个动作中选一个：
 *
 *   - 打开已有文档   — 丢弃本次暂存副本，直接预览已有文档
 *   - 作为新版本导入 — 正常导入，并记录 derived_from 指向已有文档
 *   - 作为副本导入   — 正常导入，不与已有文档建立血缘
 *
 * 关闭弹窗（X / Esc / 点击遮罩）等价于「作为副本导入」：用户的文件
 * 不会因为误触而丢失，整批导入继续。
 */

import { Copy, FolderOpen, GitBranch } from 'lucide-react';

import type { OfficeDocumentSummary } from '../../shared/api/types';
import { fillTemplate } from '../../shared/lib/fillTemplate';
import { useI18n } from '../../shared/lib/i18n';
import { Button } from '../../shared/ui/Button';
import { Modal } from '../../shared/ui/Modal';

import type { OfficeDuplicateChoice, OfficePendingDuplicate } from './useOfficeDocuments';

export interface OfficeDuplicateDialogProps {
  /** 等待决策的暂存文件；null 表示弹窗关闭。 */
  pending: OfficePendingDuplicate | null;
  /** 把用户的选择交还给暂停中的导入批次。 */
  onChoose: (choice: OfficeDuplicateChoice) => void;
}

function documentLabel(doc: OfficeDocumentSummary): string {
  return doc.original_filename ?? doc.generated_filename;
}

export function OfficeDuplicateDialog({ pending, onChoose }: OfficeDuplicateDialogProps) {
  const { t } = useI18n();
  const existing = pending?.duplicates[0] ?? null;

  return (
    <Modal
      isOpen={pending !== null && existing !== null}
      onClose={() => onChoose('keep-copy')}
      title={t('office.duplicate.title')}
    >
      {pending && existing && (
        <div className="space-y-3 text-sm" data-testid="office-duplicate-dialog">
          <p className="text-muted">
            {fillTemplate(t('office.duplicate.description'), { filename: pending.filename })}
          </p>
          <div className="rounded-md border border-border bg-ui-panel px-3 py-2">
            <div className="text-xs text-muted">{t('office.duplicate.existingLabel')}</div>
            <div className="font-medium break-all">{documentLabel(existing)}</div>
            <div className="text-xs text-muted">
              {fillTemplate(t('office.duplicate.existingMeta'), {
                type: existing.doc_type.toUpperCase(),
                time: new Date(existing.updated_at).toLocaleString(),
              })}
            </div>
          </div>
          {pending.duplicates.length > 1 && (
            <p className="text-xs text-muted">
              {fillTemplate(t('office.duplicate.moreCount'), {
                count: pending.duplicates.length,
              })}
            </p>
          )}
          <div className="flex flex-col gap-2 pt-1">
            <Button variant="secondary" onClick={() => onChoose('open-existing')}>
              <FolderOpen className="w-4 h-4 mr-2" />
              {t('office.duplicate.openExisting')}
            </Button>
            <Button variant="secondary" onClick={() => onChoose('new-version')}>
              <GitBranch className="w-4 h-4 mr-2" />
              {t('office.duplicate.newVersion')}
            </Button>
            <Button variant="ghost" onClick={() => onChoose('keep-copy')}>
              <Copy className="w-4 h-4 mr-2" />
              {t('office.duplicate.keepCopy')}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
