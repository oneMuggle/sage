import { Copy, ExternalLink, FolderOpen, X } from 'lucide-react';

import { copyToClipboard } from '../../shared/lib/clipboard';
import { useI18n } from '../../shared/lib/i18n';
import { useCurrentWorkspace } from '../../shared/lib/workspaceContext';
import type { OfficeDocType, OfficeManagedRef } from '../../shared/types/electron-api';
import { ContextMenu } from '../../shared/ui/ContextMenu/ContextMenu';
import type { ContextMenuItemSpec } from '../../shared/ui/ContextMenu/types';

interface OfficeRefChipData {
  docId: string;
  docType: OfficeDocType;
  filename: string;
}

interface OfficeRefChipProps {
  chip: OfficeRefChipData;
  onRemove?: () => void;
  /** composer：输入框上方 chip；message：用户消息元信息 chip */
  variant?: 'composer' | 'message';
  testId?: string;
}

function kindEmoji(docType: OfficeDocType): string {
  switch (docType) {
    case 'ppt':
      return '📊';
    case 'word':
      return '📝';
    case 'pdf':
      return '📄';
    default:
      return '📈';
  }
}

function buildManagedRef(
  chip: OfficeRefChipData,
  workspacePath: string | undefined,
): OfficeManagedRef | null {
  if (!workspacePath) return null;
  return {
    workspacePath,
    docType: chip.docType,
    documentId: chip.docId,
    filename: chip.filename,
  };
}

/**
 * Office 文档引用 chip —— 输入区与消息元信息共用。
 * 右键菜单复用既有 office:open / office:show-in-folder 原生通道。
 */
export function OfficeRefChip({
  chip,
  onRemove,
  variant = 'composer',
  testId,
}: OfficeRefChipProps) {
  const { t } = useI18n();
  const workspacePath = useCurrentWorkspace();

  const menuItems = (): ContextMenuItemSpec[] => {
    const officeApi = typeof window !== 'undefined' ? window.electronAPI?.office : undefined;
    const managedRef = buildManagedRef(chip, workspacePath);
    const unavailable = !officeApi || !managedRef;
    const run = (action: (ref: OfficeManagedRef) => Promise<void>) => async () => {
      if (!managedRef) return;
      try {
        await action(managedRef);
      } catch {
        // office IPC 失败由调用方 toast（此处静默，避免重复提示）
      }
    };
    return [
      {
        id: 'office-open',
        label: t('contextMenu.common.open'),
        icon: ExternalLink,
        disabled: unavailable,
        onSelect: run((ref) => officeApi!.openOfficeDocument(ref)),
      },
      {
        id: 'office-reveal',
        label: t('contextMenu.common.revealInFolder'),
        icon: FolderOpen,
        disabled: unavailable,
        onSelect: run((ref) => officeApi!.showOfficeDocumentInFolder(ref)),
      },
      {
        id: 'office-copy-name',
        label: t('contextMenu.common.copyName'),
        icon: Copy,
        onSelect: () =>
          void copyToClipboard(chip.filename, {
            successMessage: t('contextMenu.common.copied'),
            errorMessage: t('contextMenu.common.copyFailed'),
          }),
      },
      ...(onRemove
        ? [
            { id: 'office-remove-sep', kind: 'separator' as const },
            {
              id: 'office-remove',
              label: t('contextMenu.common.remove'),
              icon: X,
              destructive: true,
              onSelect: onRemove,
            },
          ]
        : []),
    ];
  };

  const isComposer = variant === 'composer';
  return (
    <ContextMenu items={menuItems}>
      <span
        className={
          isComposer
            ? 'office-ref-chip inline-flex items-center gap-1 px-2 py-0.5 rounded-radius-sm bg-primary/10 text-primary text-xs'
            : 'inline-flex items-center gap-1 px-2 py-0.5 rounded text-ui-2xs border border-border bg-bg-subtle text-text-secondary'
        }
        data-testid={testId ?? (isComposer ? 'office-ref-chip' : 'message-office-ref')}
        data-doc-id={chip.docId}
        title={chip.filename}
      >
        <span aria-hidden="true">{kindEmoji(chip.docType)}</span>
        <span className={isComposer ? undefined : 'truncate max-w-48'}>{chip.filename}</span>
        {onRemove && (
          <button
            type="button"
            className="ml-1 hover:text-error transition-colors"
            aria-label={`remove office ref ${chip.filename}`}
            onClick={onRemove}
          >
            <X className="w-3 h-3" />
          </button>
        )}
      </span>
    </ContextMenu>
  );
}
