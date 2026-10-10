import { MessageSquarePlus, RotateCcw } from 'lucide-react';
import type { Dispatch, SetStateAction } from 'react';

import { useI18n } from '../../shared/lib/i18n';
import { ContextMeter } from '../../widgets/chat/ContextMeter';
import { PermissionModeSwitch } from '../../widgets/chat/PermissionModeSwitch';
import { ProjectBadge } from '../../widgets/chat/ProjectBadge';
import { RightPanelToggle } from '../../widgets/chat/RightPanelToggle';
import { SessionModelPicker } from '../../widgets/chat/SessionModelPicker';
import { SessionUsageBadge } from '../../widgets/chat/SessionUsageBadge';
import { WorkspaceBranchPicker } from '../../widgets/chat/WorkspaceBranchPicker';

export interface ChatHeaderBarProps {
  workspacePath?: string | null;
  currentSessionId: string | null;
  orchMode: string;
  setOrchMode: (mode: string) => void;
  isLoading: boolean;
  hasConfig: boolean;
  onNewTopic: () => void;
  isTempChat: boolean;
  setTempChatSessions: Dispatch<SetStateAction<ReadonlySet<string>>>;
  onNewSession: () => void;
  rightPanelOpen: boolean;
  onToggleRightPanel: () => void;
  unseenArtifactCount: number;
}

export function ChatHeaderBar({
  workspacePath,
  currentSessionId,
  orchMode,
  setOrchMode,
  isLoading,
  hasConfig,
  onNewTopic,
  isTempChat,
  setTempChatSessions,
  onNewSession,
  rightPanelOpen,
  onToggleRightPanel,
  unseenArtifactCount,
}: ChatHeaderBarProps) {
  const { t } = useI18n();

  return (
    <div
      data-testid="chat-header-bar"
      data-compact={rightPanelOpen ? 'true' : 'false'}
      className="min-h-12 py-1.5 flex flex-wrap items-center justify-between gap-x-2.5 gap-y-1.5 px-4 border-b border-border bg-surface flex-shrink-0"
    >
      <div className="flex items-center gap-2 min-w-0 flex-wrap">
        <h2 className="text-ui-sm font-semibold text-text shrink-0">对话</h2>
        <ProjectBadge workspacePath={workspacePath} />
        <WorkspaceBranchPicker sessionId={currentSessionId} />
        <SessionUsageBadge sessionId={currentSessionId} />
      </div>
      <div className="flex items-center gap-1.5 flex-wrap" data-testid="chat-header-controls">
        <SessionModelPicker sessionId={currentSessionId} placement="bottom" />
        <PermissionModeSwitch sessionId={currentSessionId} placement="bottom" />
        <ContextMeter sessionId={currentSessionId} placement="bottom" />
        <div className="flex items-center gap-1 text-ui-xs">
          <label
            htmlFor="chat-header-orch-mode"
            className={
              rightPanelOpen
                ? 'text-text-tertiary hidden 2xl:inline'
                : 'text-text-tertiary hidden xl:inline'
            }
          >
            {t('chat.orchMode.label')}
          </label>
          <select
            id="chat-header-orch-mode"
            data-testid="orch-mode-select"
            aria-label={t('chat.orchMode.label')}
            value={orchMode}
            onChange={(e) => setOrchMode(e.target.value)}
            className={`px-2 py-1 text-ui-xs border rounded-radius-sm outline-none transition-colors ${
              orchMode !== 'auto'
                ? 'border-primary/40 bg-primary/10 text-primary font-medium'
                : 'border-border bg-surface text-text-secondary hover:bg-bg-hover'
            }`}
          >
            <option value="auto">{t('chat.orchMode.auto')}</option>
            <option value="force_multi">{t('chat.orchMode.forceMulti')}</option>
            <option value="template:research-write">
              {t('chat.orchMode.templateResearchWrite')}
            </option>
            <option value="template:gather-analyze-report">
              {t('chat.orchMode.templateGatherAnalyzeReport')}
            </option>
          </select>
        </div>
        <button
          type="button"
          data-testid="chat-new-topic"
          aria-label="+ 新话题"
          disabled={isLoading || !hasConfig}
          onClick={onNewTopic}
          title="新话题（重置上下文）"
          className="inline-flex items-center gap-1 px-2 py-1 text-ui-xs border border-border rounded-radius-sm text-text-secondary hover:bg-bg-hover hover:text-text disabled:opacity-50 transition-colors"
        >
          <RotateCcw className="w-3.5 h-3.5 shrink-0" />
          <span className={rightPanelOpen ? 'hidden 2xl:inline' : 'hidden sm:inline'}>
            + 新话题
          </span>
        </button>
        {currentSessionId && (
          <button
            type="button"
            onClick={() =>
              setTempChatSessions((prev) => {
                const next = new Set(prev);
                if (next.has(currentSessionId)) next.delete(currentSessionId);
                else next.add(currentSessionId);
                return next;
              })
            }
            aria-pressed={isTempChat}
            aria-label={t('chat.temp_chat')}
            title={isTempChat ? t('chat.temp_chat_on') : t('chat.temp_chat_off')}
            data-testid="temp-chat-toggle"
            className={`inline-flex items-center gap-1 px-2 py-1 text-ui-xs border rounded-radius-sm transition-colors ${
              isTempChat
                ? 'border-warning text-warning bg-warning/10'
                : 'border-border hover:bg-bg-hover'
            }`}
          >
            <span aria-hidden="true">🕶</span>
            <span className={rightPanelOpen ? 'hidden 2xl:inline' : 'hidden lg:inline'}>
              {t('chat.temp_chat')}
            </span>
          </button>
        )}
        <button
          type="button"
          data-testid="chat-new-session"
          aria-label="+ 新对话"
          title="新对话"
          onClick={onNewSession}
          className="inline-flex items-center gap-1 px-2 py-1 text-ui-xs border border-border rounded-radius-sm text-text-secondary hover:bg-bg-hover hover:text-text transition-colors"
        >
          <MessageSquarePlus className="w-3.5 h-3.5 shrink-0" />
          <span className={rightPanelOpen ? 'hidden 2xl:inline' : 'hidden xl:inline'}>
            + 新对话
          </span>
        </button>
        <RightPanelToggle
          open={rightPanelOpen}
          onClick={onToggleRightPanel}
          unseenCount={unseenArtifactCount}
        />
      </div>
    </div>
  );
}
