// src/widgets/memory/UserProfileCard.tsx
//
// 对标 S2 (2026-09-13): "关于我" —— 可编辑的用户画像卡片。
// 对标 ChatGPT "Manage memories" / Claude 用户偏好面板: 把后端
// UserProfileStore（自动提取 + 手动写入的稳定偏好）直接暴露给用户
// 查看 / 新增 / 编辑 / 删除。写入后后端立即刷新冻结快照，下一轮对话生效。
//
// 数据源: GET/POST/PUT/DELETE /api/v1/memory/profile[/{id}]。

import { Check, Pencil, Plus, Trash2, UserRound, X } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { memoryApi } from '../../shared/api';
import type { UserProfileEntry } from '../../shared/api/types';

const CATEGORY_LABEL: Record<string, string> = {
  preference: '偏好',
  communication_style: '沟通风格',
  workflow_habit: '工作习惯',
  identity: '身份背景',
};

const DEFAULT_CATEGORIES = Object.keys(CATEGORY_LABEL);

function labelOf(category: string): string {
  return CATEGORY_LABEL[category] ?? category;
}

interface EditorState {
  content: string;
  category: string;
  importance: number;
}

interface EntryEditorProps {
  initial: EditorState;
  categories: string[];
  busy: boolean;
  onCancel: () => void;
  onSubmit: (s: EditorState) => void;
}

function EntryEditor({ initial, categories, busy, onCancel, onSubmit }: EntryEditorProps) {
  const [state, setState] = useState<EditorState>(initial);
  const canSubmit = state.content.trim().length > 0 && !busy;
  return (
    <div className="flex flex-col gap-2" data-testid="profile-editor">
      <textarea
        value={state.content}
        onChange={(e) => setState((s) => ({ ...s, content: e.target.value }))}
        rows={2}
        maxLength={200}
        placeholder="一句话描述，例如：偏好简洁回答、常用 Python、引用格式 GB/T 7714"
        className="w-full px-2 py-1.5 text-xs rounded border border-border bg-bg text-text resize-none focus:outline-none focus:border-primary"
        data-testid="profile-editor-content"
      />
      <div className="flex items-center gap-2 flex-wrap">
        <select
          value={state.category}
          onChange={(e) => setState((s) => ({ ...s, category: e.target.value }))}
          className="px-2 py-1 text-xs rounded border border-border bg-bg text-text"
          data-testid="profile-editor-category"
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
            value={state.importance}
            onChange={(e) =>
              setState((s) => ({
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
          onClick={onCancel}
          disabled={busy}
          className="flex items-center gap-1 px-2 py-1 text-xs rounded border border-border hover:bg-bg-hover disabled:opacity-50"
        >
          <X className="w-3 h-3" aria-hidden />
          取消
        </button>
        <button
          type="button"
          onClick={() => onSubmit({ ...state, content: state.content.trim() })}
          disabled={!canSubmit}
          className="flex items-center gap-1 px-2 py-1 text-xs rounded bg-primary text-text-inverse hover:bg-primary-hover disabled:opacity-50"
          data-testid="profile-editor-submit"
        >
          <Check className="w-3 h-3" aria-hidden />
          保存
        </button>
      </div>
    </div>
  );
}

export function UserProfileCard() {
  const [items, setItems] = useState<UserProfileEntry[]>([]);
  const [categories, setCategories] = useState<string[]>(DEFAULT_CATEGORIES);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await memoryApi.getUserProfile();
      setItems(res.items);
      if (res.categories.length > 0) setCategories(res.categories);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载画像失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const run = async (op: () => Promise<void>, failMsg: string): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await op();
      await load();
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : failMsg);
    } finally {
      setBusy(false);
    }
  };

  const handleCreate = (s: EditorState) =>
    run(async () => {
      const created = await memoryApi.createUserProfile(s.content, s.category, s.importance);
      if (!created) throw new Error('内容为空或与现有画像重复');
      setAdding(false);
    }, '新增画像失败');

  const handleUpdate = (id: string, s: EditorState) =>
    run(async () => {
      await memoryApi.updateUserProfile(id, s);
      setEditingId(null);
    }, '更新画像失败');

  const handleDelete = (id: string) => run(() => memoryApi.deleteUserProfile(id), '删除画像失败');

  return (
    <section
      className="mb-5 rounded-radius-md border border-border bg-surface p-4"
      data-testid="user-profile-card"
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2 min-w-0">
          <UserRound className="w-4 h-4 text-accent shrink-0" aria-hidden />
          <h3 className="text-sm font-semibold text-text">关于我</h3>
          <span className="text-xs text-text-secondary truncate">
            Sage 在每次对话中都会参考这些稳定偏好 · 自动提取 + 手动维护
          </span>
        </div>
        <button
          type="button"
          onClick={() => {
            setAdding(true);
            setEditingId(null);
          }}
          disabled={adding || busy}
          className="flex items-center gap-1 px-2 py-1 text-xs rounded border border-border hover:bg-bg-hover disabled:opacity-50 shrink-0"
          data-testid="profile-add"
        >
          <Plus className="w-3 h-3" aria-hidden />
          添加
        </button>
      </div>

      {error && (
        <p className="mb-2 text-xs text-error" data-testid="profile-error">
          {error}
        </p>
      )}

      {adding && (
        <div className="mb-3 p-2 rounded border border-primary/40 bg-primary/5">
          <EntryEditor
            initial={{ content: '', category: categories[0] ?? 'preference', importance: 5 }}
            categories={categories}
            busy={busy}
            onCancel={() => setAdding(false)}
            onSubmit={(s) => void handleCreate(s)}
          />
        </div>
      )}

      {loading && items.length === 0 ? (
        <p className="text-xs text-text-secondary">加载中...</p>
      ) : items.length === 0 && !adding ? (
        <p className="text-xs text-text-secondary" data-testid="profile-empty">
          还没有画像条目。随着对话进行 Sage 会自动学习你的偏好，也可以点“添加”手动写入。
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-border">
          {items.map((e) => (
            <li key={e.id} className="py-2 first:pt-0 last:pb-0" data-testid="profile-item">
              {editingId === e.id ? (
                <EntryEditor
                  initial={{ content: e.content, category: e.category, importance: e.importance }}
                  categories={categories}
                  busy={busy}
                  onCancel={() => setEditingId(null)}
                  onSubmit={(s) => void handleUpdate(e.id, s)}
                />
              ) : (
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
                    onClick={() => {
                      setEditingId(e.id);
                      setAdding(false);
                    }}
                    disabled={busy}
                    className="p-1 rounded hover:bg-bg-hover disabled:opacity-50 shrink-0"
                    aria-label="编辑"
                    data-testid="profile-edit"
                  >
                    <Pencil className="w-3 h-3" aria-hidden />
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleDelete(e.id)}
                    disabled={busy}
                    className="p-1 rounded hover:bg-bg-hover text-error disabled:opacity-50 shrink-0"
                    aria-label="删除"
                    data-testid="profile-delete"
                  >
                    <Trash2 className="w-3 h-3" aria-hidden />
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
