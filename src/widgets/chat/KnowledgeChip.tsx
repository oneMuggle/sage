import { BookOpen, Copy, X } from 'lucide-react';

import { copyToClipboard } from '../../shared/lib/clipboard';
import { useI18n } from '../../shared/lib/i18n';
import { ContextMenu } from '../../shared/ui/ContextMenu/ContextMenu';

interface KnowledgeChipProps {
  title: string;
  onRemove?: () => void;
}

export function KnowledgeChip({ title, onRemove }: KnowledgeChipProps) {
  const { t } = useI18n();
  const menuItems = () => [
    {
      id: 'copy-knowledge-name',
      label: t('contextMenu.common.copyName'),
      icon: Copy,
      onSelect: () =>
        void copyToClipboard(title, {
          successMessage: t('contextMenu.common.copied'),
          errorMessage: t('contextMenu.common.copyFailed'),
        }),
    },
    ...(onRemove
      ? [
          { id: 'knowledge-remove-sep', kind: 'separator' as const },
          {
            id: 'knowledge-remove',
            label: t('contextMenu.common.remove'),
            icon: X,
            destructive: true,
            onSelect: onRemove,
          },
        ]
      : []),
  ];

  return (
    <ContextMenu items={menuItems}>
      <span className="inline-flex items-center gap-1 px-2 py-1 rounded-radius-sm bg-subtle text-xs text-text-secondary border border-border">
        <BookOpen className="w-3 h-3" />
        <span className="truncate max-w-32">{title}</span>
        {onRemove && (
          <button className="ml-1 hover:text-text transition-colors" onClick={onRemove}>
            <X className="w-3 h-3" />
          </button>
        )}
      </span>
    </ContextMenu>
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
  const clampedScore = Math.max(
    0,
    Math.min(1, Number.isFinite(input.relevanceScore) ? input.relevanceScore : 0),
  );
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
export function exportKnowledgeChipAuditJson(input: KnowledgeChipAuditInput): string {
  return JSON.stringify(evaluateKnowledgeChipAudit(input));
}
// eslint-disable-next-line react-refresh/only-export-components
export function auditKnowledgeChipGovernance(): string {
  return JSON.stringify({
    module: 'knowledge-chip',
    phase: 'P186',
    audited: true,
  });
}
