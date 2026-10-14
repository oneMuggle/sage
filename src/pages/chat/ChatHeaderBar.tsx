import type { Dispatch, SetStateAction } from 'react';
import { useNavigate } from 'react-router-dom';

import { useI18n } from '../../shared/lib/i18n';
import { ProjectBadge } from '../../widgets/chat/ProjectBadge';
import { RightPanelToggle } from '../../widgets/chat/RightPanelToggle';
import { SessionModelPicker } from '../../widgets/chat/SessionModelPicker';
import { SessionUsageBadge } from '../../widgets/chat/SessionUsageBadge';
import { WorkspaceBranchPicker } from '../../widgets/chat/WorkspaceBranchPicker';

import { SessionSessionMenu } from './SessionSessionMenu';
import { SessionSettingsMenu } from './SessionSettingsMenu';

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
  const navigate = useNavigate();

  return (
    <div
      data-testid="chat-header-bar"
      data-compact={rightPanelOpen ? 'true' : 'false'}
      className="min-h-12 py-1.5 flex flex-wrap items-center justify-between gap-x-2.5 gap-y-1.5 px-4 border-b border-border bg-surface flex-shrink-0"
    >
      <div className="flex items-center gap-2 min-w-0 flex-wrap">
        <h2 className="text-ui-sm font-semibold text-text shrink-0">对话</h2>
        <ProjectBadge workspacePath={workspacePath} onOpenWorkbench={() => navigate('/projects')} />
        <WorkspaceBranchPicker sessionId={currentSessionId} />
        <SessionUsageBadge sessionId={currentSessionId} />
      </div>
      <div className="flex items-center gap-1.5 flex-wrap" data-testid="chat-header-controls">
        <SessionModelPicker sessionId={currentSessionId} placement="bottom" />
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
        {/* UI 优化 2026-10-14: 会话级设置收纳进齿轮浮层 */}
        <SessionSettingsMenu sessionId={currentSessionId} />
        {/* UI 优化 2026-10-14: 新对话/新话题/临时聊天合并进 + 下拉菜单 */}
        <SessionSessionMenu
          isLoading={isLoading}
          hasConfig={hasConfig}
          currentSessionId={currentSessionId}
          onNewTopic={onNewTopic}
          onNewSession={onNewSession}
          isTempChat={isTempChat}
          setTempChatSessions={setTempChatSessions}
        />
        <RightPanelToggle
          open={rightPanelOpen}
          onClick={onToggleRightPanel}
          unseenCount={unseenArtifactCount}
        />
      </div>
    </div>
  );
}
