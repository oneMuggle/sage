import type { KnowledgeDoc } from '../../shared/lib/hooks/useKnowledge';

import { KnowledgeCard } from './KnowledgeCard';

interface KnowledgeListProps {
  docs: KnowledgeDoc[];
  selectedIds: Set<string>;
  selectMode: boolean;
  onToggle: (id: string) => void;
  onCardClick?: (doc: KnowledgeDoc) => void;
}

export function KnowledgeList({
  docs,
  selectedIds,
  selectMode,
  onToggle,
  onCardClick,
}: KnowledgeListProps) {
  if (docs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted">
        <p className="text-lg mb-2">未找到匹配的文档</p>
        <p className="text-sm">尝试调整搜索词或筛选条件</p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
      {docs.map((doc) => (
        <KnowledgeCard
          key={doc.id}
          doc={doc}
          isSelected={selectedIds.has(doc.id)}
          selectMode={selectMode}
          onClick={() => onCardClick?.(doc)}
          onToggle={() => onToggle(doc.id)}
        />
      ))}
    </div>
  );
}
