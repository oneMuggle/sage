import type { GovernanceData } from '../useGovernanceProject';

export interface KnowledgeSectionProps {
  data: GovernanceData;
  onStartSession: () => void;
}

export function KnowledgeSection(_props: KnowledgeSectionProps) {
  return <div data-testid="section-knowledge">Chapter: knowledge</div>;
}
