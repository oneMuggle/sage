import { describe, expect, it } from 'vitest';

import { GOVERNANCE_TABS, governanceHref, parseGovernanceTab } from '../governanceTabs';

describe('parseGovernanceTab', () => {
  it('returns overview for missing or unknown values', () => {
    expect(parseGovernanceTab(null)).toBe('overview');
    expect(parseGovernanceTab('nope')).toBe('overview');
  });

  it('accepts the five canonical tabs', () => {
    for (const tab of GOVERNANCE_TABS) expect(parseGovernanceTab(tab.id)).toBe(tab.id);
  });

  it('maps legacy deep links', () => {
    expect(parseGovernanceTab('playbook')).toBe('rules');
    expect(parseGovernanceTab('references')).toBe('files');
  });
});

describe('governanceHref', () => {
  it('builds an encoded deep link', () => {
    expect(governanceHref('p 1', 'rules')).toBe('/projects/governance/p%201?tab=rules');
  });
});

describe('GOVERNANCE_TABS', () => {
  it('exposes exactly five tabs in order', () => {
    expect(GOVERNANCE_TABS.map((tab) => tab.id)).toEqual([
      'overview',
      'rules',
      'knowledge',
      'files',
      'settings',
    ]);
  });
});
