// Right Panel - 右侧面板（文件预览 + 研究面板）
import { X } from 'lucide-react';
import { useState } from 'react';

import { useResearchStore } from '../../entities/wiki/research-store';
import { useWikiStore } from '../../entities/wiki/store';

import { MarkdownPreview } from './MarkdownPreview';

export function RightPanel() {
  const selectedFile = useWikiStore((s) => s.selectedFile);
  const fileContent = useWikiStore((s) => s.fileContent);
  const researchPanelOpen = useResearchStore((s) => s.panelOpen);
  const [copiedPreviewMd, setCopiedPreviewMd] = useState(false);
  const [copiedPreviewJson, setCopiedPreviewJson] = useState(false);

  const handleCopyPreviewMd = () => {
    setCopiedPreviewMd(true);
    /* v8 ignore start */
    setTimeout(() => setCopiedPreviewMd(false), 2000);
    void navigator.clipboard?.writeText(fileContent);
    /* v8 ignore stop */
  };

  const handleCopyPreviewJson = () => {
    setCopiedPreviewJson(true);
    /* v8 ignore start */
    setTimeout(() => setCopiedPreviewJson(false), 2000);
    const payload = {
      path: selectedFile,
      fileName: selectedFile?.split('/').pop() ?? '',
      content: fileContent,
      exportedAt: new Date().toISOString(),
    };
    void navigator.clipboard?.writeText(JSON.stringify(payload, null, 2));
    /* v8 ignore stop */
  };

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
            <div className="flex items-center gap-1">
              <button
                type="button"
                data-testid="wiki-right-preview-copy-md-btn"
                onClick={handleCopyPreviewMd}
                className="px-1.5 py-0.5 text-ui-2xs rounded border border-border text-muted hover:text-text hover:bg-bg-muted transition-colors"
              >
                {copiedPreviewMd ? '已复制MD' : '复制预览MD'}
              </button>
              <button
                type="button"
                data-testid="wiki-right-preview-copy-json-btn"
                onClick={handleCopyPreviewJson}
                className="px-1.5 py-0.5 text-ui-2xs rounded border border-border text-muted hover:text-text hover:bg-bg-muted transition-colors"
              >
                {copiedPreviewJson ? '已复制JSON' : '复制预览JSON'}
              </button>
            </div>
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
