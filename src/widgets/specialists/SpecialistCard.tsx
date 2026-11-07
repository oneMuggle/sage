import { MoreHorizontal } from 'lucide-react';

import type { AgentProfile } from '../../shared/api';
import { Button } from '../../shared/ui/Button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../../shared/ui/DropdownMenu/DropdownMenu';

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
  /** M2-Task 2: 打开「知识」编辑器（绑定知识源）。 */
  onKnowledge: (agent: AgentProfile) => void;
  onExport: (agent: AgentProfile) => void;
  /** M4-T3: 打开版本历史（列表 / diff / 回滚）。 */
  onVersions: (agent: AgentProfile) => void;
  /** M4-T4: 打开黄金任务集评测。 */
  onEval: (agent: AgentProfile) => void;
  /** M3-Task 7 资产中心: 打开专家私有记忆 / 知识绑定 / 技能总览。 */
  onAssets: (agent: AgentProfile) => void;
  /** 导出进行中（按钮禁用，避免重复弹保存框）。 */
  exporting?: boolean;
}

function readUiString(ui: Record<string, unknown> | undefined, key: string): string {
  const value = ui?.[key];
  return typeof value === 'string' ? value.trim() : '';
}

/**
 * 基于 avatar 首字符生成卡片色调（HSL 渐变）。
 * 浅色模式：高饱和度 + 高亮度；深色模式通过 CSS 变量或外层 dark: 类降低。
 */
function generateCardTone(avatar: string): React.CSSProperties {
  const hue = (avatar.charCodeAt(0) * 37) % 360;
  return {
    background: `linear-gradient(135deg, hsl(${hue} 80% 95%), hsl(${hue + 30} 80% 90%))`,
  };
}

/**
 * M1-E 专家卡片（P0 UX 优化）：主操作放大 + 色调 + 禁用态增强。
 *
 * 结构：
 * - 头部：头像 + 名称 + 徽标（版本/角色/禁用）
 * - 正文：标语 + 权限模式
 * - 主操作：「💬 开始试聊」大按钮（全宽）
 * - 次操作：编辑/知识/资产 图标按钮 + 更多菜单（版本/评测/导出）
 */
export function SpecialistCard({
  agent,
  onChat,
  onEdit,
  onKnowledge,
  onExport,
  onVersions,
  onEval,
  onAssets,
  exporting = false,
}: SpecialistCardProps) {
  const avatar = readUiString(agent.persona_ui, 'avatar') || DEFAULT_AVATAR;
  const tagline = readUiString(agent.persona_ui, 'tagline') || agent.description;
  const roleLabel = ROLE_LABELS[agent.role] ?? agent.role;
  const sourceLabel = SOURCE_LABELS[agent.source ?? 'user'] ?? agent.source ?? '';
  const version = agent.version ?? 1;
  const disabled = !agent.enabled;

  const cardStyle = disabled
    ? { filter: 'grayscale(100%)', opacity: 0.7 }
    : generateCardTone(avatar);

  return (
    <div
      data-testid={`specialist-card-${agent.id}`}
      className="flex flex-col rounded-xl border border-border p-4 transition-all hover:shadow-md"
      style={cardStyle}
    >
      {/* 头部 */}
      <div className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-white/60 text-2xl dark:bg-black/20"
        >
          {avatar}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="truncate font-medium">{agent.name}</h3>
            <span className="shrink-0 rounded-full bg-white/70 px-2 py-0.5 text-ui-xs text-text-secondary dark:bg-black/30">
              v{version}
            </span>
            {disabled && (
              <span
                className="shrink-0 rounded-full bg-warning/20 px-2 py-0.5 text-ui-xs text-warning"
                title="请先在智能体页启用"
              >
                ⚠️ 已禁用
              </span>
            )}
          </div>
          <p className="mt-1 line-clamp-2 text-sm text-muted">{tagline || '尚未填写标语'}</p>
          <p className="mt-1 text-ui-xs text-faint">
            {sourceLabel} · {roleLabel}
            {agent.permission_mode ? ` · ${PERMISSION_MODE_LABELS[agent.permission_mode]}` : ''}
            {agent.skills && agent.skills.length > 0 ? ` · ${agent.skills.length} 项技能` : ''}
          </p>
        </div>
      </div>

      {/* 主操作 */}
      <div className="mt-4">
        <Button
          variant="primary"
          size="lg"
          className="w-full"
          disabled={disabled}
          onClick={() => onChat(agent)}
          title={disabled ? '请先在智能体页启用' : undefined}
        >
          💬 开始试聊
        </Button>
      </div>

      {/* 次操作 */}
      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          onClick={() => onEdit(agent)}
          className="flex-1 rounded-radius-md border border-border px-3 py-1.5 text-sm hover:bg-bg-hover"
          title="编辑专家"
        >
          编辑
        </button>
        <button
          type="button"
          onClick={() => onKnowledge(agent)}
          className="flex-1 rounded-radius-md border border-border px-3 py-1.5 text-sm hover:bg-bg-hover"
          title="管理知识绑定"
        >
          知识
        </button>
        <button
          type="button"
          onClick={() => onAssets(agent)}
          className="flex-1 rounded-radius-md border border-border px-3 py-1.5 text-sm hover:bg-bg-hover"
          title="查看资产（记忆/知识/技能）"
        >
          资产
        </button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" title="更多操作">
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => onVersions(agent)}>版本历史</DropdownMenuItem>
            <DropdownMenuItem onClick={() => onEval(agent)}>黄金任务评测</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => onExport(agent)} disabled={exporting}>
              {exporting ? '导出中…' : '导出专家包'}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
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
