// src/widgets/memory/ProjectProfileCard.tsx
//
// P2 scope 轴: "项目画像" —— 项目级 MEMORY.md 的可编辑卡片。
// 与 UserProfileCard("关于我") 同构，但按 project_key(工作区绝对路径)分组：
// 只有会话绑定了同一项目时，这些条目才会以冻结快照注入 system prompt。
//
// 数据源: GET/POST/DELETE /api/v1/memory/project-profile[/{id}]。

import { Check, FolderGit2, Plus, Trash2, X } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { memoryApi } from '../../shared/api';
import type { ProjectProfileEntry } from '../../shared/api/types';

const CATEGORY_LABEL: Record<string, string> = {
  convention: '约定',
  architecture: '架构',
  decision: '决策',
  goal: '目标',
  note: '备注',
};

const DEFAULT_CATEGORIES = Object.keys(CATEGORY_LABEL);

function labelOf(category: string): string {
  return CATEGORY_LABEL[category] ?? category;
}

function basenameOf(projectKey: string): string {
  const parts = projectKey.replace(/[/\\]+$/, '').split(/[/\\]/);
  return parts[parts.length - 1] || projectKey;
}

interface EditorState {
  content: string;
  category: string;
  importance: number;
}

export function ProjectProfileCard() {
  const [items, setItems] = useState<ProjectProfileEntry[]>([]);
  const [projects, setProjects] = useState<string[]>([]);
  const [projectKey, setProjectKey] = useState('');
  const [categories, setCategories] = useState<string[]>(DEFAULT_CATEGORIES);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState<EditorState>({
    content: '',
    category: 'convention',
    importance: 5,
  });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await memoryApi.getProjectProfile({
        projectKey: projectKey || undefined,
      });
      setItems(res.items);
      setProjects(res.projects);
      if (res.categories.length > 0) setCategories(res.categories);
      // 首次进入且后端已解析出归属(或未指定)时,回填选择器
      if (!projectKey && res.project_key) setProjectKey(res.project_key);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载项目画像失败');
    } finally {
      setLoading(false);
    }
  }, [projectKey]);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (op: () => Promise<void>, failMsg: string): Promise<boolean> => {
    setBusy(true);
    setError(null);
    try {
      await op();
      await load();
      return true;
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : failMsg);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const handleCreate = async (): Promise<void> => {
    const content = draft.content.trim();
    if (!content || !projectKey) return;
    const ok = await run(async () => {
      const created = await memoryApi.createProjectProfile(content, {
        projectKey,
        category: draft.category,
        importance: draft.importance,
      });
      if (!created) throw new Error('内容为空或与现有画像重复');
    }, '新增项目画像失败');
    if (ok) {
      setAdding(false);
      setDraft({ content: '', category: draft.category, importance: 5 });
    }
  };

  const handleDelete = (id: string) =>
    run(() => memoryApi.deleteProjectProfile(id), '删除项目画像失败');

  return (
    <section
      className="mb-5 rounded-radius-md border border-border bg-surface p-4"
      data-testid="project-profile-card"
    >
      <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <FolderGit2 className="w-4 h-4 text-primary shrink-0" aria-hidden />
          <h3 className="text-sm font-semibold text-text">项目画像</h3>
          <span className="text-xs text-text-secondary truncate">
            每个项目一份 MEMORY.md，仅在该项目的会话中注入
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <select
            value={projectKey}
            onChange={(e) => setProjectKey(e.target.value)}
            className="max-w-64 px-2 py-1 text-xs rounded border border-border bg-bg text-text"
            data-testid="project-profile-select"
          >
            <option value="">选择项目…</option>
            {projects.map((p) => (
              <option key={p} value={p}>
                {basenameOf(p)} — {p}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => {
              setAdding(true);
            }}
            disabled={adding || busy || !projectKey}
            className="flex items-center gap-1 px-2 py-1 text-xs rounded border border-border hover:bg-bg-hover disabled:opacity-50"
            data-testid="project-profile-add"
          >
            <Plus className="w-3 h-3" aria-hidden />
            添加
          </button>
        </div>
      </div>

      {error && (
        <p className="mb-2 text-xs text-error" data-testid="project-profile-error">
          {error}
        </p>
      )}

      {adding && (
        <div className="mb-3 p-2 rounded border border-primary/40 bg-primary/5">
          <textarea
            value={draft.content}
            onChange={(e) => setDraft((s) => ({ ...s, content: e.target.value }))}
            rows={2}
            maxLength={200}
            placeholder="一句话描述项目级约定，例如：接口统一用 REST、包管理器用 pnpm"
            className="w-full px-2 py-1.5 text-xs rounded border border-border bg-bg text-text resize-none focus:outline-none focus:border-primary"
            data-testid="project-profile-editor-content"
          />
          <div className="flex items-center gap-2 flex-wrap mt-2">
            <select
              value={draft.category}
              onChange={(e) => setDraft((s) => ({ ...s, category: e.target.value }))}
              className="px-2 py-1 text-xs rounded border border-border bg-bg text-text"
            >
              {categories.map((c) => (
                <option key={c} value={c}>
                  {labelOf(c)}
                </option>
              ))}
            </select>
            <label className="flex items-center gap-1 text-xs text-text-secondary">
              重要性
              <input
                type="number"
                min={1}
                max={10}
                value={draft.importance}
                onChange={(e) =>
                  setDraft((s) => ({
                    ...s,
                    importance: Math.min(10, Math.max(1, Number(e.target.value) || 5)),
                  }))
                }
                className="w-12 px-1.5 py-1 text-xs rounded border border-border bg-bg text-text"
              />
            </label>
            <span className="flex-1" />
            <button
              type="button"
              onClick={() => setAdding(false)}
              disabled={busy}
              className="flex items-center gap-1 px-2 py-1 text-xs rounded border border-border hover:bg-bg-hover disabled:opacity-50"
            >
              <X className="w-3 h-3" aria-hidden />
              取消
            </button>
            <button
              type="button"
              onClick={() => void handleCreate()}
              disabled={draft.content.trim().length === 0 || busy}
              className="flex items-center gap-1 px-2 py-1 text-xs rounded bg-primary text-text-inverse hover:bg-primary-hover disabled:opacity-50"
              data-testid="project-profile-editor-submit"
            >
              <Check className="w-3 h-3" aria-hidden />
              保存
            </button>
          </div>
        </div>
      )}

      {loading && items.length === 0 ? (
        <p className="text-xs text-text-secondary">加载中...</p>
      ) : items.length === 0 && !adding ? (
        <p className="text-xs text-text-secondary" data-testid="project-profile-empty">
          {projectKey
            ? '该项目还没有画像条目。约定、架构决策等"项目级长期记忆"适合写在这里。'
            : '选择项目后即可查看/维护该项目的画像。'}
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-border">
          {items.map((e) => (
            <li key={e.id} className="py-2 first:pt-0 last:pb-0" data-testid="project-profile-item">
              <div className="flex items-start gap-2">
                <span className="mt-0.5 px-1.5 py-0.5 text-[10px] rounded bg-bg-hover text-text-secondary shrink-0">
                  {labelOf(e.category)}
                </span>
                <p className="flex-1 min-w-0 text-xs text-text break-words">{e.content}</p>
                <span className="text-[10px] text-text-secondary shrink-0" title="重要性">
                  ★{e.importance}
                </span>
                <button
                  type="button"
                  onClick={() => void handleDelete(e.id)}
                  disabled={busy}
                  className="p-1 rounded hover:bg-bg-hover text-error disabled:opacity-50 shrink-0"
                  aria-label="删除"
                  data-testid="project-profile-delete"
                >
                  <Trash2 className="w-3 h-3" aria-hidden />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
