/**
 * 标题栏浏览器实例指示器（P1）+ 实例面板（P2）。
 *
 * - P1：轮询 ``/browser/status`` 显示 ``活跃/上限``；无活跃实例时整体隐藏。
 * - P2：点按展开面板，可重命名实例、把实例绑定到当前会话（快速切换）。
 *
 * 轮询失败（后端未就绪 / 401）时静默保留上次快照，不打扰用户。
 */

import { Check, Globe, Pencil } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import {
  fetchBrowserStatus,
  updateSessionName,
  type BrowserSessionInfo,
  type BrowserStatusResponse,
} from '../../shared/api/browserSettingsClient';
import { useI18n } from '../../shared/lib/i18n';
import { useStore } from '../../shared/lib/store';

import { rememberBrowserSession, useBrowserSessionStore } from './browserSessionStore';

const POLL_MS = 5000;

export function BrowserSessionStatus() {
  const { t } = useI18n();
  const [status, setStatus] = useState<BrowserStatusResponse | null>(null);
  const [open, setOpen] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [draftName, setDraftName] = useState('');
  const rootRef = useRef<HTMLDivElement | null>(null);

  const currentSessionId = useStore((s) => s.currentSessionId);
  const boundSessionId = useBrowserSessionStore((s) =>
    currentSessionId ? (s.byConversation[currentSessionId] ?? null) : null,
  );

  const refresh = useCallback(async () => {
    try {
      setStatus(await fetchBrowserStatus());
    } catch {
      // 后端未就绪 / 无授权：静默保留上次快照
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, [open]);

  if (!status || status.active <= 0) return null;

  const bind = (sessionId: string): void => {
    if (!currentSessionId) return;
    rememberBrowserSession(currentSessionId, sessionId);
  };

  const commitRename = async (session: BrowserSessionInfo): Promise<void> => {
    const name = draftName.trim();
    setRenamingId(null);
    if (!name || name === session.name) return;
    try {
      await updateSessionName(session.id, name);
      toast.success(t('settings.network.browser.rename_saved'));
      await refresh();
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : String(cause));
    }
  };

  return (
    <div ref={rootRef} className="no-drag relative">
      <button
        type="button"
        data-testid="browser-session-status"
        aria-label={t('settings.network.browser.status_dot_hint')}
        aria-expanded={open}
        title={t('settings.network.browser.status_dot_hint')}
        onClick={() => setOpen((value) => !value)}
        className="flex items-center gap-1 px-2 py-1 rounded-radius-sm text-xs text-text-secondary hover:bg-bg-hover hover:text-text transition-colors"
      >
        <Globe className="w-3.5 h-3.5" />
        <span className="font-mono">
          {status.active}/{status.max}
        </span>
      </button>

      {open && (
        <div
          data-testid="browser-session-panel"
          className="absolute right-0 top-full mt-1 z-50 w-72 rounded-radius-sm border border-border bg-surface shadow-lg p-2"
        >
          <div className="px-1 pb-2 mb-1 border-b border-border">
            <div className="text-xs font-semibold text-text">
              {t('settings.network.browser.panel_title')}
            </div>
            <div className="text-xs text-muted mt-0.5">
              {t('settings.network.browser.panel_hint')}
            </div>
          </div>
          {status.sessions.length === 0 ? (
            <div className="px-1 py-2 text-xs text-muted">
              {t('settings.network.browser.panel_empty')}
            </div>
          ) : (
            <ul className="space-y-1">
              {status.sessions.map((session) => {
                const isBound = boundSessionId === session.id;
                const displayName = session.name || session.id.slice(0, 8);
                return (
                  <li
                    key={session.id}
                    className={`rounded-radius-sm px-2 py-1.5 ${
                      isBound ? 'bg-primary/5 border border-primary/40' : ''
                    }`}
                  >
                    <div className="flex items-center gap-1.5">
                      {renamingId === session.id ? (
                        <input
                          autoFocus
                          value={draftName}
                          onChange={(event) => setDraftName(event.target.value)}
                          onBlur={() => void commitRename(session)}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter') void commitRename(session);
                            if (event.key === 'Escape') setRenamingId(null);
                          }}
                          className="flex-1 min-w-0 px-1.5 py-0.5 text-xs bg-surface border border-border rounded-radius-sm"
                          data-testid={`browser-session-rename-input-${session.id}`}
                        />
                      ) : (
                        <span className="flex-1 min-w-0 truncate text-xs text-text">
                          {displayName}
                        </span>
                      )}
                      <button
                        type="button"
                        aria-label={t('settings.network.browser.panel_rename')}
                        title={t('settings.network.browser.panel_rename')}
                        onClick={() => {
                          setRenamingId(session.id);
                          setDraftName(session.name || '');
                        }}
                        className="p-1 rounded-radius-sm text-muted hover:bg-bg-hover hover:text-text transition-colors"
                      >
                        <Pencil className="w-3 h-3" />
                      </button>
                      <button
                        type="button"
                        disabled={!currentSessionId || isBound}
                        onClick={() => bind(session.id)}
                        title={
                          isBound
                            ? t('settings.network.browser.panel_bound')
                            : t('settings.network.browser.panel_bind')
                        }
                        className="p-1 rounded-radius-sm text-muted hover:bg-bg-hover hover:text-text disabled:opacity-40 transition-colors"
                        data-testid={`browser-session-bind-${session.id}`}
                      >
                        <Check className={`w-3 h-3 ${isBound ? 'text-primary' : ''}`} />
                      </button>
                    </div>
                    <div className="text-xs text-muted mt-0.5">
                      {t('settings.network.browser.panel_last_used')}: {session.last_used_at || '—'}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
