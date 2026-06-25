import {
  HelpCircle,
  Trash2,
  Search,
  FileText,
  Languages,
  Minimize2,
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
   */
  mode: 'prompt' | 'clear' | 'help';
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
    (cmd) =>
      cmd.name.toLowerCase().includes(lower) ||
      cmd.label.toLowerCase().includes(lower),
  );
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
