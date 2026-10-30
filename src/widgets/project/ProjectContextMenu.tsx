/**
 * ProjectContextMenu — right-click menu for a registered project row.
 *
 * Mirrors VS Code's Explorer affordances: open the project, start a new
 * session, open/reveal the folder in the OS file manager, settings, copy
 * path, remove. Folder actions go through the validated IPC bridge; the
 * renderer never passes a raw path.
 */
import * as ContextMenuPrimitive from '@radix-ui/react-context-menu';
import { Copy, FolderMinus, FolderOpen, MessageSquarePlus, Play, Settings } from 'lucide-react';
import type { ReactNode } from 'react';
import { toast } from 'sonner';

import type { ProjectSummary } from '../../shared/api/projectApi';

export interface ProjectContextMenuProps {
  project: ProjectSummary;
  children: ReactNode;
  onOpen: () => void;
  onNewSession: () => void;
  onSettings: () => void;
  onRemove: () => void;
}

const itemClass =
  'relative flex cursor-default select-none items-center gap-2 rounded-md px-2 py-1.5 text-sm text-ink outline-none transition-colors data-[highlighted]:bg-bg-hover data-[disabled]:pointer-events-none data-[disabled]:opacity-50';

async function runFolderAction(
  projectId: string,
  kind: 'openFolder' | 'revealFolder',
): Promise<void> {
  const bridge = window.electronAPI?.project;
  if (!bridge) {
    toast.error('当前环境不支持该操作');
    return;
  }
  try {
    const result = await bridge[kind](projectId);
    if ('error' in result) toast.error(result.error);
  } catch (err) {
    toast.error(err instanceof Error ? err.message : '操作失败');
  }
}

export function ProjectContextMenu({
  project,
  children,
  onOpen,
  onNewSession,
  onSettings,
  onRemove,
}: ProjectContextMenuProps) {
  const handleCopyPath = async () => {
    try {
      await navigator.clipboard.writeText(project.path);
      toast.success('已复制项目路径');
    } catch {
      toast.error('复制失败');
    }
  };

  return (
    <ContextMenuPrimitive.Root>
      <ContextMenuPrimitive.Trigger asChild>{children}</ContextMenuPrimitive.Trigger>
      <ContextMenuPrimitive.Portal>
        <ContextMenuPrimitive.Content
          data-testid={`project-context-menu-${project.id}`}
          className="animate-fade-enter z-50 min-w-[12rem] overflow-hidden rounded-lg border border-line bg-bg p-1 shadow-lg"
        >
          <ContextMenuPrimitive.Item className={itemClass} onSelect={onOpen}>
            <Play className="h-3.5 w-3.5" />
            打开项目
          </ContextMenuPrimitive.Item>
          <ContextMenuPrimitive.Item className={itemClass} onSelect={onNewSession}>
            <MessageSquarePlus className="h-3.5 w-3.5" />
            新建会话
          </ContextMenuPrimitive.Item>
          <ContextMenuPrimitive.Separator className="-mx-1 my-1 h-px bg-line" />
          <ContextMenuPrimitive.Item
            className={itemClass}
            onSelect={() => void runFolderAction(project.id, 'openFolder')}
          >
            <FolderOpen className="h-3.5 w-3.5" />
            打开项目文件夹
          </ContextMenuPrimitive.Item>
          <ContextMenuPrimitive.Item
            className={itemClass}
            onSelect={() => void runFolderAction(project.id, 'revealFolder')}
          >
            <FolderOpen className="h-3.5 w-3.5" />
            在文件管理器中显示
          </ContextMenuPrimitive.Item>
          <ContextMenuPrimitive.Separator className="-mx-1 my-1 h-px bg-line" />
          <ContextMenuPrimitive.Item className={itemClass} onSelect={onSettings}>
            <Settings className="h-3.5 w-3.5" />
            项目设置与 AI 初始化…
          </ContextMenuPrimitive.Item>
          <ContextMenuPrimitive.Item className={itemClass} onSelect={() => void handleCopyPath()}>
            <Copy className="h-3.5 w-3.5" />
            复制路径
          </ContextMenuPrimitive.Item>
          <ContextMenuPrimitive.Separator className="-mx-1 my-1 h-px bg-line" />
          <ContextMenuPrimitive.Item
            className={`${itemClass} text-error data-[highlighted]:bg-error/10`}
            onSelect={onRemove}
          >
            <FolderMinus className="h-3.5 w-3.5" />
            移除项目
          </ContextMenuPrimitive.Item>
        </ContextMenuPrimitive.Content>
      </ContextMenuPrimitive.Portal>
    </ContextMenuPrimitive.Root>
  );
}
