/**
 * Pet status panel.
 *
 * Rendered inside the pet window; the main process grows the window while
 * this panel is open. Shows the selected session plus all active sessions.
 */

import type { PetConfigBridge, PetSnapshotBridge } from '../shared/types/electron-api';

import {
  contextPercent,
  formatTokens,
  isActiveAction,
  progressLabel,
  relativeTime,
  sessionLabel,
  statusLabel,
  toolLabel,
} from './engine/labels';

interface PetPanelProps {
  snapshot: PetSnapshotBridge;
  config: PetConfigBridge;
  onClose: () => void;
  onOpenSession: (sessionId: string) => void;
  onOpenSettings: () => void;
}

const TERMINAL_LABELS = {
  done: { zh: '已完成', en: 'Completed' },
  error: { zh: '出错', en: 'Error' },
} as const;

function terminalLabel(action: 'done' | 'error' | null): string {
  if (!action) return '';
  const zh = typeof navigator !== 'undefined' && navigator.language.toLowerCase().startsWith('zh');
  return TERMINAL_LABELS[action][zh ? 'zh' : 'en'];
}

export function PetPanel({
  snapshot,
  config,
  onClose,
  onOpenSession,
  onOpenSettings,
}: PetPanelProps): JSX.Element {
  const current = snapshot.sessions[0] ?? null;
  const action = current?.action ?? snapshot.action;
  const detail = current?.detail ?? snapshot.detail;
  const toolName = current?.toolName ?? snapshot.toolName;
  const title = sessionLabel(
    current?.sessionTitle ?? snapshot.sessionTitle,
    current?.sessionId ?? snapshot.sessionId,
  );
  const status = statusLabel(action, detail, toolName);
  const tool = toolLabel(detail, toolName);
  const todoDone = current?.todoDone ?? snapshot.todoDone;
  const todoTotal = current?.todoTotal ?? snapshot.todoTotal;
  const progressKind = current?.progressKind ?? snapshot.progressKind;
  const todoActive = current?.todoActive ?? snapshot.todoActive;
  const contextUsed = current?.contextUsed ?? snapshot.contextUsed;
  const contextMax = current?.contextMax ?? snapshot.contextMax;
  const percent = contextPercent(contextUsed, contextMax);
  const progressPercent =
    todoTotal > 0 ? Math.min(100, Math.round((todoDone / todoTotal) * 100)) : 0;
  const lastTerminal = current?.lastTerminalAction ?? snapshot.lastTerminalAction;
  const lastTerminalAt = current?.lastTerminalAt ?? snapshot.lastTerminalAt;
  const isIdle = action === 'idle' || action === 'sleeping';
  const activeSessions = snapshot.sessions.filter((session) => isActiveAction(session.action));

  return (
    <div className="pet-panel">
      <div className="pet-panel-head">
        <span className={`pet-status-dot pet-status-${action}`} />
        <span className="pet-panel-title">大肥鱼</span>
        <span className="pet-panel-subtitle">
          {activeSessions.length > 0 ? `${activeSessions.length} 个进行中` : status}
        </span>
        <button type="button" className="pet-panel-close" onClick={onClose} aria-label="关闭面板">
          ×
        </button>
      </div>

      <div className="pet-panel-current">
        <div className="pet-session-name">{title}</div>
        <div className="pet-status-line">
          <span className="pet-status-text">{status}</span>
          {tool && tool !== status ? <span className="pet-tool-chip">{tool}</span> : null}
        </div>

        {todoTotal > 0 ? (
          <div className="pet-meter">
            <div className="pet-meter-head">
              <span>
                {progressLabel(progressKind)} {todoDone}/{todoTotal}
              </span>
              <span>{progressPercent}%</span>
            </div>
            <div className="pet-meter-track">
              <div className="pet-meter-fill" style={{ width: `${progressPercent}%` }} />
            </div>
            {todoActive ? <div className="pet-todo-active">{todoActive}</div> : null}
          </div>
        ) : null}

        {percent !== null ? (
          <div className="pet-meter">
            <div className="pet-meter-head">
              <span>上下文 {percent}%</span>
              <span>
                {formatTokens(contextUsed ?? 0)} / {formatTokens(contextMax ?? 0)}
              </span>
            </div>
            <div className="pet-meter-track">
              <div
                className={`pet-meter-fill ${percent >= 85 ? 'pet-meter-warn' : ''}`}
                style={{ width: `${percent}%` }}
              />
            </div>
          </div>
        ) : null}

        {isIdle && lastTerminal ? (
          <div className="pet-last">
            最近：{terminalLabel(lastTerminal)} · {relativeTime(lastTerminalAt)}
          </div>
        ) : null}

        <div className="pet-bond">
          陪伴 {snapshot.bondDays} 天 · 摸头 {snapshot.patCount} 次
        </div>
      </div>

      {snapshot.sessions.length > 1 ? (
        <div className="pet-panel-sessions">
          <div className="pet-panel-section-title">活跃会话</div>
          {snapshot.sessions.map((session) => (
            <button
              type="button"
              key={session.sessionId}
              className="pet-session-row"
              onClick={() => onOpenSession(session.sessionId)}
            >
              <span className={`pet-status-dot pet-status-${session.action}`} />
              <span className="pet-session-row-title">
                {sessionLabel(session.sessionTitle, session.sessionId)}
              </span>
              <span className="pet-session-row-status">
                {statusLabel(session.action, session.detail, session.toolName)}
              </span>
            </button>
          ))}
        </div>
      ) : null}

      <div className="pet-panel-actions">
        <button
          type="button"
          className="pet-action-primary"
          disabled={!current?.sessionId}
          onClick={() => {
            const sessionId = current?.sessionId;
            if (sessionId) onOpenSession(sessionId);
          }}
        >
          回到会话
        </button>
        <button type="button" className="pet-action" onClick={onOpenSettings}>
          设置
        </button>
      </div>
      {config.showSessionTitle ? null : (
        <div className="pet-panel-hint">会话名仅在面板显示；气泡保持简洁</div>
      )}
    </div>
  );
}
