/**
 * Settings 页面 - Prompt 模板管理 Tab（R27-B）
 *
 * 用户自定义提示词模板的查看/新建/编辑/删除。数据经 promptApi
 * 走后端 /prompts/templates CRUD（KV 存储，上限 100 条）。
 * 斜杠面板（/tpl-<名称>）与该列表共享同一数据源，保存后重载即可见。
 */

import { Pencil, Plus, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { promptApi, type PromptTemplate } from '../../shared/api/promptApi';

const MAX_NAME_LEN = 60;
const MAX_CONTENT_LEN = 8000;

interface FormState {
  id: string | null; // null = 新建
  name: string;
  description: string;
  content: string;
}

const EMPTY_FORM: FormState = { id: null, name: '', description: '', content: '' };

export function PromptTemplatesTab() {
  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState<FormState | null>(null); // null = 列表态
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-text">提示词模板</h3>
          <p className="text-xs text-text-secondary mt-0.5">
            在聊天输入框输入 <code className="font-mono">/tpl-</code> 即可套用；也可用{' '}
            <code className="font-mono">/prompt-save</code> 把输入框内容直接存为模板。
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            data-testid="prompts-refresh"
            onClick={() => void load()}
            className="p-1.5 rounded hover:bg-bg-hover text-muted"
            title="刷新"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
          <button
            type="button"
            data-testid="prompts-new"
            onClick={() => setForm({ ...EMPTY_FORM })}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-radius-sm bg-primary text-text-inverse hover:bg-primary-hover"
          >
            <Plus className="w-3.5 h-3.5" />
            新建模板
          </button>
        </div>
      </div>

      {error && (
        <p className="text-xs text-error" data-testid="prompts-error">
          {error}
        </p>
      )}

      {form && (
        <div className="p-3 rounded-radius-sm border border-border space-y-2" data-testid="prompts-form">
          <input
            data-testid="prompts-form-name"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="模板名称（必填）"
            maxLength={MAX_NAME_LEN}
            className="w-full px-2 py-1.5 text-xs rounded-radius-sm border border-border bg-bg text-text"
          />
          <input
            data-testid="prompts-form-desc"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="描述（可选，斜杠菜单中显示）"
            maxLength={300}
            className="w-full px-2 py-1.5 text-xs rounded-radius-sm border border-border bg-bg text-text"
          />
          <textarea
            data-testid="prompts-form-content"
            value={form.content}
            onChange={(e) => setForm({ ...form, content: e.target.value })}
            placeholder="模板内容（支持 {{变量}} 占位）"
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
              取消
            </button>
            <button
              type="button"
              data-testid="prompts-form-save"
              disabled={saving || !form.name.trim() || !form.content.trim()}
              onClick={() => void handleSave()}
              className="px-2.5 py-1 text-xs rounded-radius-sm bg-primary text-text-inverse hover:bg-primary-hover disabled:opacity-50"
            >
              {saving ? '保存中…' : '保存'}
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <p className="text-xs text-text-secondary">加载中…</p>
      ) : templates.length === 0 ? (
        <p className="text-xs text-text-secondary" data-testid="prompts-empty">
          暂无模板 —— 点击"新建模板"创建，或在聊天输入框用 /prompt-save 保存。
        </p>
      ) : (
        <ul className="space-y-2" data-testid="prompts-list">
          {templates.map((tpl) => (
            <li
              key={tpl.id}
              className="p-3 rounded-radius-sm border border-border"
              data-testid="prompts-item"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-medium text-text">{tpl.name}</div>
                  {tpl.description && (
                    <div className="text-[11px] text-text-secondary">{tpl.description}</div>
                  )}
                  <div className="text-[11px] text-text-secondary font-mono mt-1 line-clamp-2">
                    {tpl.content.length > 120 ? `${tpl.content.slice(0, 120)}…` : tpl.content}
                  </div>
                </div>
                <div className="flex gap-1 shrink-0">
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
                    title="编辑"
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  <button
                    type="button"
                    data-testid={`prompts-delete-${tpl.id}`}
                    onClick={() => void handleDelete(tpl.id)}
                    className="p-1 rounded hover:bg-error/10 text-muted hover:text-error"
                    title="删除"
                  >
                    <span className="text-[11px]">删除</span>
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
