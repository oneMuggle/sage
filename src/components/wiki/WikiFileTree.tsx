// Wiki File Tree - recursive tree view of wiki files
import { ChevronRight, ChevronDown, FileText, Folder } from 'lucide-react';
import { useState } from 'react';

import { useWikiStore } from '../../stores/wiki-store';
import type { FileNode } from '../../types/wiki';

export function WikiFileTree() {
  const fileTree = useWikiStore((s) => s.fileTree);
  const selectedFile = useWikiStore((s) => s.selectedFile);
  const openFile = useWikiStore((s) => s.openFile);
  const loadFileTree = useWikiStore((s) => s.loadFileTree);

  useState(() => {
    loadFileTree();
  });

  if (fileTree.length === 0) {
    return <div className="p-4 text-center text-sm text-muted">暂无文件</div>;
  }

  return (
    <div className="py-2">
      {fileTree.map((node) => (
        <TreeNode
          key={node.path}
          node={node}
          depth={0}
          selectedFile={selectedFile}
          onFileClick={(path) => openFile(path)}
        />
      ))}
    </div>
  );
}

function TreeNode({
  node,
  depth,
  selectedFile,
  onFileClick,
}: {
  node: FileNode;
  depth: number;
  selectedFile: string | null;
  onFileClick: (path: string) => void;
}) {
  const [expanded, setExpanded] = useState(depth === 0);
  const isSelected = selectedFile === node.path;

  const handleClick = () => {
    if (node.is_dir) {
      setExpanded(!expanded);
    } else {
      onFileClick(node.path);
    }
  };

  const paddingLeft = depth * 12 + 8;

  return (
    <div>
      <button
        onClick={handleClick}
        className={`flex w-full items-center gap-1.5 py-1 pr-2 text-left text-sm hover:bg-bg-muted transition-colors ${
          isSelected ? 'bg-primary/10 text-primary' : 'text-text-secondary'
        }`}
        style={{ paddingLeft: `${paddingLeft}px` }}
      >
        {node.is_dir ? (
          <>
            {expanded ? (
              <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted" />
            )}
            <Folder className="h-3.5 w-3.5 shrink-0 text-muted" />
          </>
        ) : (
          <>
            <span className="w-3.5 shrink-0" />
            <FileText className="h-3.5 w-3.5 shrink-0 text-muted" />
          </>
        )}
        <span className="truncate">{node.name}</span>
      </button>
      {node.is_dir && expanded && node.children && (
        <div>
          {node.children.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedFile={selectedFile}
              onFileClick={onFileClick}
            />
          ))}
        </div>
      )}
    </div>
  );
}
