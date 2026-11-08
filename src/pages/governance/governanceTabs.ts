export type GovernanceTab = 'overview' | 'rules' | 'knowledge' | 'files' | 'settings';

export const GOVERNANCE_TABS: ReadonlyArray<{ id: GovernanceTab; label: string }> = [
  { id: 'overview', label: '概览' },
  { id: 'rules', label: '规则' },
  { id: 'knowledge', label: '资料' },
  { id: 'files', label: '文件' },
  { id: 'settings', label: '设置' },
];

const LEGACY_TABS: Record<string, GovernanceTab> = {
  playbook: 'rules',
  references: 'files',
};

export function parseGovernanceTab(raw: string | null | undefined): GovernanceTab {
  if (!raw) return 'overview';
  if (GOVERNANCE_TABS.some((tab) => tab.id === raw)) return raw as GovernanceTab;
  return LEGACY_TABS[raw] ?? 'overview';
}

export function governanceHref(projectId: string, tab: GovernanceTab): string {
  return `/projects/governance/${encodeURIComponent(projectId)}?tab=${tab}`;
}
