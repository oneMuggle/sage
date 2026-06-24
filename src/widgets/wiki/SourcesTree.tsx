// Sources Tree - 源文件树组件
import { ChevronDown, ChevronRight, File, Folder } from 'lucide-react';
import { useState } from 'react';

import type { FileNode } from '../../shared/types/wiki';

interface SourcesTreeProps {
  nodes: FileNode[];
  onFileClick?: (path: string) => void;
  onIngest?: (path: string) => void;
  onDelete?: (path: string) => void;
}

function TreeNode({
  node,
  level,
  onFileClick,
  onIngest,
  onDelete,
}: {
  node: FileNode;
  level: number;
  onFileClick?: (path: string) => void;
  onIngest?: (path: string) => void;
  onDelete?: (path: string) => void;
}) {
  const [isExpanded, setIsExpanded] = useState(false);

  const handleClick = () => {
    if (node.is_dir) {
      setIsExpanded(!isExpanded);
    } else {
      onFileClick?.(node.path);
    }
  };

  return (
    <div>
      <div
        className={`flex items-center gap-2 px-2 py-1.5 hover:bg-bg-muted cursor-pointer transition-colors ${
          !node.is_dir ? 'text-text' : 'text-text font-medium'
        }`}
        style={{ paddingLeft: `${level * 16 + 8}px` }}
        onClick={handleClick}
      >
        {node.is_dir ? (
          <>
            {isExpanded ? (
              <ChevronDown className="h-3 w-3 text-muted flex-shrink-0" />
            ) : (
              <ChevronRight className="h-3 w-3 text-muted flex-shrink-0" />
            )}
            <Folder className="h-4 w-4 text-blue-500 flex-shrink-0" />
          </>
        ) : (
          <>
            <span className="w-3 flex-shrink-0" />
            <File className="h-4 w-4 text-muted flex-shrink-0" />
          </>
        )}
        <span className="text-sm truncate">{node.name}</span>
      </div>

      {/* Actions for files */}
      {!node.is_dir && (
        <div
          className="flex items-center gap-2 px-2 py-1"
          style={{ paddingLeft: `${level * 16 + 32}px` }}
        >
          {onIngest && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onIngest(node.path);
              }}
              className="px-2 py-0.5 text-xs rounded-radius-sm border border-border text-text hover:bg-bg-muted transition-colors"
            >
              导入到 Wiki
            </button>
          )}
          {onDelete && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete(node.path);
              }}
              className="px-2 py-0.5 text-xs rounded-radius-sm border border-border text-red-500 hover:bg-red-500/10 transition-colors"
            >
              删除
            </button>
          )}
        </div>
      )}

      {/* Children */}
      {node.is_dir && isExpanded && node.children && (
        <div>
          {node.children.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              level={level + 1}
              onFileClick={onFileClick}
              onIngest={onIngest}
              onDelete={onDelete}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function SourcesTree({ nodes, onFileClick, onIngest, onDelete }: SourcesTreeProps) {
  return (
    <div className="py-2">
      {nodes.map((node) => (
        <TreeNode
          key={node.path}
          node={node}
          level={0}
          onFileClick={onFileClick}
          onIngest={onIngest}
          onDelete={onDelete}
        />
      ))}
    </div>
  );
}
