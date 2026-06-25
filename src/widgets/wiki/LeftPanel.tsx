// Left Panel - 左侧面板（文件树 + 活动面板）
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useState } from 'react';

import { WikiFileTree } from './WikiFileTree';

export function LeftPanel() {
  const [showActivity, setShowActivity] = useState(false);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* File tree section */}
      <div className="flex-1 overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-3 py-2">
          <span className="text-xs font-semibold text-text uppercase tracking-wide">文件树</span>
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
