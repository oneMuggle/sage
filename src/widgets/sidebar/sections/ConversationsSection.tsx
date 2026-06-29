import { MessageSquare, Plus } from 'lucide-react';

import type { Session } from '../../../shared/lib/store';
import { useI18n } from '../../../shared/lib/i18n';
import { SortableSessionList } from '../../session/SortableSessionList';
import { SiderSection } from '../SiderSection';

interface ConversationsSectionProps {
  sessions: Session[];
  order: string[];
  currentSessionId: string | null;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onSelect: (sessionId: string) => void;
  onDelete: (sessionId: string) => void;
  onNewSession: () => void;
  onOrderChange: (next: string[]) => void;
}

export function ConversationsSection({
  sessions,
  order,
  currentSessionId,
  collapsed,
  onToggleCollapsed,
  onSelect,
  onDelete,
  onNewSession,
  onOrderChange,
}: ConversationsSectionProps) {
  const { t } = useI18n();
  return (
    <SiderSection
      sectionKey="conversations"
      label={t('sider.section.conversations')}
      icon={MessageSquare}
      collapsed={collapsed}
      onToggleCollapsed={onToggleCollapsed}
      maxHeight="50vh"
      trailing={
        <button
          type="button"
          onClick={onNewSession}
          aria-label={t('sidebar.new_chat')}
          title={t('sidebar.new_chat')}
          className="inline-flex items-center justify-center w-5 h-5 rounded text-muted hover:text-text hover:bg-bg-hover"
        >
          <Plus className="w-3.5 h-3.5" />
        </button>
      }
      render={() => (
        <SortableSessionList
          sessions={sessions}
          order={order}
          currentSessionId={currentSessionId}
          onSelect={onSelect}
          onDelete={onDelete}
          onOrderChange={onOrderChange}
        />
      )}
    />
  );
}
