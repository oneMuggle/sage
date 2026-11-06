import {
  Archive,
  ArchiveRestore,
  Copy,
  Download,
  FolderSearch,
  Pin,
  PinOff,
  Trash2,
  X,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import type { Skill } from '../../shared/api';
import { copyToClipboard } from '../../shared/lib/clipboard';
import { fillTemplate } from '../../shared/lib/formatTemplate';
import { useI18n } from '../../shared/lib/i18n';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';

import { SkillAuditDrawer } from './SkillAuditDrawer';
import SkillOriginBadge from './SkillOriginBadge';

export interface SkillDetailDrawerProps {
  skill: Skill | null;
  open: boolean;
  onClose: () => void;
  onToggle: (name: string, enabled: boolean) => void;
  onDelete?: (name: string) => void;
  onArchive?: (name: string, archived: boolean) => void;
  onPin?: (name: string, pinned: boolean) => void;
  onRolledBack?: () => void;
}

/**
 * M2 技能详情抽屉（右侧滑出）。
 *
 * 列表页只保留一行摘要；描述、触发词、正文、版本、来源、历史、管理动作
 * 全部集中在这里，避免卡片堆砌导致首屏信息过载。
 */
export default function SkillDetailDrawer({
  skill,
  open,
  onClose,
  onToggle,
  onDelete,
  onArchive,
  onPin,
  onRolledBack,
}: SkillDetailDrawerProps) {
  const { t } = useI18n();
  const [auditOpen, setAuditOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);

  if (!open || !skill) return null;

  const {
    name,
    description,
    triggers,
    enabled,
    usage_count,
    origin,
    source,
    body,
    version,
    lifecycle,
    pinned,
    when_to_use,
  } = skill;

  const copy = (text: string) =>
    void copyToClipboard(text, {
      successMessage: t('contextMenu.common.copied'),
      errorMessage: t('contextMenu.common.copyFailed'),
    });

  const handleDelete = async () => {
    if (!onDelete) return;
    const confirmed = await confirmDialog({
      title: t('contextMenu.skill.deleteTitle'),
      message: fillTemplate(t('contextMenu.skill.deleteBody'), { name }),
      confirmLabel: t('common.delete'),
      danger: true,
    });
    if (confirmed) {
      onDelete(name);
      onClose();
    }
  };

  const showInFolder = async () => {
    try {
      await window.electronAPI?.skills?.showSkillInFolder(name);
    } catch (error) {
      toast.error(`在文件夹中显示失败：${(error as Error).message}`);
    }
  };

  const exportSkill = async () => {
    try {
      const result = await window.electronAPI?.skills?.exportSkill(name);
      if (result?.ok) toast.success(`已导出到 ${result.path}`);
    } catch (error) {
      toast.error(`导出失败：${(error as Error).message}`);
    }
  };

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label={name}>
      <button
        type="button"
        aria-label="关闭"
        className="absolute inset-0 bg-overlay cursor-default"
        onClick={onClose}
      />
      <aside className="absolute right-0 top-0 h-full w-[520px] max-w-full bg-bg border-l border-line shadow-xl overflow-y-auto animate-fade-enter">
        <div className="sticky top-0 z-10 flex items-start justify-between gap-3 px-5 py-4 border-b border-border bg-bg">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-lg font-semibold text-text truncate">{name}</h2>
              <SkillOriginBadge origin={origin} />
              {version && (
                <span className="px-1.5 py-0.5 text-ui-2xs rounded-full bg-bg-subtle text-text-secondary">
                  v{version}
                </span>
              )}
              {pinned && <span className="text-xs text-warning">📌</span>}
            </div>
            <p className="text-xs text-muted mt-1">
              {t('skills_page.usage_count').replace('{count}', String(usage_count))}
              {lifecycle === 'archived' ? ` · ${t('skills_page.lifecycle_archived')}` : ''}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="p-1.5 rounded text-muted hover:text-text hover:bg-bg-subtle transition-colors flex-shrink-0"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-5">
          <section>
            <h3 className="text-xs uppercase tracking-wide text-muted mb-1.5">
              {t('skills_page.section_description')}
            </h3>
            <p className="text-sm text-text-secondary whitespace-pre-wrap">{description}</p>
          </section>

          {triggers.length > 0 && (
            <section>
              <h3 className="text-xs uppercase tracking-wide text-muted mb-1.5">
                {t('skills_page.section_triggers')}
              </h3>
              <div className="flex flex-wrap gap-1.5">
                {triggers.map((trigger, index) => (
                  <span
                    key={`${trigger}-${index}`}
                    className="px-2 py-0.5 bg-bg-subtle text-text-secondary text-xs rounded-full"
                  >
                    {trigger}
                  </span>
                ))}
              </div>
            </section>
          )}

          {when_to_use && (
            <section>
              <h3 className="text-xs uppercase tracking-wide text-muted mb-1.5">
                {t('skills_page.section_when_to_use')}
              </h3>
              <p className="text-sm text-text-secondary whitespace-pre-wrap">{when_to_use}</p>
            </section>
          )}

          {source === 'skillmd' && body && (
            <section>
              <h3 className="text-xs uppercase tracking-wide text-muted mb-1.5">
                {t('skills_page.section_body')}
              </h3>
              <pre className="p-3 bg-bg-subtle rounded-radius-sm text-xs whitespace-pre-wrap text-text-secondary max-h-72 overflow-auto">
                {body}
              </pre>
            </section>
          )}

          <section>
            <h3 className="text-xs uppercase tracking-wide text-muted mb-2">
              {t('skills_page.section_actions')}
            </h3>
            <div className="flex flex-wrap items-center gap-2">
              {onPin && (
                <button
                  type="button"
                  onClick={() => onPin(name, !pinned)}
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded border transition-colors ${
                    pinned
                      ? 'border-warning text-warning hover:bg-warning/10'
                      : 'border-border text-text-secondary hover:text-text'
                  }`}
                >
                  {pinned ? <PinOff className="w-3.5 h-3.5" /> : <Pin className="w-3.5 h-3.5" />}
                  {pinned ? t('contextMenu.skill.unpin') : t('contextMenu.skill.pin')}
                </button>
              )}
              {onArchive && (
                <button
                  type="button"
                  onClick={() => onArchive(name, lifecycle !== 'archived')}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded border border-border text-text-secondary hover:text-text transition-colors"
                >
                  {lifecycle === 'archived' ? (
                    <ArchiveRestore className="w-3.5 h-3.5" />
                  ) : (
                    <Archive className="w-3.5 h-3.5" />
                  )}
                  {lifecycle === 'archived'
                    ? t('contextMenu.skill.unarchive')
                    : t('contextMenu.skill.archive')}
                </button>
              )}
              <button
                type="button"
                onClick={() => setAuditOpen(true)}
                data-testid={`skill-audit-open-${name}`}
                className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded border border-border text-text-secondary hover:text-text transition-colors"
              >
                {t('contextMenu.skill.history')}
              </button>
              <button
                type="button"
                onClick={() => copy(name)}
                className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded border border-border text-text-secondary hover:text-text transition-colors"
              >
                <Copy className="w-3.5 h-3.5" />
                {t('contextMenu.common.copyName')}
              </button>
              {body && (
                <button
                  type="button"
                  onClick={() => copy(body)}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded border border-border text-text-secondary hover:text-text transition-colors"
                >
                  <Copy className="w-3.5 h-3.5" />
                  {t('contextMenu.skill.copyBody')}
                </button>
              )}
              {source !== 'builtin' && window.electronAPI?.skills?.showSkillInFolder && (
                <button
                  type="button"
                  onClick={() => void showInFolder()}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded border border-border text-text-secondary hover:text-text transition-colors"
                >
                  <FolderSearch className="w-3.5 h-3.5" />
                  {t('skills_page.show_in_folder')}
                </button>
              )}
              {source !== 'builtin' && window.electronAPI?.skills?.exportSkill && (
                <button
                  type="button"
                  onClick={() => void exportSkill()}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded border border-border text-text-secondary hover:text-text transition-colors"
                >
                  <Download className="w-3.5 h-3.5" />
                  {t('skills_page.export_skill')}
                </button>
              )}
              {onDelete && source !== 'builtin' && (
                <button
                  type="button"
                  onClick={() => void handleDelete()}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded border border-error/40 text-error hover:bg-error/10 transition-colors"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  {t('contextMenu.skill.delete')}
                </button>
              )}
              <label className="ml-auto relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  className="sr-only peer"
                  checked={enabled}
                  onChange={(e) => onToggle(name, e.target.checked)}
                />
                <div
                  className="w-11 h-6 bg-bg-subtle peer-focus:outline-none peer-focus:ring-4
                         peer-focus:ring-primary/30 rounded-full peer
                         peer-checked:after:translate-x-full peer-checked:after:border-text-inverse
                         after:content-[''] after:absolute after:top-[2px] after:left-[2px]
                         after:bg-text-inverse after:border-border after:border after:rounded-full
                         after:h-5 after:w-5 after:transition-all
                         peer-checked:bg-primary"
                ></div>
              </label>
            </div>
          </section>
        </div>

        <SkillAuditDrawer
          skillName={name}
          open={auditOpen}
          onOpenChange={setAuditOpen}
          onRolledBack={onRolledBack}
        />
      </aside>
    </div>
  );
}
