// src/widgets/settings/HooksCard.tsx
//
// U9 hooks 配置 UI (对标增强第二轮批次 C-2)。
// hooks 以 JSON 列表存于 preferences KV `hooks`(白名单键), 后端
// load_hooks fail-open 校验; 本组件提供 CRUD + 保存。
// L11 新事件 user_prompt_submit / stop 一并可选。
// Phase 1 (2026-09-19): 新增 "推荐 Hook" 区域 —— 内置钩子 (安全守卫 /
// 敏感信息拦截 / 审计日志 / 成本预警) 一键启用, 元数据来自后端
// GET /api/v1/hooks/builtins, 避免前后端元数据漂移。

import { DollarSign, FileText, Lock, Loader2, Plus, Shield, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { backendRequest } from '../../shared/api/backendRequest';
import { invoke } from '../../shared/api/desktopInvoke';
import { HookHistoryPanel } from './HookHistoryPanel';

interface HookEntry {
  event: string;
  matcher: string;
  command: string;
  timeout_seconds: number;
  hook_type?: string;
  handler?: string;
  builtin_id?: string;
  config?: Record<string, unknown>;
}

interface BuiltinHook {
  id: string;
  name: string;
  description: string;
  icon: string;
  event: string;
  matcher: string;
  handler: string;
  default_config: Record<string, unknown>;
}

const BUILTIN_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  shield: Shield,
  lock: Lock,
  'file-text': FileText,
  'dollar-sign': DollarSign,
};

const HOOK_EVENT_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'pre_tool_use', label: '工具执行前' },
  { value: 'post_tool_use', label: '工具执行后' },
  { value: 'user_prompt_submit', label: '消息提交时' },
  { value: 'stop', label: '回复结束时' },
  { value: 'session_start', label: '会话创建时' },
  { value: 'session_stop', label: '会话删除时' },
  { value: 'error_occurred', label: '工具出错时' },
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

function builtinToEntry(b: BuiltinHook): HookEntry {
  return {
    event: b.event,
    matcher: b.matcher,
    command: '',
    hook_type: 'python',
    handler: b.handler,
    builtin_id: b.id,
    timeout_seconds: 10,
    config: b.default_config,
  };
}

