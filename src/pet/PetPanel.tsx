/**
 * Pet status panel.
 *
 * Rendered inside the pet window; the main process grows the window while
 * this panel is open. Shows the pet's followed session, every session that
 * needs the user, and the remaining live sessions.
 */

import type {
  PetAttentionBridge,
  PetConfigBridge,
  PetSessionSummaryBridge,
  PetSnapshotBridge,
} from '../shared/types/electron-api';

import {
  contextPercent,
  formatTokens,
  isActiveAction,
  progressLabel,
  relativeTime,
  sessionLabel,
  statusLabel,
  taskAction,
  taskKindLabel,
  taskStatusLabel,
  toolLabel,
} from './engine/labels';

interface PetPanelProps {
  snapshot: PetSnapshotBridge;
  config: PetConfigBridge;
  onClose: () => void;
  onOpenSession: (sessionId: string) => void;
  onOpenSettings: () => void;
  onPinSession: (sessionId: string) => void;
  onCycleFocus: () => void;
}

const ZERO_ATTENTION: PetAttentionBridge = {
  needsYou: 0,
  failed: 0,
  running: 0,
  activeTasks: 0,
  total: 0,
  needsYouSessionIds: [],
};

const TERMINAL_LABELS = {
  done: { zh: '已完成', en: 'Completed' },
  error: { zh: '出错', en: 'Error' },
} as const;

function terminalLabel(action: 'done' | 'error' | null): string {
  if (!action) return '';
  const zh = typeof navigator !== 'undefined' && navigator.language.toLowerCase().startsWith('zh');
  return TERMINAL_LABELS[action][zh ? 'zh' : 'en'];
}

function SessionRow({
  session,
  pinned,
  onOpen,
  onPin,
}: {
  session: PetSessionSummaryBridge;
  pinned: boolean;
  onOpen: (sessionId: string) => void;
  onPin: (sessionId: string) => void;
}): JSX.Element {
  return (
    <div className="pet-session-item">
      <button
        type="button"
        className={`pet-session-row${isActiveAction(session.action) ? ' pet-session-row-active' : ''}`}
        data-testid={`pet-session-${session.sessionId}`}
        onClick={() => onOpen(session.sessionId)}
      >
        <span className={`pet-status-dot pet-status-${session.action}`} />
        <span className="pet-session-row-title">
          {sessionLabel(session.sessionTitle, session.sessionId)}
        </span>
        <span className="pet-session-row-status">
          {statusLabel(session.action, session.detail, session.toolName)}
        </span>
      </button>
      <button
        type="button"
        className={`pet-session-pin${pinned ? ' pet-session-pin-active' : ''}`}
        data-testid={`pet-pin-${session.sessionId}`}
        aria-label={pinned ? '取消钉住' : '钉住给这只宠物'}
        title={pinned ? '取消钉住' : '钉住给这只宠物'}
        onClick={() => onPin(session.sessionId)}
      >
        {pinned ? '★' : '☆'}
      </button>
    </div>
  );
}

