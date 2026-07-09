import {
  HelpCircle,
  Trash2,
  Search,
  FileText,
  Languages,
  Minimize2,
  BookOpen,
  type LucideIcon,
} from 'lucide-react';

/** Slash 命令定义 */
export interface SlashCommand {
  /** 命令名（不含 /） */
  name: string;
  /** 显示标签 */
  label: string;
  /** 描述 */
  description: string;
  /** 图标 */
  icon: LucideIcon;
  /**
   * 执行模式:
   * - 'prompt': 将命令转为提示词发送给 LLM
   * - 'clear': 清空当前对话
   * - 'help': 显示帮助信息
   * - 'skill': 作为 SKILL.md skill 执行,返回内容作为用户消息发送
   */
  mode: 'prompt' | 'clear' | 'help' | 'skill';
  /** 'skill' 模式下需要执行的 SKILL.md 名称（不含 /）。 */
  skillName?: string;
}

/** 所有可用的 slash 命令 */
export const slashCommands: SlashCommand[] = [
  {
    name: 'help',
    label: '帮助',
    description: '显示可用命令列表',
    icon: HelpCircle,
    mode: 'help',
  },
  {
    name: 'clear',
    label: '清空对话',
    description: '清空当前会话的所有消息',
    icon: Trash2,
    mode: 'clear',
  },
  {
    name: 'search',
    label: '搜索',
    description: '使用 /search 后输入搜索内容',
    icon: Search,
    mode: 'prompt',
  },
  {
    name: 'summarize',
    label: '总结',
    description: '总结当前对话内容',
    icon: FileText,
    mode: 'prompt',
  },
  {
    name: 'translate',
    label: '翻译',
    description: '翻译上一条消息',
    icon: Languages,
    mode: 'prompt',
  },
  {
    name: 'compact',
    label: '压缩上下文',
    description: '压缩当前对话上下文',
    icon: Minimize2,
    mode: 'prompt',
  },
];

/** 根据输入前缀过滤命令 */
export function filterCommands(query: string): SlashCommand[] {
  const lower = query.toLowerCase();
  return slashCommands.filter(
    (cmd) => cmd.name.toLowerCase().includes(lower) || cmd.label.toLowerCase().includes(lower),
  );
}

/**
 * Merge static slash commands with dynamically-loaded SKILL.md slash commands.
/** A SKILL.md-derived slash command with its real description. */
export interface DynamicSlashSkill {
  /** Command name as returned by backend (e.g. "/aihot" or "aihot"). */
  commandName: string;
  /** Real description from SKILL.md frontmatter (passed through to menu). */
  description: string;
}

/**
 * Merge static slash commands with dynamically-loaded SKILL.md slash commands.
 * SKILL.md commands take priority on name collision (dynamic wins because the
 * user has explicitly loaded that skill from disk). The `dynamic` entries come
 * from `GET /api/v1/skills` filtered by `dispatch.user_invocable === true` and
 * may include a leading "/" (e.g. "/aihot") which we strip before using.
 *
 * @param dynamic - Skill metadata from `skillsApi.list()`, with real description.
 *                  May be empty. Leading slashes are tolerated.
 * @returns Combined list with SKILL.md commands first, followed by static
 *          commands that did not collide.
 */
export function mergeSlashCommands(dynamic: DynamicSlashSkill[]): SlashCommand[] {
  const seen = new Set<string>();
  const result: SlashCommand[] = [];

  // Dynamic SKILL.md commands first (higher priority on name collision)
  for (const entry of dynamic) {
    const name = entry.commandName.replace(/^\/+/, ''); // strip all leading /
    if (!name) continue;
    if (seen.has(name)) continue;
    seen.add(name);
    // Truncate description to keep the menu compact (~80 chars)
    const shortDesc =
      entry.description.length > 80 ? `${entry.description.slice(0, 77)}…` : entry.description;
    result.push({
      name,
      label: entry.commandName.startsWith('/') ? entry.commandName : `/${name}`,
      description: shortDesc,
      icon: BookOpen,
      mode: 'skill',
      skillName: name,
    });
  }

  // Static commands (skip those already taken by a dynamic command)
  for (const cmd of slashCommands) {
    if (seen.has(cmd.name)) continue;
    seen.add(cmd.name);
    result.push(cmd);
  }

  return result;
}

/** 根据命令名获取命令 */
export function getCommand(name: string): SlashCommand | undefined {
  return slashCommands.find((cmd) => cmd.name === name);
}

/** 将命令转为发送给 LLM 的提示词 */
export function commandToPrompt(cmd: SlashCommand, args: string): string {
  switch (cmd.name) {
    case 'search':
      return `请在知识库中搜索以下内容并总结结果：${args}`;
    case 'summarize':
      return '请总结我们当前对话的主要内容，包括关键决策和结论。';
    case 'translate':
      return '请将上一条消息翻译成英文（如果原文是英文则翻译成中文）。';
    case 'compact':
      return '请压缩当前对话的上下文，保留关键信息，移除冗余细节。';
    default:
      return args || `/${cmd.name}`;
  }
}
