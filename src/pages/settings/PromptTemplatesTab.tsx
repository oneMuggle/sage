/**
 * Settings 页面 - Prompt 模板管理 Tab（R27-B）
 *
 * 用户自定义提示词模板的查看/新建/编辑/删除。数据经 promptApi
 * 走后端 /prompts/templates CRUD（KV 存储，上限 100 条）。
 * 斜杠面板（/tpl-<名称>）与该列表共享同一数据源，保存后重载即可见。
 * r55: 导入同名冲突从"全量覆盖与否"升级为条目级勾选覆盖。
 */

import { Download, Pencil, Plus, RefreshCw, Search, Upload } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import {
  promptApi,
  type PromptTemplate,
  type PromptTemplateEnvelope,
} from '../../shared/api/promptApi';
import { copyToClipboard } from '../../shared/lib/clipboard';
import { fillTemplate } from '../../shared/lib/formatTemplate';
import { useI18n } from '../../shared/lib/i18n';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';
import { ContextMenu } from '../../shared/ui/ContextMenu/ContextMenu';
import type { ContextMenuItemSpec } from '../../shared/ui/ContextMenu/types';
import { listTplMemoryEntries, tplStorageKey } from '../../widgets/chat/TemplateFillDialog';

const MAX_NAME_LEN = 60;
const MAX_CONTENT_LEN = 8000;

interface FormState {
  id: string | null; // null = 新建
  name: string;
  description: string;
  content: string;
}

const EMPTY_FORM: FormState = { id: null, name: '', description: '', content: '' };