export function HooksCard(): JSX.Element | null {
  const [hooks, setHooks] = useState<HookEntry[]>([]);
  const [builtins, setBuiltins] = useState<BuiltinHook[]>([]);
  const [builtinsLoading, setBuiltinsLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);

  // 1) 加载用户自定义 + 已启用内置钩子
  useEffect(() => {
    let alive = true;
    invoke<{ value: string | null }>('get_preference', { key: 'hooks' })
      .then((resp) => {
        if (alive) setHooks(parseHooks(resp.value));
      })
      .catch(() => {
        if (alive) setHooks([]);
      })
      .finally(() => {
        if (alive) setLoaded(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  // 2) 加载后端内置钩子元数据 (设置页"推荐 Hook"数据源)
  useEffect(() => {
    let alive = true;
    backendRequest<{ builtins: BuiltinHook[] }>({
      method: 'GET',
      path: '/api/v1/hooks/builtins',
    })
      .then((resp) => {
        if (alive && Array.isArray(resp?.builtins)) {
          setBuiltins(resp.builtins);
        }
      })
      .catch(() => {
        // 内置列表失败不影响自定义钩子功能 (fail-open)
      })
      .finally(() => {
        if (alive) setBuiltinsLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const enabledBuiltinIds = new Set(
    hooks.filter((h) => !!h.builtin_id).map((h) => h.builtin_id as string),
  );

  const customHooksWithOriginalIdx = hooks
    .map((h, originalIdx) => ({ hook: h, originalIdx }))
    .filter(({ hook }) => !hook.builtin_id);

  const save = (next: HookEntry[]): void => {
    setHooks(next);
    setSaving(true);
    invoke('set_preference', { key: 'hooks', value: JSON.stringify(next), valueType: 'json' })
      .then(() => toast.success('钩子配置已保存'))
      .catch((e: unknown) => toast.error(e instanceof Error ? e.message : '保存失败'))
      .finally(() => setSaving(false));
  };

  const update = (originalIdx: number, patch: Partial<HookEntry>): void => {
    save(hooks.map((h, i) => (i === originalIdx ? { ...h, ...patch } : h)));
  };

  const removeAt = (originalIdx: number): void => {
    save(hooks.filter((_, i) => i !== originalIdx));
  };

  const add = (): void => {
    if (hooks.length >= MAX_HOOKS) {
      toast.error(`最多 ${MAX_HOOKS} 条钩子`);
      return;
    }
    save([...hooks, { event: 'pre_tool_use', matcher: '*', command: '', timeout_seconds: 10 }]);
  };

  const toggleBuiltin = (builtin: BuiltinHook): void => {
    if (enabledBuiltinIds.has(builtin.id)) {
      save(hooks.filter((h) => h.builtin_id !== builtin.id));
      toast.success(`已禁用内置钩子: ${builtin.name}`);
      return;
    }
    if (hooks.length >= MAX_HOOKS) {
      toast.error(`最多 ${MAX_HOOKS} 条钩子`);
      return;
    }
    save([...hooks, builtinToEntry(builtin)]);
    toast.success(`已启用内置钩子: ${builtin.name}`);
  };

  if (!loaded) return null;

  return (
    <div data-testid="hooks-card">
      {/* 推荐 Hook 区域 */}
      {builtins.length > 0 && (
        <div className="mb-4">
          <div className="text-xs text-text-secondary mb-2">推荐 Hook (一键启用内置防护)</div>
          <div className="space-y-1.5">
            {builtins.map((builtin) => {
              const Icon = BUILTIN_ICONS[builtin.icon] ?? Shield;
              const enabled = enabledBuiltinIds.has(builtin.id);
              return (
                <div
                  key={builtin.id}
                  className="flex items-center gap-2 border border-border rounded-radius-sm p-2"
                  data-testid={`builtin-row-${builtin.id}`}
                >
                  <Icon className="w-4 h-4 text-text-secondary flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-medium">{builtin.name}</div>
                    <div className="text-[10px] text-muted truncate">{builtin.description}</div>
                  </div>
                  <button
                    type="button"
                    aria-label={`${enabled ? '禁用' : '启用'}内置钩子 ${builtin.name}`}
                    className={`px-2 py-1 text-xs rounded-radius-sm border transition-colors ${
                      enabled
                        ? 'border-accent text-accent hover:bg-accent/10'
                        : 'border-border text-text-secondary hover:bg-bg-hover'
                    }`}
                    onClick={() => toggleBuiltin(builtin)}
                    data-testid={`builtin-toggle-${builtin.id}`}
                  >
                    {enabled ? '已启用' : '启用'}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}
      {builtinsLoading && (
        <div className="flex items-center gap-1 text-xs text-muted mb-2">
          <Loader2 className="w-3 h-3 animate-spin" /> 加载内置钩子…
        </div>
      )}

      {/* 自定义钩子 CRUD */}
      {customHooksWithOriginalIdx.length === 0 ? (
        <p className="text-xs text-muted mb-2">
          暂无自定义钩子。钩子是你在事件点自动执行的 shell 命令(收 JSON payload)。
        </p>
      ) : (
        <div className="space-y-2 mb-2">
          {customHooksWithOriginalIdx.map(({ hook, originalIdx }) => (
            <div
              key={originalIdx}
              className="flex flex-wrap items-center gap-2 border border-border rounded-radius-sm p-2"
              data-testid="hook-row"
            >
              <select
                aria-label="钩子事件"
                className="text-xs border border-border rounded-radius-sm px-1.5 py-1 bg-surface text-text"
                value={hook.event}
                onChange={(e) => update(originalIdx, { event: e.target.value })}
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
                onChange={(e) => update(originalIdx, { matcher: e.target.value })}
                placeholder="*"
              />
              <input
                aria-label="命令"
                className="flex-1 min-w-48 text-xs border border-border rounded-radius-sm px-1.5 py-1 bg-surface text-text font-mono"
                value={hook.command}
                onChange={(e) => update(originalIdx, { command: e.target.value })}
                placeholder="shell 命令(STDIN 收 JSON)"
              />
              <button
                aria-label={`删除钩子 ${originalIdx + 1}`}
                className="p-1.5 rounded hover:bg-bg-hover text-text-secondary hover:text-red-500"
                onClick={() => removeAt(originalIdx)}
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
        <span className="text-[10px] text-muted">
          修改即时保存;事件点: 工具前/后、消息提交、回复结束、会话创建/删除、工具出错
        </span>
      </div>
      <HookHistoryPanel />
    </div>
  );
}
