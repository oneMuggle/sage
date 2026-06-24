// Right Panel - 右侧面板（文件预览 + 研究面板）
import { X } from 'lucide-react';

import { useResearchStore } from '../../entities/wiki/research-store';
import { useWikiStore } from '../../entities/wiki/store';

import { MarkdownPreview } from './MarkdownPreview';

export function RightPanel() {
  const selectedFile = useWikiStore((s) => s.selectedFile);
  const fileContent = useWikiStore((s) => s.fileContent);
  const researchPanelOpen = useResearchStore((s) => s.panelOpen);

  // 如果没有选中文件且研究面板未打开，不显示右侧面板
  if (!selectedFile && !researchPanelOpen) {
    return null;
  }

  return (
    <div className="flex h-full flex-col overflow-hidden border-l border-border bg-surface">
      {/* File preview section */}
      {selectedFile && (
        <div
          className={`flex-1 overflow-hidden ${researchPanelOpen ? 'border-b border-border' : ''}`}
        >
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-xs font-semibold text-text uppercase tracking-wide">
              预览: {selectedFile.split('/').pop()}
            </span>
          </div>
          <div className="flex-1 overflow-y-auto p-4">
            <MarkdownPreview content={fileContent} />
          </div>
        </div>
      )}

      {/* Research panel section */}
      {researchPanelOpen && (
        <div className={`${selectedFile ? 'h-1/2' : 'flex-1'} overflow-hidden`}>
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="text-xs font-semibold text-text uppercase tracking-wide">
              深度研究
            </span>
            <button
              onClick={() => useResearchStore.getState().setPanelOpen(false)}
              className="text-muted hover:text-text transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-4">
            <p className="text-sm text-muted">研究面板内容（待实现）</p>
          </div>
        </div>
      )}
    </div>
  );
}
