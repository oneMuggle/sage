import type { AgentProfile } from '../../shared/api';

/** agent.role → 中文标签（与 /agents 的 AgentCard 保持同一词表 + specialist）。 */
const ROLE_LABELS: Record<string, string> = {
  coordinator: '协调器',
  researcher: '研究员',
  coder: '工程师',
  memory_manager: '记忆管理',
  writer: '文档写作',
  'slide-deck-creator': '演示文稿',
  reviewer: '审校',
  specialist: '专家',
};

const SOURCE_LABELS: Record<string, string> = {
  builtin: '内置',
  user: '用户创建',
  imported: '导入',
};

const DEFAULT_AVATAR = '🤖';

interface SpecialistCardProps {
  agent: AgentProfile;
  onChat: (agent: AgentProfile) => void;
  onEdit: (agent: AgentProfile) => void;
  onExport: (agent: AgentProfile) => void;
  /** 导出进行中（按钮禁用，避免重复弹保存框）。 */
  exporting?: boolean;
}

function readUiString(ui: Record<string, unknown> | undefined, key: string): string {
  const value = ui?.[key];
  return typeof value === 'string' ? value.trim() : '';
}

/**
 * M1-E 专家卡片：头像（persona_ui.avatar emoji）+ 名称 + 标语 + 卡片级动作。
 *
 * 与 /agents 的 AgentCard 区别：本卡片面向「挑选专家去工作」，
 * 因此突出试聊入口与人设信息（头像/tagline/版本），不带启用开关与选中态。
 */
export function SpecialistCard({
  agent,
  onChat,
  onEdit,
  onExport,
  exporting = false,
}: SpecialistCardProps) {
  const avatar = readUiString(agent.persona_ui, 'avatar') || DEFAULT_AVATAR;
  const tagline = readUiString(agent.persona_ui, 'tagline') || agent.description;
  const roleLabel = ROLE_LABELS[agent.role] ?? agent.role;
  const sourceLabel = SOURCE_LABELS[agent.source ?? 'user'] ?? agent.source ?? '';
  const version = agent.version ?? 1;
  const disabled = !agent.enabled;

  return (
    <div
      data-testid={`specialist-card-${agent.id}`}
      className={`flex flex-col rounded-xl border border-border bg-surface p-4 transition-colors hover:border-border-hover ${
        disabled ? 'opacity-60' : ''
      }`}
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-bg-subtle text-2xl"
        >
          {avatar}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="truncate font-medium">{agent.name}</h3>
            <span className="shrink-0 rounded-full bg-bg-subtle px-2 py-0.5 text-ui-xs text-text-secondary">
              {roleLabel}
            </span>
            <span className="shrink-0 rounded-full bg-bg-subtle px-2 py-0.5 text-ui-xs text-muted">
              v{version}
            </span>
            {disabled && (
              <span className="shrink-0 rounded-full bg-warning/10 px-2 py-0.5 text-ui-xs text-warning">
                已禁用
              </span>
            )}
          </div>
          <p className="mt-1 line-clamp-2 text-sm text-muted">{tagline || '尚未填写标语'}</p>
          <p className="mt-1 text-ui-xs text-faint">
            {sourceLabel}
            {agent.permission_mode ? ` · ${PERMISSION_MODE_LABELS[agent.permission_mode]}` : ''}
          </p>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-2">
        <button
          type="button"
          disabled={disabled}
          onClick={() => onChat(agent)}
          title={disabled ? '专家已禁用，请先在智能体页启用' : undefined}
          className="rounded-radius-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
        >
          试聊
        </button>
        <button
          type="button"
          onClick={() => onEdit(agent)}
          className="rounded-radius-md border border-border px-3 py-1.5 text-sm hover:bg-bg-hover"
        >
          编辑
        </button>
        <button
          type="button"
          onClick={() => onExport(agent)}
          disabled={exporting}
          className="rounded-radius-md border border-border px-3 py-1.5 text-sm hover:bg-bg-hover disabled:opacity-50"
        >
          {exporting ? '导出中…' : '导出'}
        </button>
      </div>
    </div>
  );
}

/** 权限模式标签（与后端 _VALID_PERMISSION_MODES 对齐）。 */
export const PERMISSION_MODE_LABELS: Record<string, string> = {
  read_only: '只读',
  workspace_write: '工作区可写',
  prompt: '逐次确认',
  full_access: '完全访问',
};
