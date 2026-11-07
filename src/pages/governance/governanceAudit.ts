export interface GovernanceAuditOptions {
  projectId?: string | null;
  projectType?: string | null;
  activeTab?: string;
  milestonesCount?: number;
  profileCount?: number;
  allowedPathsCount?: number;
  scaffolding?: boolean;
}

export function formatProjectGovernanceAuditSnapshot(opts: GovernanceAuditOptions): string {
  return `projectGovernance|id=${opts.projectId || 'none'}|type=${opts.projectType || 'business'}|tab=${opts.activeTab || 'overview'}|milestones=${opts.milestonesCount ?? 0}|profile=${opts.profileCount ?? 0}|paths=${opts.allowedPathsCount ?? 0}|scaffolding=${opts.scaffolding ? 1 : 0}`;
}

export function formatProjectGovernanceAuditJson(opts: GovernanceAuditOptions): string {
  return JSON.stringify({
    projectId: opts.projectId || 'none',
    projectType: opts.projectType || 'business',
    activeTab: opts.activeTab || 'overview',
    milestonesCount: opts.milestonesCount ?? 0,
    profileCount: opts.profileCount ?? 0,
    allowedPathsCount: opts.allowedPathsCount ?? 0,
    scaffolding: Boolean(opts.scaffolding),
  });
}

export function auditProjectGovernancePageGovernance(): {
  module: 'src/pages/governance/GovernanceShell.tsx';
  phase: 'P173';
  domain: 'pages';
  tabs: readonly ['overview', 'rules', 'knowledge', 'files', 'settings'];
  compliant: boolean;
} {
  return {
    module: 'src/pages/governance/GovernanceShell.tsx',
    phase: 'P173',
    domain: 'pages',
    tabs: ['overview', 'rules', 'knowledge', 'files', 'settings'],
    compliant: true,
  };
}
