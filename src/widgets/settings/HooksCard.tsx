// src/widgets/settings/HooksCard.tsx
//
// U9 hooks 配置 UI (对标增强第二轮批次 C-2)。
// hooks 以 JSON 列表存于 preferences KV `hooks`(白名单键), 后端
// load_hooks fail-open 校验; 本组件提供 CRUD + 保存。
// L11 新事件 user_prompt_submit / stop 一并可选。

import { Plus, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { invoke } from '../../shared/api/desktopInvoke';

interface HookEntry {
  event: string;
  matcher: string;
  command: string;
  timeout_seconds: number;
}

const HOOK_EVENT_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'pre_tool_use', label: '工具执行前' },
  { value: 'post_tool_use', label: '工具执行后' },
  { value: 'user_prompt_submit', label: '消息提交时' },
  { value: 'stop', label: '回复结束时' },
];

const MAX_HOOKS = 20;

function parseHooks(raw: string | null): HookEntry[] {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item): item is HookEntry =>
        typeof item === 'object' &&
        item !== null &&
        typeof (item as HookEntry).command === 'string' &&
        typeof (item as HookEntry).event === 'string',
    );
  } catch {
    return [];
  }
}

export function HooksCard(): JSX.Element | null {
  const [hooks, setHooks] = useState<HookEntry[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    invoke<{ value: string | null }>('get_preference', { key: 'hooks' })
      .then((resp) => setHooks(parseHooks(resp.value)))
      .catch(() => setHooks([]))
      .finally(() => setLoaded(true));
  }, []);

  const save = (next: HookEntry[]): void => {
    setHooks(next);
    setSaving(true);
    invoke('set_preference', { key: 'hooks', value: JSON.stringify(next), valueType: 'json' })
      .then(() => toast.success('钩子配置已保存'))
      .catch((e: unknown) => toast.error(e instanceof Error ? e.message : '保存失败'))
      .finally(() => setSaving(false));
  };

  const update = (index: number, patch: Partial<HookEntry>): void => {
    save(hooks.map((h, i) => (i === index ? { ...h, ...patch } : h)));
  };

  const remove = (index: number): void => {
    save(hooks.filter((_, i) => i !== index));
  };

  const add = (): void => {
    if (hooks.length >= MAX_HOOKS) {
      toast.error(`最多 ${MAX_HOOKS} 条钩子`);
      return;
    }
    save([
      ...hooks,
      { event: 'pre_tool_use', matcher: '*', command: '', timeout_seconds: 10 },
    ]);
  };

  if (!loaded) return null;

  return (
    <div data-testid="hooks-card">
      {hooks.length === 0 ? (
        <p className="text-xs text-muted mb-2">暂无自定义钩子。钩子是你在事件点自动执行的 shell 命令(收 JSON payload)。</p>
      ) : (
        <div className="space-y-2 mb-2">
          {hooks.map((hook, idx) => (
            <div
              key={idx}
              className="flex flex-wrap items-center gap-2 border border-border rounded-radius-sm p-2"
              data-testid="hook-row"
            >
              <select
                aria-label="钩子事件"
                className="text-xs border border-border rounded-radius-sm px-1.5 py-1 bg-surface text-text"
                value={hook.event}
                onChange={(e) => update(idx, { event: e.target.value })}
              >
                {HOOK_EVENT_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <input
                aria-label="匹配器"
                title="工具名 glob 匹配(仅工具事件有效)"
                className="w-24 text-xs border border-border rounded-radius-sm px-1.5 py-1 bg-surface text-text"
                value={hook.matcher}
                onChange={(e) => update(idx, { matcher: e.target.value })}
                placeholder="*"
              />
              <input
                aria-label="命令"
                className="flex-1 min-w-48 text-xs border border-border rounded-radius-sm px-1.5 py-1 bg-surface text-text font-mono"
                value={hook.command}
                onChange={(e) => update(idx, { command: e.target.value })}
                placeholder="shell 命令(STDIN 收 JSON)"
              />
              <button
                aria-label={`删除钩子 ${idx + 1}`}
                className="p-1.5 rounded hover:bg-bg-hover text-text-secondary hover:text-red-500"
                onClick={() => remove(idx)}
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
      <div className="flex items-center gap-2">
        <button
          className="px-2 py-1 text-xs border border-border rounded-radius-sm hover:bg-bg-hover transition-colors flex items-center gap-1"
          onClick={add}
          data-testid="hooks-add"
        >
          <Plus className="w-3 h-3" /> 添加钩子
        </button>
        {saving && <span className="text-xs text-muted">保存中…</span>}
        <span className="text-[10px] text-muted">修改即时保存;事件点: 工具前/后、消息提交、回复结束</span>
      </div>
    </div>
  );
}
