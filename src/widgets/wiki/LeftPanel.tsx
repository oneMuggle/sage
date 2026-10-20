// Left Panel - 左侧面板（文件树 + 活动面板）
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useState } from 'react';

import { useWikiStore } from '../../entities/wiki/store';

import { WikiFileTree } from './WikiFileTree';

export function LeftPanel() {
  const fileTree = useWikiStore((s) => s.fileTree);
  const [showActivity, setShowActivity] = useState(false);
  const [copiedTreeMd, setCopiedTreeMd] = useState(false);
  const [copiedTreeJson, setCopiedTreeJson] = useState(false);

  const handleCopyTreeMd = () => {
    setCopiedTreeMd(true);
    /* v8 ignore start */
    setTimeout(() => setCopiedTreeMd(false), 2000);
    const lines = [
      '# Wiki 文件树清单',
      '',
      `- 顶层节点数: ${fileTree.length}`,
      ...fileTree.map((n) => `- ${n.is_dir ? '📁' : '📄'} ${n.name} (\`${n.path}\`)`),
    ];
    void navigator.clipboard?.writeText(lines.join('\n'));
    /* v8 ignore stop */
  };

  const handleCopyTreeJson = () => {
    setCopiedTreeJson(true);
    /* v8 ignore start */
    setTimeout(() => setCopiedTreeJson(false), 2000);
    const payload = {
      topLevelCount: fileTree.length,
      fileTree,
      exportedAt: new Date().toISOString(),
    };
    void navigator.clipboard?.writeText(JSON.stringify(payload, null, 2));
    /* v8 ignore stop */
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* File tree section */}
      <div className="flex-1 overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-3 py-2">
          <span className="text-xs font-semibold text-text uppercase tracking-wide">文件树</span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              data-testid="wiki-file-tree-copy-md-btn"
              onClick={handleCopyTreeMd}
              className="px-1.5 py-0.5 text-ui-2xs rounded border border-border text-muted hover:text-text hover:bg-bg-muted transition-colors"
            >
              {copiedTreeMd ? '已复制MD' : '复制树MD'}
            </button>
            <button
              type="button"
              data-testid="wiki-file-tree-copy-json-btn"
              onClick={handleCopyTreeJson}
              className="px-1.5 py-0.5 text-ui-2xs rounded border border-border text-muted hover:text-text hover:bg-bg-muted transition-colors"
            >
              {copiedTreeJson ? '已复制JSON' : '复制树JSON'}
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto">
          <WikiFileTree />
        </div>
      </div>

      {/* Activity panel toggle */}
      <div className="border-t border-border">
        <button
          onClick={() => setShowActivity(!showActivity)}
          className="flex w-full items-center justify-between px-3 py-2 text-xs font-semibold text-text uppercase tracking-wide hover:bg-bg-muted transition-colors"
        >
          <span>活动</span>
          {showActivity ? (
            <ChevronDown className="h-3 w-3 text-muted" />
          ) : (
            <ChevronRight className="h-3 w-3 text-muted" />
          )}
        </button>
        {showActivity && (
          <div className="border-t border-border p-2 text-xs text-muted">
            <p>活动面板内容（待实现）</p>
          </div>
        )}
      </div>
    </div>
  );
}
