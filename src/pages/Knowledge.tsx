// Knowledge Page - Wiki workspace with multi-panel layout
import { useEffect } from 'react';

import { useWikiStore } from '../entities/wiki/store';
import {
  IconSidebar,
  LeftPanel,
  RightPanel,
  SourcesView,
  WikiChat,
  WikiEditor,
  WikiGraphView,
  WikiInsightsPanel,
  WikiLintView,
  WikiProjectPicker,
  WikiQueuePanel,
  WikiReviewView,
  WikiSearch,
} from '../widgets/wiki';

const VIEW_TITLES: Record<string, string> = {
  browser: '浏览',
  search: '搜索',
  chat: '对话',
  graph: '图谱',
  insights: '洞察',
  lint: '质量检查',
  review: '内容审核',
  sources: '来源文件',
  queue: '摄入队列',
};

export function Knowledge() {
  // selector 订阅 (F4): 只在关心的字段变化时重渲染。此前的 useState 镜像 +
  // 无 selector 的 store.subscribe 让 store 任何字段变化都整页重渲染,
  // 与旁边注释宣称的"带 selector"相反。
  const activeView = useWikiStore((s) => s.activeView);
  const project = useWikiStore((s) => s.project);
  const graphData = useWikiStore((s) => s.graphData);
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
            project,
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
  project: ReturnType<typeof useWikiStore.getState>['project'];
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
    case 'insights':
      return props.project ? (
        <WikiInsightsPanel projectPath={props.project.path} onNodeClick={handleOpenFile} />
      ) : (
        <div className="flex h-full items-center justify-center text-muted text-sm">
          请先选择项目
        </div>
      );
    case 'lint':
      return props.project ? (
        <WikiLintView projectPath={props.project.path} />
      ) : (
        <div className="flex h-full items-center justify-center text-muted text-sm">
          请先选择项目
        </div>
      );
    case 'review':
      return props.project ? (
        <WikiReviewView projectPath={props.project.path} />
      ) : (
        <div className="flex h-full items-center justify-center text-muted text-sm">
          请先选择项目
        </div>
      );
    case 'sources':
      return <SourcesView />;
    case 'queue':
      return props.project ? (
        <WikiQueuePanel projectPath={props.project.path} />
      ) : (
        <div className="flex h-full items-center justify-center text-muted text-sm">
          请先选择项目
        </div>
      );
    default:
      return <WikiEditor />;
  }
}
