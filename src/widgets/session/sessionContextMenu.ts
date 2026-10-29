import {
  Copy,
  Download,
  FileText,
  GitBranch,
  MessageSquare,
  Pencil,
  Pin,
  PinOff,
  Trash2,
} from 'lucide-react';

import type { TranslationKey } from '../../shared/lib/i18n';
import type { Session } from '../../shared/lib/store';
import type { ContextMenuItemSpec } from '../../shared/ui/ContextMenu/types';

type SessionMenuSession = Pick<Session, 'id' | 'title' | 'is_pinned' | 'fork_root'>;

export interface SessionContextMenuParams {
  session: SessionMenuSession;
  t: (key: TranslationKey) => string;
  exportingHtml?: boolean;
  exportingMarkdown?: boolean;
  pinning?: boolean;
  onOpen: () => void;
  onRename: () => void;
  onTogglePin: () => void;
  onCopyTitle: () => void | Promise<void>;
  onExportHtml: () => void | Promise<void>;
  onExportMarkdown: () => void | Promise<void>;
  onViewForkTree: () => void;
  onDelete: () => void | Promise<void>;
}

/**
 * 会话列表项右键菜单（对齐 ChatGPT / Cherry Studio 的会话管理菜单）。
 *
 * 只做动作编排，业务逻辑（导出、置顶、删除确认）全部由调用方注入 ——
 * 菜单是既有 hover 按钮的第二入口，不重复实现任何 handler。
 */
export function buildSessionContextMenuItems({
  session,
  t,
  exportingHtml = false,
  exportingMarkdown = false,
  pinning = false,
  onOpen,
  onRename,
  onTogglePin,
  onCopyTitle,
  onExportHtml,
  onExportMarkdown,
  onViewForkTree,
  onDelete,
}: SessionContextMenuParams): ContextMenuItemSpec[] {
  const pinned = session.is_pinned;
  const items: ContextMenuItemSpec[] = [
    {
      id: 'open',
      label: t('contextMenu.session.open'),
      icon: MessageSquare,
      onSelect: onOpen,
    },
    {
      id: 'rename',
      label: t('contextMenu.common.rename'),
      icon: Pencil,
      onSelect: onRename,
    },
    {
      id: 'pin',
      label: pinned ? t('contextMenu.session.unpin') : t('contextMenu.session.pin'),
      icon: pinned ? PinOff : Pin,
      disabled: pinning,
      onSelect: onTogglePin,
    },
    {
      id: 'copy-title',
      label: t('contextMenu.session.copyTitle'),
      icon: Copy,
      onSelect: onCopyTitle,
    },
    { id: 'sep-actions', kind: 'separator' },
    {
      id: 'export-markdown',
      label: t('contextMenu.session.exportMarkdown'),
      icon: FileText,
      disabled: exportingMarkdown,
      onSelect: onExportMarkdown,
    },
    {
      id: 'export-html',
      label: t('contextMenu.session.exportHtml'),
      icon: Download,
      disabled: exportingHtml,
      onSelect: onExportHtml,
    },
  ];

  if (session.fork_root) {
    items.push({
      id: 'fork-tree',
      label: t('contextMenu.session.viewForkTree'),
      icon: GitBranch,
      onSelect: onViewForkTree,
    });
  }

  items.push(
    { id: 'sep-delete', kind: 'separator' },
    {
      id: 'delete',
      label: t('contextMenu.session.delete'),
      icon: Trash2,
      destructive: true,
      onSelect: onDelete,
    },
  );

  return items;
}
