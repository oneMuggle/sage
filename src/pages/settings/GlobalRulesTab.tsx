/**
 * 全局规则 Tab (G1 / P0) —— 编辑 ~/.sage/SAGE.md。
 *
 * 路径由后端硬编码，本组件只负责：
 * - 加载当前内容 + 状态（exists / size / mtime / truncated / symlink）
 * - 提供编辑器（<textarea>）与草稿状态管理
 * - 保存、删除、从模板加载三类写操作
 * - 内联展示安全扫描拒绝原因（HTTP 422 / 413）
 */

import { useEffect, useMemo, useRef, useState } from 'react';

import {
  GLOBAL_RULES_CHAR_LIMIT,
  GlobalRulesError,
  GlobalRulesTemplate,
  globalRulesApi,
  normalizeGlobalRulesState,
  type GlobalRulesState,
} from '../../shared/api/globalRulesApi';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

import { SettingRow } from './components';

type SaveStatus = 'idle' | 'loading' | 'saving' | 'saved' | 'error';

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function formatMtime(epochSeconds: number | null): string {
  if (epochSeconds == null || epochSeconds === 0) return '—';
  return new Date(epochSeconds * 1000).toLocaleString();
}

export function GlobalRulesTab(): JSX.Element {
  const { t } = useI18n();

  const [state, setState] = useState<GlobalRulesState | null>(null);
  const [draft, setDraft] = useState('');
  const [status, setStatus] = useState<SaveStatus>('loading');
  const [error, setError] = useState<string | null>(null);
  const [lastSavedAt, setLastSavedAt] = useState<number | null>(null);
  const [templates, setTemplates] = useState<GlobalRulesTemplate[]>([]);
  // 「已保存」提示 3 秒后回 idle。用 ref 持 timer id，避免快速连续保存时旧 timer
  // 把新一次的「saved」状态提前清掉（code review 2026-10-27 stale-closure 修复）。
  const savedTimerRef = useRef<number | null>(null);

  const isDirty = useMemo(() => state !== null && draft !== state.content, [draft, state]);

  useEffect(() => {
    let cancelled = false;
    (async (): Promise<void> => {
      try {
        const next = await globalRulesApi.get();
        if (cancelled) return;
        setState(next);
        setDraft(next.content);
        setStatus('idle');
      } catch (err) {
        if (cancelled) return;
        setError(describeBackendError(t('settings.global_rules.load_failed'), err));
        setStatus('error');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [t]);

  useEffect(() => {
    let cancelled = false;
    (async (): Promise<void> => {
      try {
        const list = await globalRulesApi.templates();
        if (!cancelled) setTemplates(list);
      } catch {
        // 模板加载失败不阻断主流程
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSave = async (): Promise<void> => {
    if (!state) return;
    setError(null);
    setStatus('saving');
    if (savedTimerRef.current !== null) {
      window.clearTimeout(savedTimerRef.current);
      savedTimerRef.current = null;
    }
    try {
      const next = await globalRulesApi.save(draft);
      setState(next);
      setDraft(next.content);
      setStatus('saved');
      setLastSavedAt(Date.now());
      savedTimerRef.current = window.setTimeout(() => {
        savedTimerRef.current = null;
        setStatus((s) => (s === 'saved' ? 'idle' : s));
      }, 3000);
    } catch (err) {
      setError(describeSaveError(err, t));
      setStatus('error');
    }
  };

  const handleDelete = async (): Promise<void> => {
    setError(null);
    setStatus('saving');
    try {
      const result = await globalRulesApi.remove();
      const empty = normalizeGlobalRulesState({
        content: '',
        path: state?.path ?? '',
        exists: false,
        size: 0,
        mtime: null,
        truncated: false,
        char_limit: GLOBAL_RULES_CHAR_LIMIT,
        symlink: false,
      });
      setState(empty);
      setDraft('');
      setStatus('idle');
      setLastSavedAt(result.deleted ? Date.now() : lastSavedAt);
    } catch (err) {
      setError(describeBackendError(t('settings.global_rules.delete_failed'), err));
      setStatus('error');
    }
  };

  const handleTemplateApply = (template: GlobalRulesTemplate): void => {
    setDraft((current) =>
      current.trim() ? `${current.trimEnd()}\n\n${template.content}` : template.content,
    );
  };

  const handleReload = async (): Promise<void> => {
    setError(null);
    setStatus('loading');
    try {
      const next = await globalRulesApi.get();
      setState(next);
      setDraft(next.content);
      setStatus('idle');
    } catch (err) {
      setError(describeBackendError(t('settings.global_rules.load_failed'), err));
      setStatus('error');
    }
  };

  const charCount = draft.length;
  const overBudget = charCount > GLOBAL_RULES_CHAR_LIMIT;

  return (
    <div className="space-y-4">
      <SettingRow
        label={t('settings.global_rules.title')}
        desc={t('settings.global_rules.desc')}
        anchor="global_rules_editor"
      >
        <div className="flex flex-col gap-2 w-full">
          <StatusBanner
            state={state}
            status={status}
            error={error}
            lastSavedAt={lastSavedAt}
            onReload={handleReload}
          />
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={status === 'loading' || status === 'saving'}
            rows={16}
            spellCheck={false}
            placeholder={t('settings.global_rules.placeholder')}
            className="w-full px-3 py-2 text-ui-sm font-mono border border-border rounded bg-surface text-text focus:outline-none focus:ring-2 focus:ring-primary/60 resize-y"
            data-testid="settings-global-rules-editor"
          />
          <div className="flex items-center justify-between text-ui-xs text-muted">
            <div className="flex items-center gap-3">
              <span data-testid="settings-global-rules-char-count">
                {t('settings.global_rules.char_count').replace('{count}', String(charCount))}
              </span>
              {overBudget && (
                <span className="text-warning" data-testid="settings-global-rules-over-budget">
                  {t('settings.global_rules.over_budget').replace(
                    '{limit}',
                    String(GLOBAL_RULES_CHAR_LIMIT),
                  )}
                </span>
              )}
              {isDirty && (
                <span className="text-primary" data-testid="settings-global-rules-unsaved">
                  {t('settings.global_rules.unsaved')}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setDraft(state?.content ?? '')}
                disabled={!isDirty || status === 'saving' || status === 'loading'}
                className="px-3 py-1 rounded border border-border text-muted hover:text-text hover:bg-bg-hover disabled:opacity-40 disabled:cursor-not-allowed"
                data-testid="settings-global-rules-revert"
              >
                {t('settings.global_rules.revert')}
              </button>
              <button
                type="button"
                onClick={() => void handleDelete()}
                disabled={status === 'loading' || status === 'saving' || !state?.exists}
                className="px-3 py-1 rounded border border-border text-warning hover:bg-warning/10 disabled:opacity-40 disabled:cursor-not-allowed"
                data-testid="settings-global-rules-delete"
              >
                {t('settings.global_rules.delete')}
              </button>
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={!isDirty || status === 'saving' || status === 'loading'}
                className="px-3 py-1 rounded bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed"
                data-testid="settings-global-rules-save"
              >
                {status === 'saving'
                  ? t('settings.global_rules.saving')
                  : t('settings.global_rules.save')}
              </button>
            </div>
          </div>
        </div>
      </SettingRow>

      {templates.length > 0 && (
        <SettingRow
          label={t('settings.global_rules.templates.label')}
          desc={t('settings.global_rules.templates.desc')}
          anchor="global_rules_templates"
        >
          <div className="flex flex-wrap gap-2">
            {templates.map((tpl) => (
              <button
                key={tpl.id}
                type="button"
                onClick={() => handleTemplateApply(tpl)}
                className="px-3 py-1 text-ui-sm rounded border border-border text-muted hover:text-text hover:bg-bg-hover"
                data-testid={`settings-global-rules-template-${tpl.id}`}
              >
                {tpl.name}
              </button>
            ))}
          </div>
        </SettingRow>
      )}
    </div>
  );
}

function StatusBanner({
  state,
  status,
  error,
  lastSavedAt,
  onReload,
}: {
  state: GlobalRulesState | null;
  status: SaveStatus;
  error: string | null;
  lastSavedAt: number | null;
  onReload: () => void;
}): JSX.Element {
  const { t } = useI18n();

  if (status === 'loading') {
    return (
      <div
        role="status"
        className="text-ui-xs text-muted"
        data-testid="settings-global-rules-loading"
      >
        {t('settings.global_rules.loading')}
      </div>
    );
  }

  if (error) {
    return (
      <div
        role="alert"
        className="px-3 py-2 text-ui-xs rounded border border-warning/60 bg-warning/5 text-warning"
        data-testid="settings-global-rules-error"
      >
        <div>{error}</div>
        <button
          type="button"
          onClick={() => void onReload()}
          className="mt-1 underline hover:no-underline"
          data-testid="settings-global-rules-retry"
        >
          {t('settings.global_rules.retry')}
        </button>
      </div>
    );
  }

  if (!state) return <></>;

  return (
    <div
      className="flex flex-wrap items-center gap-x-4 gap-y-1 text-ui-xs text-muted"
      data-testid="settings-global-rules-status"
    >
      <span>{t('settings.global_rules.status.path').replace('{path}', state.path)}</span>
      <span>
        {state.exists
          ? t('settings.global_rules.status.size').replace('{size}', formatBytes(state.size))
          : t('settings.global_rules.status.missing')}
      </span>
      {state.exists && (
        <span>
          {t('settings.global_rules.status.mtime').replace('{time}', formatMtime(state.mtime))}
        </span>
      )}
      {state.truncated && (
        <span className="text-warning">
          {t('settings.global_rules.status.truncated').replace('{limit}', String(state.char_limit))}
        </span>
      )}
      {state.symlink && (
        <span className="text-warning">{t('settings.global_rules.status.symlink')}</span>
      )}
      {state.read_error && (
        <span className="text-warning">
          {t('settings.global_rules.status.read_error').replace('{reason}', state.read_error)}
        </span>
      )}
      {status === 'saved' && lastSavedAt && (
        <span className="text-primary">
          {t('settings.global_rules.saved_at').replace(
            '{time}',
            new Date(lastSavedAt).toLocaleTimeString(),
          )}
        </span>
      )}
    </div>
  );
}

/** 通用后端错误文案：本地化主句 + 后端原始细节（原始细节可能是英文/技术语）。 */
function describeBackendError(base: string, err: unknown): string {
  const detail = err instanceof GlobalRulesError ? err.message : String(err);
  return detail ? `${base}: ${detail}` : base;
}

function describeSaveError(err: unknown, t: (key: TranslationKey) => string): string {
  if (!(err instanceof GlobalRulesError)) {
    return t('settings.global_rules.error.generic');
  }
  switch (err.type) {
    case 'empty_content':
      return t('settings.global_rules.error.empty_content');
    case 'content_too_large':
      return t('settings.global_rules.error.content_too_large');
    case 'unsafe_content':
      return t('settings.global_rules.error.unsafe_content').replace(
        '{reason}',
        err.reason ?? err.message,
      );
    case 'symlink_target':
      return t('settings.global_rules.error.symlink_target');
    case 'write_failed':
      return t('settings.global_rules.error.write_failed');
    default:
      // 未知错误类型 → 兜底本地化文案，避免把后端英文/技术字符串直接透出。
      return t('settings.global_rules.error.generic');
  }
}
