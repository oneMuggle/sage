// Icon Sidebar - 左侧图标导航栏
import {
  FileText,
  Search,
  Network,
  CheckSquare,
  ClipboardList,
  FolderOpen,
  Globe,
  MessageCircle,
} from 'lucide-react';

import { useResearchStore } from '../../entities/wiki/research-store';
import { useReviewStore } from '../../entities/wiki/review-store';
import { useWikiStore } from '../../entities/wiki/store';
import type { WikiView } from '../../shared/types/wiki';

const NAV_ITEMS: { view: WikiView; icon: React.ElementType; label: string }[] = [
  { view: 'browser', icon: FileText, label: '浏览' },
  { view: 'search', icon: Search, label: '搜索' },
  { view: 'chat', icon: MessageCircle, label: '对话' },
  { view: 'graph', icon: Network, label: '图谱' },
  { view: 'lint', icon: CheckSquare, label: '质量检查' },
  { view: 'review', icon: ClipboardList, label: '审核' },
  { view: 'sources', icon: FolderOpen, label: '来源' },
];

export function IconSidebar() {
  const activeView = useWikiStore((s) => s.activeView);
  const pendingReviewCount = useReviewStore((s) => s.items.filter((i) => !i.resolved).length);
  const researchPanelOpen = useResearchStore((s) => s.panelOpen);
  const researchActiveCount = useResearchStore(
    (s) => s.tasks.filter((t) => t.status !== 'done' && t.status !== 'error').length,
  );

  // 使用 setState 直接更新，绕过可能的选择器订阅问题
  const handleViewClick = (view: WikiView) => {
    useWikiStore.setState({ activeView: view });
  };

  const handleResearchToggle = () => {
    const current = useResearchStore.getState().panelOpen;
    useResearchStore.setState({ panelOpen: !current });
  };

  return (
    <div
      data-testid="icon-sidebar"
      className="flex h-full w-16 flex-col items-center border-r-2 border-primary/30 bg-surface py-3"
    >
      {/* Logo */}
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-primary text-text-inverse">
        <span className="text-base font-bold">W</span>
      </div>

      {/* Navigation items */}
      <div className="flex flex-1 flex-col items-center gap-1.5 w-full px-2">
        {NAV_ITEMS.map(({ view, icon: Icon, label }) => {
          const isActive = activeView === view;
          return (
            <button
              key={view}
              onClick={() => handleViewClick(view)}
              title={label}
              data-active={isActive}
              data-view={view}
              className={`relative flex h-11 w-11 items-center justify-center rounded-lg transition-all border-2 ${
                isActive
                  ? 'bg-primary text-text-inverse border-primary shadow-md scale-105'
                  : 'text-muted hover:bg-bg-muted hover:text-text hover:border-primary/30 border-transparent'
              }`}
            >
              <Icon className="h-5 w-5" />
              {view === 'review' && pendingReviewCount > 0 && (
                <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
                  {pendingReviewCount > 99 ? '99+' : pendingReviewCount}
                </span>
              )}
              {isActive && (
                <span className="absolute -right-2 top-1/2 -translate-y-1/2 h-6 w-1 bg-primary rounded-l-full" />
              )}
            </button>
          );
        })}

        {/* Separator */}
        <div className="w-8 h-px bg-border my-1" />

        {/* Research toggle */}
        <button
          onClick={handleResearchToggle}
          title="深度研究"
          className={`relative flex h-11 w-11 items-center justify-center rounded-lg transition-all border-2 ${
            researchPanelOpen
              ? 'bg-blue-500 text-white border-blue-500 shadow-md scale-105'
              : 'text-muted hover:bg-bg-muted hover:text-text hover:border-blue-500/30 border-transparent'
          }`}
        >
          <Globe className="h-5 w-5" />
          {researchActiveCount > 0 && (
            <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-blue-500 px-1 text-[10px] font-bold text-white">
              {researchActiveCount}
            </span>
          )}
        </button>
      </div>
    </div>
  );
}
