import { Archive, ArchiveRestore, Copy, History, Pin, PinOff, Trash2 } from 'lucide-react';

import type { Skill } from '../../shared/api';
import { copyToClipboard } from '../../shared/lib/clipboard';
import { fillTemplate } from '../../shared/lib/formatTemplate';
import { useI18n } from '../../shared/lib/i18n';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';
import { ContextMenu } from '../../shared/ui/ContextMenu/ContextMenu';
import type { ContextMenuItemSpec } from '../../shared/ui/ContextMenu/types';
import { TwoStepDelete } from '../sidebar/TwoStepDelete';

import SkillOriginBadge from './SkillOriginBadge';

export interface SkillRowProps {
  skill: Skill;
  onToggle: (name: string, enabled: boolean) => void;
  onOpenDetails?: (skill: Skill) => void;
  onDelete?: (name: string) => void;
  onArchive?: (name: string, archived: boolean) => void;
  onPin?: (name: string, pinned: boolean) => void;
}

/**
 * M2 紧凑技能行：名称 + 来源徽章 + 一行描述 + 使用次数 + 开关。
 *
 * 设计参考主流 AI 应用（Claude Skills / GPTs / Coze 插件中心）：
 * 列表做减法，触发词 / 正文 / 历史 / 导出等全部收进详情抽屉。
 * 右键菜单保留高频管理动作，权力用户不必先开详情。
 */
export default function SkillRow({
  skill,
  onToggle,
  onOpenDetails,
  onDelete,
  onArchive,
  onPin,
}: SkillRowProps) {
  const { t } = useI18n();
  const { name, description, enabled, usage_count, origin, source, lifecycle, pinned } = skill;

  const copy = (text: string) =>
    void copyToClipboard(text, {
      successMessage: t('contextMenu.common.copied'),
      errorMessage: t('contextMenu.common.copyFailed'),
    });

  const menuItems = (): ContextMenuItemSpec[] => {
    const items: ContextMenuItemSpec[] = [];
    if (onPin) {
      items.push({
        id: 'skill-pin',
        label: pinned ? t('contextMenu.skill.unpin') : t('contextMenu.skill.pin'),
        icon: pinned ? PinOff : Pin,
        onSelect: () => onPin(name, !pinned),
      });
    }
    if (onArchive) {
      items.push({
        id: 'skill-archive',
        label:
          lifecycle === 'archived'
            ? t('contextMenu.skill.unarchive')
            : t('contextMenu.skill.archive'),
        icon: lifecycle === 'archived' ? ArchiveRestore : Archive,
        onSelect: () => onArchive(name, lifecycle !== 'archived'),
      });
    }
    items.push(
      {
        id: 'skill-details',
        label: t('skills_page.view_details'),
        icon: History,
        onSelect: () => onOpenDetails?.(skill),
      },
      {
        id: 'skill-copy-name',
        label: t('contextMenu.common.copyName'),
        icon: Copy,
        onSelect: () => copy(name),
      },
    );
    if (onDelete && source !== 'builtin') {
      items.push(
        { id: 'skill-sep-delete', kind: 'separator' },
        {
          id: 'skill-delete',
          label: t('contextMenu.skill.delete'),
          icon: Trash2,
          destructive: true,
          onSelect: async () => {
            const confirmed = await confirmDialog({
              title: t('contextMenu.skill.deleteTitle'),
              message: fillTemplate(t('contextMenu.skill.deleteBody'), { name }),
              confirmLabel: t('common.delete'),
              danger: true,
            });
            if (confirmed) onDelete(name);
          },
        },
      );
    }
    return items;
  };

  return (
    <ContextMenu items={menuItems}>
      <div
        data-testid={`skill-row-${name}`}
        className={`group flex items-center gap-3 px-4 py-2.5 border-b border-border last:border-b-0 hover:bg-bg-subtle transition-colors ${
          enabled ? '' : 'opacity-70'
        } ${lifecycle === 'archived' ? 'opacity-50' : ''}`}
      >
        <button
          type="button"
          onClick={() => onOpenDetails?.(skill)}
          className="flex-1 min-w-0 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary rounded-sm"
          aria-label={`${t('skills_page.view_details')} ${name}`}
        >
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm font-semibold text-text truncate">{name}</span>
            <SkillOriginBadge origin={origin} />
            {pinned && (
              <span
                className="text-xs text-warning flex-shrink-0"
                title={t('contextMenu.skill.pin')}
              >
                📌
              </span>
            )}
            {lifecycle === 'archived' && (
              <span className="text-[11px] text-accent flex-shrink-0">
                {t('skills_page.lifecycle_archived')}
              </span>
            )}
            {lifecycle === 'stale' && (
              <span className="text-[11px] text-muted flex-shrink-0">
                {t('skills_page.lifecycle_stale')}
              </span>
            )}
          </div>
          <p className="text-xs text-text-secondary truncate mt-0.5" title={description}>
            {description}
          </p>
        </button>

        <span className="text-[11px] text-muted flex-shrink-0 hidden sm:inline">
          {t('skills_page.usage_count').replace('{count}', String(usage_count))}
        </span>

        {/* M2: 低频管理动作 hover 才出现，默认保持行清爽 */}
        {onArchive && (
          <button
            type="button"
            onClick={() => onArchive(name, lifecycle !== 'archived')}
            aria-label={lifecycle === 'archived' ? `取消归档 ${name}` : `归档 ${name}`}
            title={lifecycle === 'archived' ? `取消归档 ${name}` : `归档 ${name}`}
            className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100 p-1 rounded text-muted hover:text-text hover:bg-bg-subtle transition-all flex-shrink-0"
          >
            {lifecycle === 'archived' ? (
              <ArchiveRestore className="w-3.5 h-3.5" />
            ) : (
              <Archive className="w-3.5 h-3.5" />
            )}
          </button>
        )}
        {onDelete && source !== 'builtin' && (
          <TwoStepDelete
            onConfirm={() => onDelete(name)}
            label={`删除技能 ${name}`}
            armedLabel={`确认删除 ${name}`}
            className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100 p-1.5 flex-shrink-0"
          />
        )}

        <label className="relative inline-flex items-center cursor-pointer flex-shrink-0">
          <input
            type="checkbox"
            className="sr-only peer"
            checked={enabled}
            onChange={(e) => onToggle(name, e.target.checked)}
            aria-label={`${enabled ? t('skills_page.disable_skill') : t('skills_page.enable_skill')} ${name}`}
          />
          <div
            className="w-9 h-5 bg-bg-subtle peer-focus:outline-none peer-focus:ring-4
                   peer-focus:ring-primary/30 rounded-full peer
                   peer-checked:after:translate-x-full peer-checked:after:border-text-inverse
                   after:content-[''] after:absolute after:top-[2px] after:left-[2px]
                   after:bg-text-inverse after:border-border after:border after:rounded-full
                   after:h-4 after:w-4 after:transition-all
                   peer-checked:bg-primary"
          ></div>
        </label>
      </div>
    </ContextMenu>
  );
}
