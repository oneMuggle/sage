import { BookOpen, X } from 'lucide-react';

interface KnowledgeChipProps {
  title: string;
  onRemove?: () => void;
}

export function KnowledgeChip({ title, onRemove }: KnowledgeChipProps) {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-1 rounded-radius-sm bg-subtle text-xs text-text-secondary border border-border">
      <BookOpen className="w-3 h-3" />
      <span className="truncate max-w-32">{title}</span>
      {onRemove && (
        <button className="ml-1 hover:text-text transition-colors" onClick={onRemove}>
          <X className="w-3 h-3" />
        </button>
      )}
    </span>
  );
}

export interface KnowledgeChipAuditInput {
  sourceId: string;
  label: string;
  relevanceScore: number;
  clickable: boolean;
}

export interface KnowledgeChipAuditReport {
  sourceId: string;
  label: string;
  relevancePct: number;
  clickable: boolean;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateKnowledgeChipAudit(
  input: KnowledgeChipAuditInput,
): KnowledgeChipAuditReport {
  const sourceId = input.sourceId.trim();
  const label = input.label.trim();
  const clampedScore = Math.max(0, Math.min(1, Number.isFinite(input.relevanceScore) ? input.relevanceScore : 0));
  const relevancePct = Math.round(clampedScore * 100);
  const issueCodes: string[] = [];

  if (!sourceId) {
    issueCodes.push('missing_knowledge_source_id');
  }
  if (!label) {
    issueCodes.push('missing_knowledge_chip_label');
  }
  if (relevancePct < 20) {
    issueCodes.push('low_knowledge_relevance');
  }

  return {
    sourceId,
    label,
    relevancePct,
    clickable: Boolean(input.clickable),
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}

// eslint-disable-next-line react-refresh/only-export-components
export function exportKnowledgeChipAuditJson(
  input: KnowledgeChipAuditInput,
): string {
  return JSON.stringify(evaluateKnowledgeChipAudit(input));
}
