import { CheckSquare, FilePlus2, FileText, Plus, Save, Square, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { ProjectOverviewWidgets } from '../../../features/project-type/ProjectOverviewWidgets';
import { projectApi, type ProjectMaterial, type ProjectSummary } from '../../../shared/api/projectApi';
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
      {Boolean(project.projectType || project.detectedType) && (
        <div className="mb-2" data-testid="project-overview-widgets-slot">
          <ProjectOverviewWidgets project={project} />
        </div>
      )}
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

const MATERIAL_PER_FILE_CAP = 8000;
const MATERIAL_TOTAL_CAP = 16000;

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
  const [enabledOverrides, setEnabledOverrides] = useState<Record<string, boolean>>({});
  const [togglingId, setTogglingId] = useState<string | null>(null);

  const isMaterialEnabled = (m: ProjectMaterial): boolean => {
    if (m.id in enabledOverrides) return enabledOverrides[m.id];
    return m.enabled !== false;
  };

  const handleToggleMaterial = async (m: ProjectMaterial) => {
    if (togglingId === m.id) return;
    const nextEnabled = !isMaterialEnabled(m);
    setEnabledOverrides((prev) => ({ ...prev, [m.id]: nextEnabled }));
    if (typeof projectApi.updateMaterial !== 'function') return;
    setTogglingId(m.id);
    try {
      await projectApi.updateMaterial(project.id, m.id, { enabled: nextEnabled });
    } catch (err) {
      setEnabledOverrides((prev) => ({ ...prev, [m.id]: !nextEnabled }));
      toast.error(err instanceof Error ? err.message : '切换资料状态失败');
    } finally {
      setTogglingId(null);
    }
  };

  const readyMaterials = (list ?? []).filter((m) => m.status === 'ready');
  const activeReadyMaterials = readyMaterials.filter((m) => isMaterialEnabled(m));
  const usedChars = Math.min(
    MATERIAL_TOTAL_CAP,
    activeReadyMaterials.reduce(
      (acc, m) => acc + Math.min((m.content ?? '').length, MATERIAL_PER_FILE_CAP),
      0,
    ),
  );
  const usagePct = Math.min(100, Math.round((usedChars / MATERIAL_TOTAL_CAP) * 100));

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

      {list && list.length > 0 && (
        <div
          className="mb-2 px-1.5 py-1 rounded bg-bg-secondary/60 border border-border/40"
          data-testid="project-materials-watermark"
        >
          <div className="flex items-center justify-between text-ui-2xs text-text-secondary">
            <span>
              受控注入源 · 已启用 {activeReadyMaterials.length}/{readyMaterials.length}
            </span>
            <span className="tabular-nums text-muted">
              {usedChars.toLocaleString()} / {MATERIAL_TOTAL_CAP.toLocaleString()} 字 ({usagePct}%)
            </span>
          </div>
          <div className="mt-1 h-1 w-full rounded-full bg-border/50 overflow-hidden">
            <div
              className={`h-full transition-all ${
                usagePct >= 90 ? 'bg-danger' : usagePct >= 70 ? 'bg-warning' : 'bg-primary'
              }`}
              style={{ width: `${Math.max(usagePct, activeReadyMaterials.length > 0 ? 4 : 0)}%` }}
            />
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="text-ui-2xs text-muted py-1" data-testid="project-materials-loading">
          {t('sider.project.materials_loading')}
        </div>
      ) : list && list.length > 0 ? (
        <ul className="space-y-1" data-testid="project-material-list">
          {list.map((m) => {
            const enabled = isMaterialEnabled(m);
            return (
            <li
              key={m.id}
              data-testid="project-material-row"
              data-status={m.status}
              data-enabled={String(enabled)}
              className={`flex items-start gap-1.5 px-1.5 py-1 rounded bg-bg/60 border border-border/30 transition-opacity ${
                enabled ? '' : 'opacity-60'
              }`}
            >
              <button
                type="button"
                data-testid="project-material-toggle"
                aria-pressed={enabled}
                aria-label={enabled ? '暂停注入此资料' : '启用注入此资料'}
                title={enabled ? '已参与本轮上下文注入（点击暂停）' : '已暂停注入（点击启用）'}
                disabled={togglingId === m.id}
                onClick={() => void handleToggleMaterial(m)}
                className="mt-0.5 shrink-0 inline-flex items-center justify-center text-muted hover:text-primary disabled:opacity-40"
              >
                {enabled ? (
                  <CheckSquare className="w-3.5 h-3.5 text-primary" aria-hidden="true" />
                ) : (
                  <Square className="w-3.5 h-3.5" aria-hidden="true" />
                )}
              </button>
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
            );
          })}
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
