import { Code2, Lightbulb, Search, type LucideIcon } from 'lucide-react';

export interface AssistantRecommendation {
  id: string;
  title: string;
  prompt: string;
  icon: string; // lucide-react icon name
  gradient: string; // tailwind gradient class
}

export const lucideIconMap: Record<string, LucideIcon> = {
  Code2,
  Search,
  Lightbulb,
};

export const defaultRecommendations: AssistantRecommendation[] = [
  {
    id: 'code',
    title: 'write-code',
    prompt: '帮我写代码：',
    icon: 'Code2',
    gradient: 'bg-gradient-to-br from-blue-500 to-indigo-600',
  },
  {
    id: 'search',
    title: 'search-info',
    prompt: '帮我搜索：',
    icon: 'Search',
    gradient: 'bg-gradient-to-br from-emerald-500 to-teal-600',
  },
  {
    id: 'idea',
    title: 'brainstorm',
    prompt: '帮我脑暴：',
    icon: 'Lightbulb',
    gradient: 'bg-gradient-to-br from-amber-500 to-orange-600',
  },
];
