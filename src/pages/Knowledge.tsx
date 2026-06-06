// Knowledge Page - Wiki workspace
import { useWikiStore } from '../entities/wiki/store';
import {
  WikiChat,
  WikiEditor,
  WikiFileTree,
  WikiProjectPicker,
  WikiSearch,
  WikiToolbar,
} from '../widgets/wiki';

export function Knowledge() {
  const project = useWikiStore((s) => s.project);
  const activeView = useWikiStore((s) => s.activeView);

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
        <div className="flex-1 min-w-0 overflow-hidden">
          {activeView === 'browser' && <WikiEditor />}
          {activeView === 'search' && <WikiSearch />}
          {activeView === 'chat' && <WikiChat />}
        </div>
      </div>
    </div>
  );
}