export function PetPanel({
  snapshot,
  config,
  onClose,
  onOpenSession,
  onOpenSettings,
  onPinSession,
  onCycleFocus,
}: PetPanelProps): JSX.Element {
  const attention = snapshot.attention ?? ZERO_ATTENTION;
  const current =
    snapshot.sessions.find((session) => session.sessionId === snapshot.sessionId) ??
    snapshot.sessions[0] ??
    null;
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
  const primarySessionId =
    current?.sessionId ?? snapshot.sessionId ?? snapshot.tasks[0]?.sessionId ?? null;

  const needsYouRows = snapshot.sessions.filter((session) => session.action === 'waiting');
  const runningRows = snapshot.sessions.filter(
    (session) => session.action !== 'waiting' && isActiveAction(session.action),
  );
  const otherRows = snapshot.sessions.filter(
    (session) => session.action !== 'waiting' && !isActiveAction(session.action),
  );
  const runningTotal = attention.running + attention.activeTasks;
  const countParts = [
    runningTotal > 0 ? `${runningTotal} 个进行中` : '',
    attention.needsYou > 0 ? `${attention.needsYou} 个待处理` : '',
    attention.failed > 0 ? `${attention.failed} 个出错` : '',
  ].filter(Boolean);
  const headerText = countParts.length > 0 ? countParts.join(' · ') : status;
  // "已钉住" only when the pin is actually in effect: the pet window shows
  // the per-instance config, and a pinned mode without a live target falls
  // back to focus behaviour.
  const pinnedActive =
    config.followMode === 'pinned' &&
    Boolean(config.pinnedSessionId) &&
    config.pinnedSessionId === snapshot.sessionId;
  const followLabel = pinnedActive
    ? '已钉住'
    : config.followMode === 'urgent'
      ? '紧急优先'
      : '跟随焦点';
  const pinnedHere =
    config.followMode === 'pinned' &&
    Boolean(config.pinnedSessionId) &&
    config.pinnedSessionId === current?.sessionId;

  const pinnedFor = (sessionId: string): boolean =>
    config.followMode === 'pinned' && config.pinnedSessionId === sessionId;

  return (
    <div className="pet-panel">
      <div className="pet-panel-head">
        <span className={`pet-status-dot pet-status-${action}`} />
        <span className="pet-panel-title">大肥鱼</span>
        <span className="pet-panel-subtitle">{headerText}</span>
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

        <div className="pet-panel-follow" data-testid="pet-panel-follow">
          {followLabel}
          {current ? (
            <button
              type="button"
              className={`pet-session-pin${pinnedHere ? ' pet-session-pin-active' : ''}`}
              data-testid={`pet-pin-current-${current.sessionId}`}
              aria-label={pinnedHere ? '取消钉住' : '钉住给这只宠物'}
              title={pinnedHere ? '取消钉住' : '钉住给这只宠物'}
              onClick={() => onPinSession(current.sessionId)}
            >
              {pinnedHere ? '★' : '☆'}
            </button>
          ) : null}
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

      {snapshot.tasks.length > 0 ? (
        <div className="pet-panel-sessions">
          <div className="pet-panel-section-title">后台任务</div>
          {snapshot.tasks.slice(0, 5).map((task) => (
            <button
              type="button"
              key={task.id}
              className="pet-session-row"
              disabled={!task.sessionId}
              title={`${taskKindLabel(task.kind)} · ${task.title}`}
              onClick={() => {
                if (task.sessionId) onOpenSession(task.sessionId);
              }}
            >
              <span className={`pet-status-dot pet-status-${taskAction(task.status)}`} />
              <span className="pet-session-row-title">{task.title}</span>
              <span className="pet-session-row-status">
                {taskStatusLabel(task.status)}
                {task.percent !== null && task.percent !== undefined ? ` ${task.percent}%` : ''}
              </span>
            </button>
          ))}
        </div>
      ) : null}

      <div className="pet-panel-sessions">
        {needsYouRows.length > 0 ? (
          <section>
            <div className="pet-panel-section-title">需要处理</div>
            {needsYouRows.slice(0, 3).map((session) => (
              <SessionRow
                key={session.sessionId}
                session={session}
                pinned={pinnedFor(session.sessionId)}
                onOpen={onOpenSession}
                onPin={onPinSession}
              />
            ))}
          </section>
        ) : null}
        {runningRows.length > 0 ? (
          <section>
            <div className="pet-panel-section-title">正在运行</div>
            {runningRows.slice(0, 3).map((session) => (
              <SessionRow
                key={session.sessionId}
                session={session}
                pinned={pinnedFor(session.sessionId)}
                onOpen={onOpenSession}
                onPin={onPinSession}
              />
            ))}
          </section>
        ) : null}
        {otherRows.length > 0 ? (
          <section>
            <div className="pet-panel-section-title">其他会话</div>
            {otherRows.slice(0, 3).map((session) => (
              <SessionRow
                key={session.sessionId}
                session={session}
                pinned={pinnedFor(session.sessionId)}
                onOpen={onOpenSession}
                onPin={onPinSession}
              />
            ))}
          </section>
        ) : null}
      </div>

      <div className="pet-panel-actions">
        <button
          type="button"
          data-testid="pet-next-needs-you"
          disabled={attention.needsYouSessionIds.length === 0}
          onClick={onCycleFocus}
          className="pet-panel-action"
        >
          下一个待处理
        </button>
        <button
          type="button"
          className="pet-action-primary"
          disabled={!primarySessionId}
          onClick={() => {
            if (primarySessionId) onOpenSession(primarySessionId);
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
