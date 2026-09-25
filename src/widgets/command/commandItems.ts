import {
  MessageSquare,
  Brain,
  BookOpen,
  Settings,
  Bot,
  FolderPlus,
  Sparkles,
  Network,
  FileSpreadsheet,
  Swords,
  ListChecks,
  Clock,
  Boxes,
  HelpCircle,
  PanelRight,
} from 'lucide-react';
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
  // U10: sidebar 隐藏高级入口期间，命令面板作为发现路径（首次使用后解锁并固定到 sidebar）。
  { type: 'nav', path: '/orchestration', label: '编排', icon: Network },
  { type: 'nav', path: '/arena', label: 'Arena 控制台', icon: Swords },
  { type: 'nav', path: '/office', label: 'Office', icon: FileSpreadsheet },
  { type: 'nav', path: '/todos', label: '待办事项', icon: ListChecks },
  { type: 'nav', path: '/scheduled', label: '定时任务', icon: Clock },
  { type: 'nav', path: '/model-catalog', label: '模型目录', icon: Boxes },
  { type: 'nav', path: '/settings', label: '设置', icon: Settings },
  { type: 'nav', path: '/help', label: '帮助', icon: HelpCircle },
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
  // 项目模块 P2 (2026-09-13): 命令面板登记项目入口（与侧边栏 + 同一链路）
  {
    type: 'action',
    id: 'add-project',
    label: '添加项目',
    description: '选择工作目录并登记为项目',
    icon: FolderPlus,
  },
  // Phase 1 (2026-09-25): ZCode 启发优化——快速切换右侧面板（进度/产物/变更）
  {
    type: 'action',
    id: 'toggle-right-panel',
    label: '切换右侧面板',
    description: '打开或关闭右侧面板（进度/产物/变更）',
    icon: PanelRight,
  },
];
