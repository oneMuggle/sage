import { UserRound } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { agentsApi } from '../../shared/api/agentsApi';
import { sessionApi } from '../../shared/api/sessionApi';
import { useI18n } from '../../shared/lib/i18n';
import { useStore } from '../../shared/lib/store';

/** 主助手（默认助手）的 agent id —— 后端 sessions.specialist_id 的缺省值。 */
const PRIMARY_AGENT_ID = 'primary';

interface SpecialistOption {
  id: string;
  name: string;
}

/**
 * M0 (2026-11-03): 聊天头部「专家」选择器 —— 切换当前会话绑定的专家。
 *
 * 绑定只影响本会话后续轮次的 persona / 工具白名单 / 模型 / 记忆策略，
 * 不触碰历史消息。绑定的专家被禁用或删除时后端回落主助手，选择器
 * 随之展示实际生效值（主助手）。
 */
export function SessionSpecialistPicker() {
  const { t } = useI18n();
  const sessionId = useStore((s) => s.currentSessionId);
  const boundSpecialistId = useStore(
    (s) =>
      s.sessions.find((session) => session.id === s.currentSessionId)?.specialist_id ??
      PRIMARY_AGENT_ID,
  );
  const [agents, setAgents] = useState<SpecialistOption[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    agentsApi
      .list()
      .then((list) => {
        if (cancelled) return;
        setAgents(
          list
            .filter((agent) => agent.enabled)
            .map((agent) => ({ id: agent.id, name: agent.name })),
        );
      })
      .catch(() => {
        // 加载失败时只展示主助手，聊天本身不受影响。
        if (!cancelled) setAgents([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const options = useMemo<SpecialistOption[]>(() => {
    const rest = agents
      .filter((agent) => agent.id !== PRIMARY_AGENT_ID)
      // 固定 collation：默认 locale 在 CI（en-US）与本地（zh_CN）间不一致，
      // 中文名会落到码点序（写 < 分）。zh-Hans 下中文按拼音、拉丁名按字母序。
      .sort((a, b) => a.name.localeCompare(b.name, 'zh-Hans'));
    const primary = agents.find((agent) => agent.id === PRIMARY_AGENT_ID);
    return [primary ?? { id: PRIMARY_AGENT_ID, name: t('chat.specialist.primary') }, ...rest];
  }, [agents, t]);

  // 绑定值已不可用（专家被禁用/删除）时展示后端实际回落的主助手。
  const currentValue = options.some((option) => option.id === boundSpecialistId)
    ? boundSpecialistId
    : PRIMARY_AGENT_ID;

  const handleChange = async (next: string) => {
    if (!sessionId || saving || next === currentValue) return;
    setSaving(true);
    try {
      await sessionApi.setSpecialist(sessionId, next);
      useStore.getState().updateSession(sessionId, { specialist_id: next });
      const name = options.find((option) => option.id === next)?.name ?? next;
      toast.success(t('chat.specialist.switched').replace('{name}', name));
    } catch (error: unknown) {
      toast.error(error instanceof Error ? error.message : t('chat.specialist.switchFailed'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex items-center gap-1 text-ui-xs" title={t('chat.specialist.hint')}>
      <UserRound className="w-3.5 h-3.5 text-text-secondary shrink-0" aria-hidden="true" />
      <label htmlFor="chat-specialist-picker" className="sr-only">
        {t('chat.specialist.label')}
      </label>
      <select
        id="chat-specialist-picker"
        data-testid="session-specialist-picker"
        aria-label={t('chat.specialist.label')}
        value={currentValue}
        disabled={!sessionId || saving}
        onChange={(e) => void handleChange(e.target.value)}
        className="max-w-40 text-xs text-text-secondary bg-surface border border-border rounded-radius-sm px-1.5 py-1 outline-none hover:bg-bg-hover focus:border-primary disabled:opacity-50 truncate"
      >
        {options.map((option) => (
          <option key={option.id} value={option.id}>
            {option.name}
          </option>
        ))}
      </select>
    </div>
  );
}
