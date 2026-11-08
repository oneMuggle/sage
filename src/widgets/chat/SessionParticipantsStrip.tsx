/**
 * 会话参与者条（M2 私聊/群聊）。
 *
 * - DM 会话：渲染既有 SessionSpecialistPicker（单专家选择器）；
 * - Group 会话：显示参与者头像 + 名字 chips，可移除成员（host 保留）。
 */
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import { sessionApi } from '../../shared/api/sessionApi';
import type { ConversationParticipant } from '../../shared/api/types';
import { useStore } from '../../shared/lib/store';

import { SessionSpecialistPicker } from './SessionSpecialistPicker';

export function SessionParticipantsStrip() {
  const currentSessionId = useStore((state) => state.currentSessionId);
  const session = useStore((state) =>
    state.sessions.find((item) => item.id === state.currentSessionId),
  );
  const isGroup = session?.conversation_type === 'group';
  const [participants, setParticipants] = useState<ConversationParticipant[]>([]);

  const loadParticipants = useCallback(async () => {
    if (!currentSessionId || !isGroup) {
      setParticipants([]);
      return;
    }
    try {
      setParticipants(await sessionApi.listParticipants(currentSessionId));
    } catch {
      setParticipants([]);
    }
  }, [currentSessionId, isGroup]);

  useEffect(() => {
    void loadParticipants();
  }, [loadParticipants]);

  async function handleRemove(participant: ConversationParticipant) {
    if (!currentSessionId) return;
    if (participant.role === 'host') {
      toast.info('主持专家不能移除');
      return;
    }
    try {
      await sessionApi.removeParticipant(currentSessionId, participant.agent_id);
      await loadParticipants();
    } catch (err) {
      toast.error(`移除成员失败：${err instanceof Error ? err.message : String(err)}`);
    }
  }

  if (!isGroup) {
    return <SessionSpecialistPicker />;
  }

  return (
    <div
      className="flex items-center gap-1.5 min-w-0 flex-wrap"
      data-testid="session-participants-strip"
      title="群聊成员：在输入框输入 @专家名 指定发言"
    >
      <span className="text-ui-xs text-muted shrink-0">👥 {participants.length} 位专家</span>
      {participants.slice(0, 4).map((participant) => (
        <span
          key={participant.agent_id}
          className="inline-flex items-center gap-1 rounded-full border border-border bg-surface px-2 py-0.5 text-ui-xs text-text-secondary"
          data-testid={`participant-chip-${participant.agent_id}`}
        >
          <span aria-hidden="true">{participant.avatar}</span>
          <span className="max-w-24 truncate">{participant.name}</span>
          {participant.role === 'host' ? (
            <span className="text-ui-2xs text-primary">主持</span>
          ) : (
            <button
              type="button"
              aria-label={`移除 ${participant.name}`}
              onClick={() => void handleRemove(participant)}
              className="text-muted hover:text-error"
            >
              ×
            </button>
          )}
        </span>
      ))}
      {participants.length > 4 && (
        <span className="text-ui-xs text-muted">+{participants.length - 4}</span>
      )}
    </div>
  );
}
