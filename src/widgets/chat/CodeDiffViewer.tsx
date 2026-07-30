/**
 * A17 — Code Diff 可视化组件。
 *
 * 渲染 write_file / edit_file 工具产生的代码变更:
 * - old/new 全文可得(双侧 ≤ 64KB)→ react-diff-viewer-continued 高亮渲染
 * - 仅 unified_diff 可得(大文件降级)→ 按行着色的 unified 视图
 * - skipped 标记 → 一行说明(如 file_too_large)
 *
 * 数据契约见 `src/shared/lib/store.ts` 的 `CodeDiff`(与后端
 * `backend/application/services/code_diff.py` 1:1)。
 */
import { ChevronDown, FileDiff } from 'lucide-react';
import { memo, useContext, useState } from 'react';
import ReactDiffViewer from 'react-diff-viewer-continued';

import { ThemeContext } from '../../app/providers/useTheme';
import type { CodeDiff } from '../../shared/lib/store';

export interface CodeDiffViewerProps {
  /** 后端 code_diff.py 生成的 diff 载荷 */
  diff: CodeDiff;
  /** 默认是否展开(默认 true) */
  defaultExpanded?: boolean;
}

/** unified diff 降级渲染的单行样式分类(语义 token,自动适配 11 主题) */
function unifiedLineClass(line: string): string {
  if (line.startsWith('+++') || line.startsWith('---')) {
    return 'text-text-muted italic';
  }
  if (line.startsWith('@@')) {
    return 'text-info bg-info/10';
  }
  if (line.startsWith('+')) {
    return 'bg-success/10 text-role-green-text';
  }
  if (line.startsWith('-')) {
    return 'bg-error/10 text-error';
  }
  return 'text-text-secondary';
}

/** 从绝对路径取文件名(title 保留全路径) */
function fileName(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

/**
 * 深色模式判定:优先 ThemeContext(主题切换即时响应);
 * 无 Provider 时(如纯组件单测)回退读 root 的 .dark class。
 */
function useIsDark(): boolean {
  const theme = useContext(ThemeContext);
  if (theme) {
    return theme.resolved === 'dark';
  }
  return (
    typeof document !== 'undefined' &&
    document.documentElement.classList.contains('dark')
  );
}

function CodeDiffViewerComponent({ diff, defaultExpanded = true }: CodeDiffViewerProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const isDark = useIsDark();

  const hasFullContent =
    typeof diff.old_content === 'string' && typeof diff.new_content === 'string';
  const unifiedLines = (diff.unified_diff ?? '').split('\n');

  return (
    <div className="rounded border border-border overflow-hidden text-[12px]">
      {/* 头部:文件名 + 变更统计 + 折叠开关 */}
      <button
        type="button"
        onClick={() => setIsExpanded((v) => !v)}
        className="w-full flex items-center gap-2 px-2 py-1.5 bg-bg-subtle hover:bg-bg-hover transition-colors text-left"
        aria-expanded={isExpanded}
        aria-label="toggle-diff"
      >
        <FileDiff className="w-3.5 h-3.5 text-primary shrink-0" />
        <span
          className="font-mono font-semibold text-text-primary truncate"
          title={diff.path}
        >
          {fileName(diff.path)}
        </span>
        {diff.is_new_file && (
          <span className="px-1 rounded text-[10px] bg-success/15 text-success shrink-0">
            new
          </span>
        )}
        {typeof diff.additions === 'number' && (
          <span className="font-mono text-success shrink-0">+{diff.additions}</span>
        )}
        {typeof diff.deletions === 'number' && (
          <span className="font-mono text-error shrink-0">-{diff.deletions}</span>
        )}
        <ChevronDown
          className={`w-4 h-4 ml-auto text-muted transition-transform ${
            isExpanded ? 'rotate-180' : ''
          }`}
        />
      </button>

      {isExpanded && (
        <div className="border-t border-border">
          {diff.skipped ? (
            <div className="px-3 py-2 text-text-muted">diff 未展示: {diff.skipped}</div>
          ) : hasFullContent ? (
            <div className="max-h-96 overflow-auto">
              <ReactDiffViewer
                oldValue={diff.old_content ?? ''}
                newValue={diff.new_content ?? ''}
                splitView={false}
                showDiffOnly
                extraLinesSurroundingDiff={3}
                useDarkTheme={isDark}
              />
            </div>
          ) : diff.unified_diff ? (
            <pre
              data-testid="code-diff-unified"
              className="font-mono text-[11px] leading-relaxed px-2 py-1.5 max-h-96 overflow-auto m-0"
            >
              {unifiedLines.map((line, i) => (
                <div key={i} className={unifiedLineClass(line)}>
                  {line || ' '}
                </div>
              ))}
            </pre>
          ) : null}
          {diff.diff_truncated && (
            <div className="px-3 py-1 text-[10px] text-warning border-t border-border/50">
              diff 过大，已截断展示
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export const CodeDiffViewer = memo(CodeDiffViewerComponent);
