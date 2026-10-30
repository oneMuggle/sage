import { Copy, GitBranch } from 'lucide-react';

import type { GitFileChange } from '../../../shared/api/gitStatusApi';
import type { TranslationKey } from '../../../shared/lib/i18n';
import type { ContextMenuItemSpec } from '../../../shared/ui/ContextMenu/types';

export interface GitFileContextMenuParams {
  file: Pick<GitFileChange, 'path' | 'status'>;
  t: (key: TranslationKey) => string;
  onViewDiff: () => void;
  onCopyPath: () => void;
  onCopyName: () => void;
}

/** Git 变更文件行右键菜单：查看 diff / 复制路径 / 复制文件名。 */
export function buildGitFileContextMenuItems({
  t,
  onViewDiff,
  onCopyPath,
  onCopyName,
}: GitFileContextMenuParams): ContextMenuItemSpec[] {
  return [
    {
      id: 'git-view-diff',
      label: t('contextMenu.git.viewDiff'),
      icon: GitBranch,
      onSelect: onViewDiff,
    },
    {
      id: 'git-copy-path',
      label: t('contextMenu.common.copyPath'),
      icon: Copy,
      onSelect: onCopyPath,
    },
    {
      id: 'git-copy-name',
      label: t('contextMenu.common.copyName'),
      icon: Copy,
      onSelect: onCopyName,
    },
  ];
}
