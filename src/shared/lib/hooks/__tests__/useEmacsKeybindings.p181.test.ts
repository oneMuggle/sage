import { describe, expect, it } from 'vitest';

import {
  auditUseEmacsKeybindingsGovernance,
  formatEmacsKeybindingsJson,
  formatEmacsKeybindingsSummary,
} from '../useEmacsKeybindings';

describe('useEmacsKeybindings P181 governance audit', () => {
  it('audits useEmacsKeybindings governance contract and cursor formatters', () => {
    const raw = auditUseEmacsKeybindingsGovernance();
    const parsed = JSON.parse(raw);
    expect(parsed.schema).toBe('sage.shared.lib.hooks.use_emacs_keybindings.governance.v1');
    expect(parsed.phase).toBe('P181');
    expect(parsed.supportedShortcuts).toContain('Ctrl+K');
    expect(formatEmacsKeybindingsSummary('abc', 1, true)).toContain('emacs: enabled · len=3');
    expect(JSON.parse(formatEmacsKeybindingsJson('abc', 1, true)).cursor).toBe(1);
  });
});
