import { FilePlus2, FileText, Plus, Save, Trash2 } from 'lucide-react';

import type { ProjectMaterial, ProjectSummary } from '../../../shared/api/projectApi';
import { useI18n } from '../../../shared/lib/i18n';
import { formatRelativeTime } from '../../../shared/lib/utils';

import { MaterialStatusBadge } from './MaterialStatusBadge';

interface OverviewDraftEntry {
  description: string;
  instructions: string;
  dirty: boolean;
}

interface ProjectOverviewPanelProps {
  project: ProjectSummary;
  draft: OverviewDraftEntry | undefined;
  saving: boolean;
  onSave: (project: ProjectSummary) => void;
  onChange: (projectId: string, field: 'description' | 'instructions', value: string) => void;
}

export function ProjectOverviewPanel({
  project,
  draft,
  saving,
  onSave,
  onChange,
}: ProjectOverviewPanelProps) {
  const { t } = useI18n();
  return (
    <div
      className="ml-5 mr-1.5 mt-1 p-2 rounded border border-border/50 bg-bg/40"
      data-testid="project-overview-panel"
    >
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-ui-2xs text-muted uppercase tracking-wide">
          {t('sider.project.overview_title')}
        </span>
        <button
          type="button"
          data-testid="project-overview-save"
          disabled={!draft?.dirty || saving}
          onClick={() => onSave(project)}
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-ui-2xs text-text hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Save className="w-3 h-3" aria-hidden="true" />
          {saving ? t('sider.project.overview_saving') : t('sider.project.overview_save')}
        </button>
      </div>
      <label className="block text-ui-2xs text-muted mb-0.5">
        {t('sider.project.overview_description')}
      </label>
      <textarea
        data-testid="project-overview-description"
        value={draft?.description ?? ''}
        onChange={(e) => onChange(project.id, 'description', e.target.value)}
        rows={2}
        className="w-full text-ui-2xs px-1.5 py-1 rounded border border-border bg-bg resize-y"
        placeholder={t('sider.project.overview_description_placeholder')}
      />
      <label className="block text-ui-2xs text-muted mb-0.5 mt-1.5">
        {t('sider.project.overview_instructions')}
      </label>
      <textarea
        data-testid="project-overview-instructions"
        value={draft?.instructions ?? ''}
        onChange={(e) => onChange(project.id, 'instructions', e.target.value)}
        rows={3}
        className="w-full text-ui-2xs px-1.5 py-1 rounded border border-border bg-bg resize-y"
        placeholder={t('sider.project.overview_instructions_placeholder')}
      />
    </div>
  );
}

interface ProjectMaterialsPanelProps {
  project: ProjectSummary;
  list: ProjectMaterial[] | undefined;
  isLoading: boolean;
  isAdding: boolean;
  draftText: string;
  currentSessionId: string | null;
  savingAnswer: boolean;
  removingMaterialId: string | null;
  onSaveAnswer: (project: ProjectSummary) => void;
  onRemoveMaterial: (project: ProjectSummary, materialId: string) => void;
  onDraftChange: (projectId: string, text: string) => void;
  onAddMaterial: (project: ProjectSummary) => void;
}

export function ProjectMaterialsPanel({
  project,
  list,
  isLoading,
  isAdding,
  draftText,
  currentSessionId,
  savingAnswer,
  removingMaterialId,
  onSaveAnswer,
  onRemoveMaterial,
  onDraftChange,
  onAddMaterial,
}: ProjectMaterialsPanelProps) {
  const { t } = useI18n();
  return (
    <div
      className="ml-5 mr-1.5 mt-1 p-2 rounded border border-border/50 bg-bg/40"
      data-testid="project-materials-panel"
    >
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-ui-2xs text-muted uppercase tracking-wide">
          {t('sider.project.materials_title')}
        </span>
        <button
          type="button"
          data-testid="project-save-answer"
          disabled={savingAnswer || !currentSessionId}
          onClick={() => onSaveAnswer(project)}
          title={
            currentSessionId
              ? t('sider.project.save_answer_title')
              : t('sider.project.save_answer_no_session')
          }
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-ui-2xs text-text hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40"
        >
          <FilePlus2 className="w-3 h-3" aria-hidden="true" />
          {t('sider.project.save_answer')}
        </button>
      </div>

      {isLoading ? (
        <div className="text-ui-2xs text-muted py-1" data-testid="project-materials-loading">
          {t('sider.project.materials_loading')}
        </div>
      ) : list && list.length > 0 ? (
        <ul className="space-y-1" data-testid="project-material-list">
          {list.map((m) => (
            <li
              key={m.id}
              data-testid="project-material-row"
              data-status={m.status}
              className="flex items-start gap-1.5 px-1.5 py-1 rounded bg-bg/60 border border-border/30"
            >
              <FileText className="w-3 h-3 mt-0.5 shrink-0 text-muted" aria-hidden="true" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5 text-ui-2xs">
                  <MaterialStatusBadge status={m.status} />
                  <span className="text-muted truncate">
                    {m.sourceMessageId
                      ? t('sider.project.material_from_message').replace('{id}', m.sourceMessageId)
                      : t('sider.project.material_direct')}
                  </span>
                  <span className="text-muted/60 tabular-nums ml-auto">
                    {formatRelativeTime(m.createdAt)}
                  </span>
                </div>
                {m.status === 'failed' && m.errorMessage && (
                  <div
                    className="text-ui-2xs text-warning mt-0.5 truncate"
                    title={m.errorMessage}
                    data-testid="project-material-error"
                  >
                    {m.errorMessage}
                  </div>
                )}
                {m.status === 'ready' && m.content && (
                  <div className="text-ui-2xs text-text-secondary mt-0.5 line-clamp-2">
                    {m.content.slice(0, 120)}
                    {m.content.length > 120 ? '…' : ''}
                  </div>
                )}
              </div>
              <button
                type="button"
                data-testid="project-material-remove"
                aria-label={t('sider.project.material_remove')}
                disabled={removingMaterialId === m.id}
                onClick={() => onRemoveMaterial(project, m.id)}
                className="shrink-0 inline-flex items-center justify-center w-4 h-4 rounded text-muted hover:text-text hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Trash2 className="w-3 h-3" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <div className="text-ui-2xs text-muted py-1" data-testid="project-materials-empty">
          {t('sider.project.materials_empty')}
        </div>
      )}

      <div className="mt-2 space-y-1">
        <textarea
          data-testid="project-material-input"
          value={draftText}
          onChange={(e) => onDraftChange(project.id, e.target.value)}
          rows={3}
          placeholder={t('sider.project.material_input_placeholder')}
          className="w-full text-ui-2xs px-1.5 py-1 rounded border border-border bg-bg resize-y"
        />
        <div className="flex justify-end">
          <button
            type="button"
            data-testid="project-material-add"
            disabled={isAdding || !draftText.trim()}
            onClick={() => onAddMaterial(project)}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-ui-2xs text-text hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Plus className="w-3 h-3" aria-hidden="true" />
            {t('sider.project.material_add')}
          </button>
        </div>
      </div>
    </div>
  );
}

/** 子行前缀圆点：层级指示，弱于图标避免与主行混淆 */
export function MessageDot() {
  return (
    <span className="w-1 h-1 rounded-full bg-current opacity-40 shrink-0" aria-hidden="true" />
  );
}

/** 移除按钮图标：与 Folder 语义呼应，弱化"删除文件"的误读 */
export function FolderMinusIcon() {
  return (
    <svg
      className="h-4 w-4"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z" />
      <path d="M9 13h6" />
    </svg>
  );
}
