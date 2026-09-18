/**
 * AllowedPathsEditor — 项目 allowed_paths 内联编辑器 (P1, 2026-09-17)
 *
 * 嵌入在 ProjectSection 行展开区，允许用户为单个项目配置允许访问的
 * 路径规则列表（除 workspace 内部之外）。后端 PUT /projects/{id}/allowed-paths。
 *
 * UX:
 *  - 默认展示当前规则列表（紧凑 chip 样式）+ 顶部 "编辑" 按钮
 *  - 编辑状态：列表变为可删除 + 末尾行内 input + Add 按钮 + Save/Cancel
 *  - 保存成功 → 退出编辑态，toast 提示；失败保留编辑态供用户调整
 *  - 空列表（规则为空）显示空态提示
 *
 * 路径规则语法：类 .gitignore（`~/Documents/**`、`/tmp/*`），由后端校验。
 */

import { Check, Pencil, Plus, Trash2, X } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import { projectApi, type ProjectSummary } from '../../../shared/api/projectApi';
import { useI18n } from '../../../shared/lib/i18n';

interface AllowedPathsEditorProps {
  project: ProjectSummary;
  /** 规则更新成功回调（用于刷新上层列表的 allowedPaths 字段） */
  onUpdated?: (next: string[]) => void;
}

function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}

export function AllowedPathsEditor({ project, onUpdated }: AllowedPathsEditorProps) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string[]>(project.allowedPaths);
  const [pendingInput, setPendingInput] = useState('');
  const [saving, setSaving] = useState(false);

  // 同步 project.allowedPaths 外部变化（如其他标签页/自动刷新）
  useEffect(() => {
    if (!editing) {
      setDraft(project.allowedPaths);
    }
  }, [project.allowedPaths, editing]);

  const enterEdit = useCallback(() => {
    setDraft(project.allowedPaths);
    setPendingInput('');
    setEditing(true);
  }, [project.allowedPaths]);

  const cancelEdit = useCallback(() => {
    setDraft(project.allowedPaths);
    setPendingInput('');
    setEditing(false);
  }, [project.allowedPaths]);

  const addDraftRow = useCallback(() => {
    const trimmed = pendingInput.trim();
    if (!trimmed) return;
    if (draft.includes(trimmed)) {
      toast.error(t('sider.project.allowed_paths_failed').replace('{message}', '规则已存在'));
      return;
    }
    setDraft((prev) => [...prev, trimmed]);
    setPendingInput('');
  }, [draft, pendingInput, t]);

  const removeDraftRow = useCallback((idx: number) => {
    setDraft((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const save = useCallback(async () => {
    setSaving(true);
    try {
      const next = await projectApi.updateAllowedPaths(project.id, draft);
      toast.success(t('sider.project.allowed_paths_saved').replace('{count}', String(next.length)));
      setDraft(next);
      setEditing(false);
      onUpdated?.(next);
    } catch (err) {
      toast.error(t('sider.project.allowed_paths_failed').replace('{message}', errorMessage(err)));
    } finally {
      setSaving(false);
    }
  }, [draft, onUpdated, project.id, t]);

  return (
    <div
      className="ml-5 mr-1.5 mt-1 px-2 py-1.5 rounded border border-border bg-bg/40"
      data-testid="allowed-paths-editor"
      onClick={(e) => e.stopPropagation()}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] uppercase tracking-wide text-muted">
          {t('sider.project.allowed_paths_label')}
        </span>
        {!editing && (
          <button
            type="button"
            data-testid="allowed-paths-edit"
            aria-label={t('sider.project.allowed_paths_label')}
            title={t('sider.project.allowed_paths_label')}
            onClick={enterEdit}
            className="inline-flex items-center justify-center w-4 h-4 rounded text-muted hover:text-text hover:bg-bg-hover"
          >
            <Pencil className="w-2.5 h-2.5" />
          </button>
        )}
      </div>

      {/* 编辑模式：可增删规则 */}
      {editing && (
        <div className="flex flex-col gap-1">
          {draft.length === 0 ? (
            <div className="text-[10px] text-muted italic" data-testid="allowed-paths-empty">
              {t('sider.project.allowed_paths_empty')}
            </div>
          ) : (
            <ul className="flex flex-col gap-0.5" data-testid="allowed-paths-list">
              {draft.map((rule, idx) => (
                <li
                  key={`${rule}-${idx}`}
                  className="flex items-center gap-1 group/rule text-[11px] font-mono"
                  data-testid="allowed-paths-row"
                >
                  <span className="flex-1 min-w-0 truncate text-text-secondary" title={rule}>
                    {rule}
                  </span>
                  <button
                    type="button"
                    data-testid="allowed-paths-remove"
                    aria-label={t('sider.project.allowed_paths_remove')}
                    title={t('sider.project.allowed_paths_remove')}
                    onClick={() => removeDraftRow(idx)}
                    className="inline-flex items-center justify-center w-4 h-4 rounded text-muted hover:text-danger hover:bg-bg-hover opacity-0 group-hover/rule:opacity-100"
                  >
                    <Trash2 className="w-2.5 h-2.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div className="flex items-center gap-1 mt-1">
            <input
              type="text"
              data-testid="allowed-paths-input"
              aria-label={t('sider.project.allowed_paths_add_placeholder')}
              placeholder={t('sider.project.allowed_paths_add_placeholder')}
              value={pendingInput}
              onChange={(e) => setPendingInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  addDraftRow();
                }
              }}
              className="flex-1 min-w-0 px-1.5 py-0.5 text-[11px] font-mono rounded border border-border bg-bg focus:outline-none focus:border-primary"
            />
            <button
              type="button"
              data-testid="allowed-paths-add"
              aria-label={t('sider.project.allowed_paths_add')}
              title={t('sider.project.allowed_paths_add')}
              onClick={addDraftRow}
              disabled={pendingInput.trim().length === 0}
              className="inline-flex items-center justify-center w-5 h-5 rounded text-muted hover:text-text hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Plus className="w-3 h-3" />
            </button>
          </div>

          <div className="flex items-center justify-end gap-1 mt-1">
            <button
              type="button"
              data-testid="allowed-paths-cancel"
              onClick={cancelEdit}
              disabled={saving}
              className="inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] rounded text-text-secondary hover:bg-bg-hover disabled:opacity-50"
            >
              <X className="w-2.5 h-2.5" />
              {t('sider.project.allowed_paths_cancel')}
            </button>
            <button
              type="button"
              data-testid="allowed-paths-save"
              onClick={() => void save()}
              disabled={saving}
              className="inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] rounded bg-primary text-primary-fg hover:opacity-90 disabled:opacity-50"
            >
              <Check className="w-2.5 h-2.5" />
              {t('sider.project.allowed_paths_save')}
            </button>
          </div>
        </div>
      )}

      {/* 只读模式：紧凑列表 */}
      {!editing && (
        <div>
          {project.allowedPaths.length === 0 ? (
            <div className="text-[10px] text-muted italic" data-testid="allowed-paths-empty">
              {t('sider.project.allowed_paths_empty')}
            </div>
          ) : (
            <ul className="flex flex-col gap-0.5" data-testid="allowed-paths-list">
              {project.allowedPaths.map((rule, idx) => (
                <li
                  key={`${rule}-${idx}`}
                  className="text-[11px] font-mono text-text-secondary truncate"
                  title={rule}
                >
                  {rule}
                </li>
              ))}
            </ul>
          )}
          <div className="text-[9px] text-muted mt-1 leading-tight">
            {t('sider.project.allowed_paths_hint')}
          </div>
        </div>
      )}
    </div>
  );
}
