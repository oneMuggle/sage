import { describe, expect, it } from 'vitest';

import { rulePackToMarkdown } from '../rulePackMarkdown';
import type { RulePack } from '../ruleTypes';

const PACK: RulePack = {
  name: 'Style pack',
  version: '2.0',
  exportedAt: '2026-11-07T10:00:00Z',
  exportedBy: 'local',
  groups: [
    {
      id: 'group-1',
      name: 'Style',
      description: '格式规范',
      priority: 7,
      builtin: false,
      rules: [
        {
          id: 'rule-regex',
          name: 'No passive',
          type: 'format',
          severity: 'warning',
          scope: 'body',
          description: 'avoid is',
          checkMode: 'regex',
          pattern: '\\bis\\b',
          enabled: true,
          groupId: 'group-1',
        },
        {
          id: 'rule-ai',
          name: 'Term check',
          type: 'terminology',
          severity: 'error',
          scope: 'full',
          description: '',
          checkMode: 'ai',
          aiPrompt: 'check terms',
          enabled: false,
          groupId: 'group-1',
        },
      ],
    },
  ],
};

describe('rulePackToMarkdown', () => {
  it('renders the group heading with its priority and both rule kinds', () => {
    const markdown = rulePackToMarkdown(PACK);

    expect(markdown).toContain('# Style pack');
    expect(markdown).toContain('## Style (priority 7)');
    expect(markdown).toContain('格式规范');
    expect(markdown).toContain('- [x] **No passive** — format / warning / body / regex');
    expect(markdown).toContain('- pattern: `\\bis\\b`');
    expect(markdown).toContain('- [ ] **Term check** — terminology / error / full / ai');
    expect(markdown).toContain('- prompt: check terms');
  });
});
