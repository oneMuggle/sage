// src/widgets/chat/preview/ArchivePreview.tsx
//
// 压缩包浏览器 —— 文件树 + 条目预览（feat/archive-preview）。
// 数据源：GET /sessions/{id}/workspace/preview?path=archive.zip（目录列表）
//         GET /sessions/{id}/workspace/preview?path=archive.zip&entry=src/main.py（条目内容）
import { ChevronDown, ChevronRight, FileArchive, FileIcon, FolderIcon, Search } from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';

import {
  workspaceApi,
  type ArchiveEntryInfo,
  type WorkspacePreviewContent,
} from '../../../shared/api/workspaceApi';
import { langFromPath } from '../../../shared/lib/fileLang';
import { Markdown } from '../../markdown';
import { ShikiCodeBlock } from '../ShikiCodeBlock';

interface ArchivePreviewProps {
  sessionId: string;
  /** 压缩包文件路径（工作区相对或绝对） */
  path: string;
  /** 初始目录列表数据 */
  data: WorkspacePreviewContent;
}

interface TreeNode extends ArchiveEntryInfo {
  children?: TreeNode[];
  depth: number;
}

function buildTree(entries: ArchiveEntryInfo[]): TreeNode[] {
  const root: TreeNode[] = [];
  const dirMap = new Map<string, TreeNode>();

  const sorted = [...entries].sort((a, b) => {
    if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
    return a.name.localeCompare(b.name);
  });

  for (const entry of sorted) {
    const parts = entry.name.split('/').filter(Boolean);
    const node: TreeNode = { ...entry, depth: parts.length - 1 };

    if (parts.length === 1) {
      root.push(node);
    } else {
      const parentPath = parts.slice(0, -1).join('/');
      const parent = dirMap.get(parentPath);
      if (parent) {
        if (!parent.children) parent.children = [];
        parent.children.push(node);
      } else {
        root.push(node);
      }
    }

    if (entry.is_dir) {
      dirMap.set(entry.name, node);
    }
  }

  return root;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function EntryRow({
  node,
  expanded,
  onToggle,
  onSelect,
  selected,
}: {
  node: TreeNode;
  expanded: boolean;
  onToggle: () => void;
  onSelect: () => void;
  selected: boolean;
}) {
  const name = node.name.split('/').pop() || node.name;
  const indent = node.depth * 16;

  return (
    <div
      className={`flex items-center gap-1 px-2 py-1 cursor-pointer hover:bg-bg-hover rounded text-sm ${
        selected ? 'bg-bg-hover' : ''
      }`}
      style={{ paddingLeft: `${indent + 8}px` }}
      onClick={node.is_dir ? onToggle : onSelect}
    >
      {node.is_dir ? (
        <>
          {expanded ? (
            <ChevronDown className="w-4 h-4 text-muted shrink-0" />
          ) : (
            <ChevronRight className="w-4 h-4 text-muted shrink-0" />
          )}
          <FolderIcon className="w-4 h-4 text-blue-500 shrink-0" />
        </>
      ) : node.is_archive ? (
        <>
          <span className="w-4 shrink-0" />
          <FileArchive className="w-4 h-4 text-amber-500 shrink-0" />
        </>
      ) : (
        <>
          <span className="w-4 shrink-0" />
          <FileIcon className="w-4 h-4 text-muted shrink-0" />
        </>
      )}
      <span className="truncate flex-1">{name}</span>
      {!node.is_dir && <span className="text-xs text-muted shrink-0">{formatSize(node.size)}</span>}
    </div>
  );
}

function renderEntryContent(content: WorkspacePreviewContent, entryName: string): React.ReactNode {
  if (!content.ok) {
    return <div className="text-sm text-error">{content.error || '加载失败'}</div>;
  }
  if (content.kind === 'image') {
    return <img src={content.data_url} alt={entryName} className="max-w-full rounded" />;
  }
  if (content.kind === 'code' || content.kind === 'json') {
    return (
      <ShikiCodeBlock language={content.kind === 'json' ? 'json' : langFromPath(entryName)}>
        {content.content ?? ''}
      </ShikiCodeBlock>
    );
  }
  if (content.kind === 'markdown') {
    return <Markdown content={content.content ?? ''} tier="chat" />;
  }
  return <pre className="whitespace-pre-wrap text-sm">{content.content}</pre>;
}

export function ArchivePreview({ sessionId, path, data }: ArchivePreviewProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selectedEntry, setSelectedEntry] = useState<string | null>(null);
  const [entryContent, setEntryContent] = useState<WorkspacePreviewContent | null>(null);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');

  const tree = useMemo(() => {
    if (!data.entries) return [];
    return buildTree(data.entries);
  }, [data.entries]);

  const filteredTree = useMemo(() => {
    if (!search) return tree;
    const lower = search.toLowerCase();
    const filterNodes = (nodes: TreeNode[]): TreeNode[] =>
      nodes
        .filter((n) => n.name.toLowerCase().includes(lower) || n.is_dir)
        .map((n) => ({
          ...n,
          children: n.children ? filterNodes(n.children) : undefined,
        }));
    return filterNodes(tree);
  }, [tree, search]);

  const toggleExpanded = useCallback((name: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  const handleSelectEntry = useCallback(
    async (entryName: string) => {
      setSelectedEntry(entryName);
      setLoading(true);
      try {
        const result = await workspaceApi.previewArchiveEntry(sessionId, path, entryName);
        setEntryContent(result);
      } catch (err) {
        setEntryContent({
          ok: false,
          error: err instanceof Error ? err.message : String(err),
        });
      } finally {
        setLoading(false);
      }
    },
    [sessionId, path],
  );

  const renderTree = (nodes: TreeNode[]): React.ReactNode =>
    nodes.map((node) => (
      <div key={node.name}>
        <EntryRow
          node={node}
          expanded={expanded.has(node.name)}
          onToggle={() => toggleExpanded(node.name)}
          onSelect={() => handleSelectEntry(node.name)}
          selected={selectedEntry === node.name}
        />
        {node.is_dir && expanded.has(node.name) && node.children && (
          <div>{renderTree(node.children)}</div>
        )}
      </div>
    ));

  return (
    <div className="flex flex-col h-full" data-testid="archive-preview">
      {/* 头部信息 */}
      <div className="px-3 py-2 border-b border-border bg-bg-subtle">
        <div className="flex items-center gap-2 text-sm">
          <FileArchive className="w-4 h-4 text-amber-500" />
          <span className="font-medium">{path.split('/').pop()}</span>
          <span className="text-muted">
            {data.entry_count} 个条目 · {formatSize(data.total_uncompressed ?? 0)}
          </span>
        </div>
        {data.encrypted && (
          <div className="text-xs text-amber-600 mt-1">压缩包已加密，部分内容可能无法预览</div>
        )}
      </div>

      {/* 搜索框 */}
      <div className="px-3 py-2 border-b border-border">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
          <input
            type="text"
            placeholder="搜索文件..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-8 pr-2 py-1 text-sm bg-bg border border-border rounded focus:outline-none focus:border-primary"
          />
        </div>
      </div>

      {/* 内容区：左树右预览 */}
      <div className="flex-1 flex overflow-hidden">
        {/* 左侧文件树 */}
        <div className="w-64 shrink-0 border-r border-border overflow-auto">
          {renderTree(filteredTree)}
        </div>

        {/* 右侧条目预览 */}
        <div className="flex-1 overflow-auto p-3">
          {loading ? (
            <div className="text-sm text-muted">加载中...</div>
          ) : selectedEntry && entryContent ? (
            <div>
              <div className="text-xs text-muted mb-2">{selectedEntry}</div>
              {renderEntryContent(entryContent, selectedEntry)}
            </div>
          ) : (
            <div className="text-sm text-muted">选择一个文件以预览内容</div>
          )}
        </div>
      </div>
    </div>
  );
}
