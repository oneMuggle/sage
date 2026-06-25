import { MessageSquare, Brain, BookOpen, Settings, Bot, Sparkles } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

/** 导航命令 */
export interface NavCommand {
  type: 'nav';
  path: string;
  label: string;
  icon: LucideIcon;
}

/** 操作命令 */
export interface ActionCommand {
  type: 'action';
  id: string;
  label: string;
  description: string;
  icon: LucideIcon;
}

export type CommandItem = NavCommand | ActionCommand;

/** 导航命令配置 */
export const navCommands: NavCommand[] = [
  { type: 'nav', path: '/chat', label: '对话', icon: MessageSquare },
  { type: 'nav', path: '/memory', label: '记忆', icon: Brain },
  { type: 'nav', path: '/knowledge', label: '知识库', icon: BookOpen },
  { type: 'nav', path: '/agents', label: '智能体', icon: Bot },
  { type: 'nav', path: '/skills', label: '技能', icon: Sparkles },
  { type: 'nav', path: '/settings', label: '设置', icon: Settings },
];

/** 操作命令配置 */
export const actionCommands: ActionCommand[] = [
  {
    type: 'action',
    id: 'new-chat',
    label: '新建对话',
    description: '创建一个新的对话会话',
    icon: MessageSquare,
  },
  {
    type: 'action',
    id: 'toggle-theme',
    label: '切换主题',
    description: '在亮色/暗色之间切换',
    icon: Sparkles,
  },
];