// eslint-disable-next-line react-refresh/only-export-components
export function formatPromptTemplatesTabAuditSnapshot(input: {
  templateCount: number;
  loading: boolean;
  editing: boolean;
  hasConflict?: boolean;
}): string {
  const count = Math.max(0, Math.trunc(input.templateCount));
  const stateLabel = input.hasConflict
    ? '冲突待决'
    : input.editing
      ? '编辑中'
      : input.loading
        ? '加载中'
        : '就绪';
  return `提示词模板 · ${count}项 · ${stateLabel}`;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatPromptTemplatesTabAuditJson(input: {
  templateCount: number;
  loading: boolean;
  editing: boolean;
  hasConflict?: boolean;
}): string {
  return JSON.stringify({
    templateCount: Math.max(0, Math.trunc(input.templateCount)),
    loading: Boolean(input.loading),
    editing: Boolean(input.editing),
    hasConflict: Boolean(input.hasConflict),
  });
}

export function PromptTemplatesTab() {
  const { t } = useI18n();
  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState<FormState | null>(null); // null = 列表态
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // R38: 记忆清除后触发重渲染（localStorage 不经过 React，需手动 tick）
  const [, setMemoryTick] = useState(0);
  // R52: 模板搜索过滤
  const [searchQuery, setSearchQuery] = useState('');
  // R42: 拖拽排序状态
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dropIndex, setDropIndex] = useState<number | null>(null);

  const handleDragStart = (index: number) => setDragIndex(index);
  const handleDragOver = (index: number) => {
    if (dragIndex !== null && dragIndex !== index) setDropIndex(index);
  };
  const handleDrop = async () => {
    if (dragIndex === null || dropIndex === null || dragIndex === dropIndex) {
      setDragIndex(null);
      setDropIndex(null);
      return;
    }
    const reordered = [...templates];
    const [moved] = reordered.splice(dragIndex, 1);
    reordered.splice(dropIndex, 0, moved);
    setTemplates(reordered);
    setDragIndex(null);
    setDropIndex(null);
    try {
      await promptApi.reorder(reordered.map((tpl) => tpl.id));
    } catch {
      await load(); // 排序失败回滚
    }
  };
  const handleDragEnd = () => {
    setDragIndex(null);
    setDropIndex(null);
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setTemplates(await promptApi.list());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSave = async () => {
    if (!form || !form.name.trim() || !form.content.trim()) return;
    setSaving(true);
    setError(null);
    try {
      if (form.id) {
        await promptApi.update(form.id, {
          name: form.name.trim(),
          description: form.description.trim(),
          content: form.content,
        });
      } else {
        await promptApi.create(form.name.trim(), form.content, form.description.trim());
      }
      setForm(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await promptApi.remove(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const promptMenuItems = (tpl: PromptTemplate): ContextMenuItemSpec[] => [
    {
      id: 'prompt-edit',
      label: t('contextMenu.prompt.edit'),
      icon: Pencil,
      onSelect: () =>
        setForm({
          id: tpl.id,
          name: tpl.name,
          description: tpl.description,
          content: tpl.content,
        }),
    },
    {
      id: 'prompt-copy-content',
      label: t('contextMenu.prompt.copyContent'),
      icon: Copy,
      onSelect: () =>
        void copyToClipboard(tpl.content, {
          successMessage: t('contextMenu.common.copied'),
          errorMessage: t('contextMenu.common.copyFailed'),
        }),
    },
    {
      id: 'prompt-copy-name',
      label: t('contextMenu.common.copyName'),
      icon: Copy,
      onSelect: () =>
        void copyToClipboard(tpl.name, {
          successMessage: t('contextMenu.common.copied'),
          errorMessage: t('contextMenu.common.copyFailed'),
        }),
    },
    { id: 'prompt-sep-delete', kind: 'separator' },
    {
      id: 'prompt-delete',
      label: t('contextMenu.prompt.delete'),
      icon: Trash2,
      destructive: true,
      onSelect: async () => {
        const confirmed = await confirmDialog({
          title: t('contextMenu.prompt.deleteTitle'),
          message: fillTemplate(t('contextMenu.prompt.deleteBody'), { name: tpl.name }),
          confirmLabel: t('common.delete'),
          danger: true,
        });
        if (confirmed) await handleDelete(tpl.id);
      },
    },
  ];

  // R30: 模板导出（JSON 下载）
  const handleExport = () => {
    promptApi
      .exportTemplates()
      .then((envelope) => {
        const blob = new Blob([JSON.stringify(envelope, null, 2)], {
          type: 'application/json;charset=utf-8',
        });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `sage-prompt-templates-${new Date().toISOString().slice(0, 10)}.json`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
      })
      .catch(() => setError(t('settings.templates.export_failed')));
  };

  // R30: 模板导入（文件选择 → JSON 解析 → 报告）
  const importInputRef = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);
  // r55: 冲突条目级覆盖选择 —— skip 导入发现同名后挂起，面板里挑覆盖谁
  // （信封来自用户文件，条目由后端逐条校验，这里只关心 templates 形状）
  const [pendingImport, setPendingImport] = useState<{
    envelope: PromptTemplateEnvelope;
    conflicts: string[];
  } | null>(null);
  const [conflictSelection, setConflictSelection] = useState<Set<string>>(new Set());

  const reportImport = (r: { imported: number; skipped: number; failed: number }) =>
    t('settings.templates.import_done')
      .replace('{imported}', String(r.imported))
      .replace('{skipped}', String(r.skipped))
      .replace('{failed}', String(r.failed));

  const handleImportFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setImporting(true);
    try {
      const envelope = JSON.parse(await file.text()) as PromptTemplateEnvelope;
      // R32 两阶段 + r55 条目级选择：先 skip 导入；同名冲突挂起待用户挑选
      const first = await promptApi.importTemplates(envelope, 'skip');
      if (first.conflicts && first.conflicts.length > 0) {
        setPendingImport({ envelope, conflicts: first.conflicts });
        setConflictSelection(new Set(first.conflicts));
        return;
      }
      toast.success(reportImport(first));
      await load();
    } catch {
      setError(t('settings.templates.import_failed'));
    } finally {
      setImporting(false);
    }
  };

  // 覆盖选中项：信封过滤为勾选条目，overwrite 重导（保留现有 id 不断链）
  const handleConflictOverwrite = async () => {
    if (!pendingImport) return;
    setImporting(true);
    try {
      const subset = {
        ...pendingImport.envelope,
        templates: (pendingImport.envelope.templates ?? []).filter(
          (tpl) =>
            !!tpl &&
            typeof tpl === 'object' &&
            conflictSelection.has(String((tpl as { name?: unknown }).name ?? '')),
        ),
      } as PromptTemplateEnvelope;
      const second = await promptApi.importTemplates(subset, 'overwrite');
      toast.success(reportImport(second));
      setPendingImport(null);
      await load();
    } catch {
      setError(t('settings.templates.overwrite_failed'));
    } finally {
      setImporting(false);
    }
  };

  const handleConflictSkip = () => {
    setPendingImport(null);
    setConflictSelection(new Set());
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-text">{t('settings.templates.title')}</h3>
          <p className="text-xs text-text-secondary mt-0.5">
            {t('settings.templates.hint_prefix')} <code className="font-mono">/tpl-</code>{' '}
            {t('settings.templates.hint_middle')} <code className="font-mono">/prompt-save</code>{' '}
            {t('settings.templates.hint_suffix')}
          </p>
        </div>
        <div className="flex gap-2">
          <div className="relative flex-1 min-w-[160px]">
            <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-muted" />
            <input
              data-testid="prompts-search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('settings.templates.search_placeholder')}
              className="w-full pl-7 pr-2 py-1.5 text-xs rounded-radius-sm border border-border bg-bg text-text"
            />
          </div>
          <button
            type="button"
            data-testid="prompts-refresh"
            onClick={() => void load()}
            className="p-1.5 rounded hover:bg-bg-hover text-muted"
            title={t('settings.templates.refresh')}
          >
            <RefreshCw className="w-4 h-4" />
          </button>
          <button
            type="button"
            data-testid="prompts-export"
            onClick={handleExport}
            className="p-1.5 rounded hover:bg-bg-hover text-muted"
            title={t('settings.templates.export_title')}
          >
            <Download className="w-4 h-4" />
          </button>
          <button
            type="button"
            data-testid="prompts-import"
            disabled={importing}
            onClick={() => importInputRef.current?.click()}
            className="p-1.5 rounded hover:bg-bg-hover text-muted disabled:opacity-50"
            title={t('settings.templates.import_title')}
          >
            <Upload className="w-4 h-4" />
          </button>
          <input
            ref={importInputRef}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={(e) => void handleImportFile(e)}
          />
          <button
            type="button"
            data-testid="prompts-new"
            onClick={() => setForm({ ...EMPTY_FORM })}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-radius-sm bg-primary text-text-inverse hover:bg-primary-hover"
          >
            <Plus className="w-3.5 h-3.5" />
            {t('settings.templates.new')}
          </button>
        </div>
      </div>

      {error && (
        <p className="text-xs text-error" data-testid="prompts-error">
          {error}
        </p>
      )}

      {pendingImport && (
        <div
          className="p-3 rounded-radius-sm border border-amber-500/40 bg-amber-500/5 space-y-2"
          data-testid="prompts-conflict-panel"
        >
          <p className="text-xs text-text">
            {t('settings.templates.conflict_notice').replace(
              '{count}',
              String(pendingImport.conflicts.length),
            )}
          </p>
          <ul className="space-y-1">
            {pendingImport.conflicts.map((name) => (
              <li key={name} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  data-testid={`prompts-conflict-check-${name}`}
                  checked={conflictSelection.has(name)}
                  onChange={(e) => {
                    const next = new Set(conflictSelection);
                    if (e.target.checked) next.add(name);
                    else next.delete(name);
                    setConflictSelection(next);
                  }}
                />
                <span className="text-xs text-text font-mono">{name}</span>
              </li>
            ))}
          </ul>
          <div className="flex gap-2">
            <button
              type="button"
              data-testid="prompts-conflict-overwrite"
              disabled={importing || conflictSelection.size === 0}
              onClick={() => void handleConflictOverwrite()}
              className="px-2.5 py-1 text-xs rounded-radius-sm bg-primary text-text-inverse hover:bg-primary-hover disabled:opacity-50"
            >
              {t('settings.templates.overwrite_selected').replace(
                '{count}',
                String(conflictSelection.size),
              )}
            </button>
            <button
              type="button"
              data-testid="prompts-conflict-skip"
              onClick={handleConflictSkip}
              className="px-2.5 py-1 text-xs rounded-radius-sm border border-border text-muted hover:text-text"
            >
              {t('settings.templates.keep_existing')}
            </button>
          </div>
        </div>
      )}

      {form && (
        <div
          className="p-3 rounded-radius-sm border border-border space-y-2"
          data-testid="prompts-form"
        >
          <input
            data-testid="prompts-form-name"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder={t('settings.templates.form.name_placeholder')}
            maxLength={MAX_NAME_LEN}
            className="w-full px-2 py-1.5 text-xs rounded-radius-sm border border-border bg-bg text-text"
          />
          <input
            data-testid="prompts-form-desc"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder={t('settings.templates.form.desc_placeholder')}
            maxLength={300}
            className="w-full px-2 py-1.5 text-xs rounded-radius-sm border border-border bg-bg text-text"
          />
          <textarea
            data-testid="prompts-form-content"
            value={form.content}
            onChange={(e) => setForm({ ...form, content: e.target.value })}
            placeholder={t('settings.templates.form.content_placeholder')}
            rows={6}
            maxLength={MAX_CONTENT_LEN}
            className="w-full px-2 py-1.5 text-xs rounded-radius-sm border border-border bg-bg text-text font-mono"
          />
          <div className="flex gap-2 justify-end">
            <button
              type="button"
              onClick={() => setForm(null)}
              className="px-2.5 py-1 text-xs rounded-radius-sm border border-border hover:bg-bg-hover"
            >
              {t('settings.templates.cancel')}
            </button>
            <button
              type="button"
              data-testid="prompts-form-save"
              disabled={saving || !form.name.trim() || !form.content.trim()}
              onClick={() => void handleSave()}
              className="px-2.5 py-1 text-xs rounded-radius-sm bg-primary text-text-inverse hover:bg-primary-hover disabled:opacity-50"
            >
              {saving ? t('settings.templates.saving') : t('settings.templates.save')}
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <p className="text-xs text-text-secondary">{t('settings.templates.loading')}</p>
      ) : templates.length === 0 ? (
        <p className="text-xs text-text-secondary" data-testid="prompts-empty">
          {t('settings.templates.empty')}
        </p>
      ) : (
        <ul className="space-y-2" data-testid="prompts-list">
          {templates
            .filter((tpl) => {
              if (!searchQuery.trim()) return true;
              const q = searchQuery.toLowerCase();
              return (
                tpl.name.toLowerCase().includes(q) ||
                (tpl.description ?? '').toLowerCase().includes(q) ||
                tpl.content.toLowerCase().includes(q)
              );
            })
            .map((tpl, idx) => (
              <ContextMenu key={tpl.id} items={() => promptMenuItems(tpl)}>
              <li
                draggable
                onDragStart={() => handleDragStart(idx)}
                onDragOver={(e) => {
                  e.preventDefault();
                  handleDragOver(idx);
                }}
                onDrop={() => void handleDrop()}
                onDragEnd={handleDragEnd}
                className={`p-3 rounded-radius-sm border ${dropIndex === idx ? 'border-primary' : 'border-border'} ${dragIndex === idx ? 'opacity-50' : ''} cursor-grab active:cursor-grabbing`}
                data-testid="prompts-item"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="text-xs font-medium text-text">{tpl.name}</div>
                    {tpl.description && (
                      <div className="text-ui-2xs text-text-secondary">{tpl.description}</div>
                    )}
                    <div className="text-ui-2xs text-text-secondary font-mono mt-1 line-clamp-2">
                      {tpl.content.length > 120 ? `${tpl.content.slice(0, 120)}…` : tpl.content}
                    </div>
                  </div>
                  <div className="flex gap-1 shrink-0">
                    {(() => {
                      // R38: 变量记忆展示/清除 —— 与填充对话框同键口径
                      try {
                        const raw = window.localStorage.getItem(tplStorageKey(tpl.content));
                        const mem = raw ? (JSON.parse(raw) as Record<string, string>) : null;
                        const entries = mem ? Object.entries(mem) : [];
                        if (entries.length === 0) return null;
                        return (
                          <span
                            className="text-ui-2xs text-text-secondary mr-1"
                            data-testid={`prompts-memory-${tpl.id}`}
                          >
                            {t('settings.templates.memory_count').replace(
                              '{count}',
                              String(entries.length),
                            )}
                            <button
                              type="button"
                              data-testid={`prompts-memory-clear-${tpl.id}`}
                              onClick={() => {
                                localStorage.removeItem(tplStorageKey(tpl.content));
                                setMemoryTick((n) => n + 1);
                              }}
                              className="ml-1 text-error hover:underline"
                            >
                              {t('settings.templates.clear')}
                            </button>
                          </span>
                        );
                      } catch {
                        return null;
                      }
                    })()}
                    <button
                      type="button"
                      data-testid={`prompts-edit-${tpl.id}`}
                      onClick={() =>
                        setForm({
                          id: tpl.id,
                          name: tpl.name,
                          description: tpl.description,
                          content: tpl.content,
                        })
                      }
                      className="p-1 rounded hover:bg-bg-hover text-muted"
                      title={t('settings.templates.edit')}
                    >
                      <Pencil className="w-3.5 h-3.5" />
                    </button>
                    <button
                      type="button"
                      data-testid={`prompts-delete-${tpl.id}`}
                      onClick={() => void handleDelete(tpl.id)}
                      className="p-1 rounded hover:bg-error/10 text-muted hover:text-error"
                      title={t('settings.templates.delete')}
                    >
                      <span className="text-ui-2xs">{t('settings.templates.delete')}</span>
                    </button>
                  </div>
                </div>
              </li>
              </ContextMenu>
            ))}
        </ul>
      )}

      {(() => {
        // r56: 失联变量记忆 —— 模板已修改/删除后残留的 sage:tplfill: 键
        const boundKeys = new Set(templates.map((tpl) => tplStorageKey(tpl.content)));
        const orphans = listTplMemoryEntries().filter((e) => !boundKeys.has(e.key));
        // loading 中模板清单未就绪，避免把绑定记忆误判成失联
        if (loading || orphans.length === 0) return null;
        const remove = (key: string) => {
          try {
            window.localStorage.removeItem(key);
          } catch {
            // ignore
          }
          setMemoryTick((n) => n + 1);
        };
        return (
          <div
            className="p-3 rounded-radius-sm border border-border space-y-2"
            data-testid="tplmem-orphans"
          >
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs text-text">
                {t('settings.templates.orphans_heading').replace('{count}', String(orphans.length))}
              </p>
              <button
                type="button"
                data-testid="tplmem-orphan-clear-all"
                onClick={() => {
                  orphans.forEach((e) => remove(e.key));
                }}
                className="px-2 py-0.5 text-ui-2xs rounded-radius-sm border border-border text-muted hover:text-error shrink-0"
              >
                {t('settings.templates.clear_all')}
              </button>
            </div>
            <ul className="space-y-1">
              {orphans.map((e) => {
                const preview =
                  e.values !== null
                    ? Object.entries(e.values)
                        .map(([k, v]) => `${k}=${v}`)
                        .join(t('settings.templates.value_separator'))
                        .slice(0, 120)
                    : e.rawPreview || t('settings.templates.corrupted_value');
                return (
                  <li key={e.key} className="flex items-start justify-between gap-2">
                    <span className="min-w-0 text-ui-2xs">
                      <span className="font-mono text-muted">#{e.hash.slice(0, 8)}</span>
                      <span className="ml-2 text-text-secondary font-mono break-all">
                        {preview}
                      </span>
                    </span>
                    <button
                      type="button"
                      data-testid={`tplmem-orphan-remove-${e.hash}`}
                      onClick={() => remove(e.key)}
                      className="text-ui-2xs text-error hover:underline shrink-0"
                    >
                      {t('settings.templates.delete')}
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })()}
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditPromptTemplatesTabGovernance(): {
  module: 'src/pages/settings/PromptTemplatesTab.tsx';
  phase: 'P173';
  domain: 'settings';
  supportsOrphanTemplateMemoryCleanup: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/pages/settings/PromptTemplatesTab.tsx',
    phase: 'P173',
    domain: 'settings',
    supportsOrphanTemplateMemoryCleanup: true,
    compliant: true,
  };
}
