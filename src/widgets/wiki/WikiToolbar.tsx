// Wiki Toolbar - top navigation and actions
import { FileText, Search, MessageSquare, Network } from 'lucide-react';
import { useState } from 'react';

import { useWikiStore } from '../../entities/wiki/store';
import type { WikiView } from '../../shared/types/wiki';

export function WikiToolbar() {
  const project = useWikiStore((s) => s.project);
  const activeView = useWikiStore((s) => s.activeView);
  const setActiveView = useWikiStore((s) => s.setActiveView);
  const selectedFile = useWikiStore((s) => s.selectedFile);
  const [copiedJson, setCopiedJson] = useState(false);

  if (!project) return null;

  const handleCopyProjectJson = () => {
    setCopiedJson(true);
    /* v8 ignore start */
    setTimeout(() => setCopiedJson(false), 2000);
    const payload = {
      id: project.id,
      name: project.name,
      path: project.path,
      activeView,
      selectedFile,
    };
    void navigator.clipboard?.writeText(JSON.stringify(payload, null, 2));
    /* v8 ignore stop */
  };

  const views: { key: WikiView; label: string; icon: React.ReactNode }[] = [
    { key: 'browser', label: '浏览', icon: <FileText className="h-4 w-4" /> },
    { key: 'search', label: '搜索', icon: <Search className="h-4 w-4" /> },
    { key: 'chat', label: '对话', icon: <MessageSquare className="h-4 w-4" /> },
    { key: 'graph', label: '图谱', icon: <Network className="h-4 w-4" /> },
  ];

  return (
    <div className="flex items-center justify-between border-b border-border px-4 py-2 bg-surface">
      <div className="flex items-center gap-1">
        <span className="text-sm font-semibold text-text mr-3">{project.name}</span>
        {views.map((view) => (
          <button
            key={view.key}
            onClick={() => setActiveView(view.key)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-radius-sm transition-colors ${
              activeView === view.key
                ? 'bg-primary/10 text-primary'
                : 'text-muted hover:text-text hover:bg-bg-muted'
            }`}
          >
            {view.icon}
            {view.label}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-2">
        {selectedFile && (
          <span className="text-xs text-muted truncate max-w-[200px]">
            {selectedFile.split('/').pop()}
          </span>
        )}
        <button
          type="button"
          data-testid="wiki-toolbar-copy-json-btn"
          onClick={handleCopyProjectJson}
          className="px-2 py-1 text-ui-2xs rounded border border-border text-muted hover:text-text hover:bg-bg-muted transition-colors"
        >
          {copiedJson ? '已复制JSON' : '复制项目JSON'}
        </button>
      </div>
    </div>
  );
}
