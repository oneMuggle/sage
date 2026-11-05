/**
 * AddProjectDialog — 添加项目对话框（P3, 2026-11-05）。
 *
 * 流程：选目录 → 选模板（可选）→ 确认。模板只影响目录/文件骨架的脚手架化，
 * 不改变项目类型与阶段；"不使用模板" 走原有纯登记路径。
 */

import { FolderOpen } from 'lucide-react';
import { useEffect, useState } from 'react';

import { projectApi, type ProjectTemplateSummary } from '../../../shared/api/projectApi';
import { useI18n } from '../../../shared/lib/i18n';
import { Button } from '../../../shared/ui/Button';
import { Modal } from '../../../shared/ui/Modal';

export interface AddProjectSubmission {
  path: string;
  templateName?: string;
}

export interface AddProjectDialogProps {
  isOpen: boolean;
  onClose: () => void;
  /** 返回 Promise 以便对话框在登记期间保持 submitting 态；抛错时错误由调用方 toast。 */
  onSubmit: (payload: AddProjectSubmission) => Promise<void>;
}

const sourceBadgeKey = (source: ProjectTemplateSummary['source']) =>
  source === 'global' ? 'sider.project.template_global' : 'sider.project.template_builtin';

export function AddProjectDialog({ isOpen, onClose, onSubmit }: AddProjectDialogProps) {
  const { t } = useI18n();
  const [path, setPath] = useState<string | null>(null);
  const [templateName, setTemplateName] = useState<string | null>(null);
  const [templates, setTemplates] = useState<ProjectTemplateSummary[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // 每次打开重置本地状态，并拉取最新模板目录
  useEffect(() => {
    if (!isOpen) return;
    setPath(null);
    setTemplateName(null);
    setSubmitting(false);
    setLoadingTemplates(true);
    let cancelled = false;
    projectApi
      .listTemplates()
      .then((list) => {
        if (!cancelled) setTemplates(list);
      })
      .catch(() => {
        if (!cancelled) setTemplates([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingTemplates(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  const pickDirectory = async () => {
    const api = typeof window !== 'undefined' ? window.electronAPI : undefined;
    if (!api) return;
    const picked = await api.selectDirectory({ intent: 'open' });
    if (picked) {
      setPath(picked);
      // 换目录后模板选择保留：模板与目录正交
    }
  };

  const confirm = async () => {
    if (!path || submitting) return;
    setSubmitting(true);
    try {
      await onSubmit({ path, ...(templateName ? { templateName } : {}) });
      onClose();
    } catch {
      // 调用方已 toast；保持对话框打开以便用户重试或换目录
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={t('sider.project.add_dialog_title')}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={submitting}>
            {t('common.cancel')}
          </Button>
          <Button size="sm" onClick={() => void confirm()} disabled={!path || submitting}>
            {t('sider.project.confirm_add')}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {/* 目录选择 */}
        <div className="flex flex-col gap-1.5">
          <span className="text-ui-sm font-medium text-text">
            {t('sider.project.directory_label')}
          </span>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={() => void pickDirectory()}>
              <FolderOpen className="w-3.5 h-3.5 mr-1.5" aria-hidden="true" />
              {path ? t('sider.project.change_directory') : t('sider.project.pick_directory')}
            </Button>
            <span
              className="flex-1 min-w-0 truncate text-ui-sm text-text-secondary"
              data-testid="add-project-path"
              title={path ?? undefined}
            >
              {path ?? t('sider.project.directory_unset')}
            </span>
          </div>
        </div>

        {/* 模板选择 */}
        <div className="flex flex-col gap-1.5">
          <span className="text-ui-sm font-medium text-text">
            {t('sider.project.template_label')}
          </span>
          <div
            className="max-h-64 overflow-y-auto rounded border border-border"
            data-testid="add-project-template-list"
          >
            {loadingTemplates ? (
              <div className="px-3 py-2 text-ui-sm text-muted">
                {t('sider.project.template_loading')}
              </div>
            ) : (
              <div className="flex flex-col">
                <TemplateOption
                  selected={templateName === null}
                  label={t('sider.project.template_none')}
                  description={t('sider.project.template_none_desc')}
                  onSelect={() => setTemplateName(null)}
                />
                {templates.map((tpl) => (
                  <TemplateOption
                    key={`${tpl.source}:${tpl.name}`}
                    selected={templateName === tpl.name}
                    label={tpl.name}
                    description={tpl.description}
                    badge={t(sourceBadgeKey(tpl.source))}
                    meta={t('sider.project.template_meta')
                      .replace('{dirs}', String(tpl.directoryCount))
                      .replace('{files}', String(tpl.fileCount))}
                    onSelect={() => setTemplateName(tpl.name)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </Modal>
  );
}

interface TemplateOptionProps {
  selected: boolean;
  label: string;
  description: string;
  badge?: string;
  meta?: string;
  onSelect: () => void;
}

function TemplateOption({
  selected,
  label,
  description,
  badge,
  meta,
  onSelect,
}: TemplateOptionProps) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      data-testid="add-project-template-option"
      onClick={onSelect}
      className={`text-left px-3 py-2 border-b border-border/60 last:border-b-0 hover:bg-bg-hover ${
        selected ? 'bg-primary/5' : ''
      }`}
    >
      <div className="flex items-center gap-1.5">
        <span className="text-ui-sm text-text truncate">{label}</span>
        {badge && (
          <span className="shrink-0 rounded border border-border/60 bg-bg-muted px-1 py-0.5 text-ui-2xs text-text-secondary">
            {badge}
          </span>
        )}
        {meta && <span className="shrink-0 text-ui-2xs text-muted">{meta}</span>}
      </div>
      {description && <div className="text-ui-2xs text-muted truncate">{description}</div>}
    </button>
  );
}
