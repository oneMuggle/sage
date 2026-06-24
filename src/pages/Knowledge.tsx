// Knowledge Page - Wiki workspace with multi-panel layout
import { useEffect, useState } from 'react';

import { useWikiStore } from '../entities/wiki/store';
import {
  IconSidebar,
  LeftPanel,
  LintView,
  ResearchPanel,
  ReviewView,
  RightPanel,
  SourcesView,
  WikiChat,
  WikiEditor,
  WikiGraphView,
  WikiProjectPicker,
  WikiSearch,
} from '../widgets/wiki';

const VIEW_TITLES: Record<string, string> = {
  browser: '浏览',
  search: '搜索',
  chat: '对话',
  graph: '图谱',
  lint: '质量检查',
  review: '审核队列',
  sources: '来源文件',
};

interface WikiState {
  activeView: string;
  project: ReturnType<typeof useWikiStore.getState>['project'];
  graphData: ReturnType<typeof useWikiStore.getState>['graphData'];
}

export function Knowledge() {
  // 用 useState 镜像整个 wiki store 状态（确保每次 store 变化都重新渲染）
  const [state, setState] = useState<WikiState>(() => ({
    activeView: useWikiStore.getState().activeView,
    project: useWikiStore.getState().project,
    graphData: useWikiStore.getState().graphData,
  }));

  // 订阅 store 变化（带 selector，只在关心的字段变化时更新）
  useEffect(() => {
    const unsubscribe = useWikiStore.subscribe((s) => {
      setState({
        activeView: s.activeView,
        project: s.project,
        graphData: s.graphData,
      });
    });
    return unsubscribe;
  }, []);

  const { activeView, project, graphData } = state;
  const loadGraph = useWikiStore.getState().loadGraph;
  const openFile = useWikiStore.getState().openFile;

  // 切到 graph 视图时加载图谱
  useEffect(() => {
    if (activeView === 'graph' && project && !graphData) {
      void loadGraph();
    }
  }, [activeView, project, graphData, loadGraph]);

  if (!project) {
    return (
      <div className="flex flex-1 overflow-hidden">
        <IconSidebar />
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="h-12 flex items-center px-5 border-b border-border bg-surface flex-shrink-0">
            <h2 className="text-[18px] font-semibold text-text">知识库</h2>
          </div>
          <div className="flex-1 overflow-hidden">
            <WikiProjectPicker />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Icon Sidebar - 左侧图标导航栏 */}
      <IconSidebar />

      {/* Left Panel - 左侧面板（仅 browser/search 视图显示） */}
      {(activeView === 'browser' || activeView === 'search') && (
        <div className="w-56 border-r border-border bg-surface flex-shrink-0 flex flex-col overflow-hidden">
          <LeftPanel />
        </div>
      )}

      {/* Main Content Area */}
      <div className="flex-1 min-w-0 overflow-hidden flex flex-col">
        {/* 顶部标题栏 */}
        <div
          data-testid="view-title"
          data-view={activeView}
          className="h-12 flex items-center px-5 border-b border-border bg-surface flex-shrink-0"
        >
          <h2 className="text-[18px] font-semibold text-text">
            知识库 · {VIEW_TITLES[activeView] || activeView}
          </h2>
          <span className="ml-auto text-xs text-muted">
            当前视图:{' '}
            <code className="px-1 py-0.5 rounded bg-bg-muted text-primary">{activeView}</code>
          </span>
        </div>
        {/* 内容区 */}
        <div className="flex-1 min-h-0 overflow-hidden">
          {renderMainView(activeView, {
            openFile,
            graphData,
          })}
        </div>
      </div>

      {/* Right Panel - 右侧面板（仅 browser 视图显示预览） */}
      {activeView === 'browser' && <RightPanel />}
    </div>
  );
}

interface MainViewProps {
  openFile: (path: string) => Promise<void>;
  graphData: ReturnType<typeof useWikiStore.getState>['graphData'];
}

function renderMainView(activeView: string, props: MainViewProps) {
  const handleOpenFile = (path: string) => {
    void props.openFile(path);
    useWikiStore.setState({ activeView: 'browser' });
  };

  switch (activeView) {
    case 'browser':
      return <WikiEditor />;
    case 'search':
      return <WikiSearch />;
    case 'chat':
      return <WikiChat />;
    case 'graph':
      return props.graphData ? (
        <WikiGraphView data={props.graphData} query="" onNodeClick={handleOpenFile} />
      ) : (
        <div className="flex h-full items-center justify-center text-muted text-sm">
          加载图谱中...
        </div>
      );
    case 'lint':
      return <LintView />;
    case 'review':
      return <ReviewView />;
    case 'sources':
      return <SourcesView />;
    default:
      return <WikiEditor />;
  }
}

// Export sub-components for backward compatibility
export { ResearchPanel };
