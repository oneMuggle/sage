// Knowledge Page - Wiki workspace
import { Search } from 'lucide-react';
import { useEffect, useState } from 'react';

import { useWikiStore } from '../entities/wiki/store';
import {
  WikiChat,
  WikiEditor,
  WikiFileTree,
  WikiGraphView,
  WikiProjectPicker,
  WikiSearch,
  WikiToolbar,
} from '../widgets/wiki';

export function Knowledge() {
  const project = useWikiStore((s) => s.project);
  const activeView = useWikiStore((s) => s.activeView);
  const graphData = useWikiStore((s) => s.graphData);
  const graphQuery = useWikiStore((s) => s.graphQuery);
  const loadGraph = useWikiStore((s) => s.loadGraph);
  const setGraphQuery = useWikiStore((s) => s.setGraphQuery);
  const openFile = useWikiStore((s) => s.openFile);
  const setActiveView = useWikiStore((s) => s.setActiveView);

  // 切到 graph 视图时加载图谱
  useEffect(() => {
    if (activeView === 'graph' && project && !graphData) {
      void loadGraph();
    }
  }, [activeView, project, graphData, loadGraph]);

  if (!project) {
    return (
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="h-12 flex items-center px-5 border-b border-border bg-surface flex-shrink-0">
          <h2 className="text-[18px] font-semibold text-text">知识库</h2>
        </div>
        <div className="flex-1 overflow-hidden">
          <WikiProjectPicker />
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="h-12 flex items-center px-5 border-b border-border bg-surface flex-shrink-0">
        <h2 className="text-[18px] font-semibold text-text">知识库</h2>
      </div>
      <WikiToolbar />
      <div className="flex-1 flex overflow-hidden">
        {/* Sidebar: file tree (only in browser view) */}
        {activeView === 'browser' && (
          <div className="w-56 border-r border-border overflow-y-auto bg-surface flex-shrink-0">
            <WikiFileTree />
          </div>
        )}
        {/* Main content area */}
        <div className="flex-1 min-w-0 overflow-hidden flex flex-col">
          {activeView === 'browser' && <WikiEditor />}
          {activeView === 'search' && <WikiSearch />}
          {activeView === 'chat' && <WikiChat />}
          {activeView === 'graph' && (
            <GraphPanel
              graphData={graphData}
              query={graphQuery}
              setQuery={setGraphQuery}
              onLoad={() => loadGraph()}
              onNodeClick={(path) => {
                void openFile(path);
                setActiveView('browser');
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// Graph 视图:搜索框 + React Flow
function GraphPanel({
  graphData,
  query,
  setQuery,
  onLoad,
  onNodeClick,
}: {
  graphData: ReturnType<typeof useWikiStore.getState>['graphData'];
  query: string;
  setQuery: (q: string) => void;
  onLoad: () => void;
  onNodeClick: (path: string) => void;
}) {
  const [local, setLocal] = useState(query);
  return (
    <>
      <div className="flex items-center gap-2 border-b border-border px-4 py-2 bg-surface">
        <Search className="h-4 w-4 text-muted" />
        <input
          type="text"
          value={local}
          onChange={(e) => setLocal(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              setQuery(local);
              onLoad();
            }
          }}
          onBlur={() => {
            if (local !== query) {
              setQuery(local);
              onLoad();
            }
          }}
          placeholder="搜索节点(label 或 id 包含)..."
          className="flex-1 rounded-md border border-border bg-bg-muted px-3 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
        />
      </div>
      <div className="flex-1 min-h-0 relative">
        {graphData && <WikiGraphView data={graphData} query={query} onNodeClick={onNodeClick} />}
      </div>
    </>
  );
}
