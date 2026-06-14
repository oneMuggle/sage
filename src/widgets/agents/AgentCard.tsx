import type { AgentProfile } from '../../shared/api/api';

const ROLE_LABELS: Record<string, string> = {
  coordinator: '协调器',
  researcher: '研究员',
  coder: '工程师',
  memory_manager: '记忆管理',
};

const ROLE_COLORS: Record<string, string> = {
  coordinator: 'bg-role-blue text-role-blue-text',
  researcher: 'bg-role-green text-role-green-text',
  coder: 'bg-role-purple text-role-purple-text',
  memory_manager: 'bg-role-orange text-role-orange-text',
};

interface AgentCardProps {
  agent: AgentProfile;
  isSelected: boolean;
  onSelect: () => void;
  onToggle: (id: string, enabled: boolean) => void;
}

export function AgentCard({ agent, isSelected, onSelect, onToggle }: AgentCardProps) {
  const roleColor = ROLE_COLORS[agent.role] || 'bg-bg-subtle text-text-secondary';
  const roleLabel = ROLE_LABELS[agent.role] || agent.role;

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onSelect();
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`选择智能体 ${agent.name}`}
      aria-pressed={isSelected}
      onClick={onSelect}
      onKeyDown={handleKeyDown}
      className={`p-4 rounded-lg border cursor-pointer transition-all focus:outline-none focus:ring-2 focus:ring-primary ${
        isSelected ? 'border-primary bg-primary/10' : 'border-border hover:border-border-hover'
      } ${!agent.enabled ? 'opacity-50' : ''}`}
    >
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-medium">{agent.name}</h3>
        <span className={`px-2 py-0.5 text-xs rounded-full ${roleColor}`}>{roleLabel}</span>
      </div>

      <p className="text-sm text-muted mb-3 line-clamp-2">{agent.description}</p>

      <div className="flex items-center justify-between">
        <span className="text-xs text-muted">模型: {agent.model_config.model}</span>
        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={agent.enabled}
            onChange={(e) => {
              e.stopPropagation();
              onToggle(agent.id, e.target.checked);
            }}
            className="rounded"
          />
          启用
        </label>
      </div>
    </div>
  );
}
