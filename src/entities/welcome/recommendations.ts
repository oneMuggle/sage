import {
  Code2,
  Lightbulb,
  Search,
  FileText,
  FolderSearch,
  FileSpreadsheet,
  Presentation,
  type LucideIcon,
} from 'lucide-react';

export type TaskScenario = 'report' | 'organize' | 'data' | 'slides' | 'coding';
export interface AssistantRecommendation {
  id: string;
  title: string;
  prompt: string;
  icon: string;
  gradient: string;
  labels?: { zh: { title: string; desc: string }; en: { title: string; desc: string } };
}
export const lucideIconMap: Record<string, LucideIcon> = {
  Code2,
  Search,
  Lightbulb,
  FileText,
  FolderSearch,
  FileSpreadsheet,
  Presentation,
};
export const defaultRecommendations: AssistantRecommendation[] = [
  {
    id: 'report',
    title: 'report',
    prompt: '根据指定资料生成一份可交付的报告',
    icon: 'FileText',
    gradient: 'bg-ui-surface',
    labels: {
      zh: { title: '写报告', desc: '明确受众、资料、格式和检查要求' },
      en: {
        title: 'Write a report',
        desc: 'Set audience, sources, format and review requirements',
      },
    },
  },
  {
    id: 'organize',
    title: 'organize',
    prompt: '整理指定资料并给出可追溯的摘要',
    icon: 'FolderSearch',
    gradient: 'bg-ui-surface',
    labels: {
      zh: { title: '整理资料', desc: '按来源梳理要点，标明缺失与未核验项' },
      en: { title: 'Organize sources', desc: 'Trace summaries to sources and identify unknowns' },
    },
  },
  {
    id: 'data',
    title: 'data',
    prompt: '分析指定表格并交付检查过的数据结果',
    icon: 'FileSpreadsheet',
    gradient: 'bg-ui-surface',
    labels: {
      zh: { title: '分析表格', desc: '明确计算口径、数据范围和交付形式' },
      en: { title: 'Analyze a spreadsheet', desc: 'Define scope, calculations and deliverables' },
    },
  },
  {
    id: 'slides',
    title: 'slides',
    prompt: '根据指定资料制作可编辑的演示文稿',
    icon: 'Presentation',
    gradient: 'bg-ui-surface',
    labels: {
      zh: { title: '制作演示', desc: '先确认大纲，再生成和验收演示文稿' },
      en: { title: 'Create a presentation', desc: 'Agree on an outline, then generate and review' },
    },
  },
  {
    id: 'coding',
    title: 'coding',
    prompt: '在绑定的工作目录内修改代码并通过检查',
    icon: 'Code2',
    gradient: 'bg-ui-surface',
    labels: {
      zh: { title: '写代码 / 改代码', desc: '在绑定目录内修改，遵守审批与检查' },
      en: {
        title: 'Write or change code',
        desc: 'Edit inside the bound workspace with approvals and checks',
      },
    },
  },
];
