import { describe, expect, it } from 'vitest';

import {
  auditEditAgentForm,
  exportEditAgentFormAuditJson,
} from '../EditAgentForm';

describe('EditAgentForm audit diagnostics', () => {
  it('audits default and empty states', () => {
    const def = auditEditAgentForm();
    expect(def.schemaVersion).toBe('1.0');
    expect(def.module).toBe('src/widgets/agents/EditAgentForm.tsx');
    expect(def.hasNameField).toBe(true);
    expect(def.hasSystemPromptField).toBe(true);
    expect(def.isDirty).toBe(false);

    const empty = auditEditAgentForm('   ', '', true);
    expect(empty.hasNameField).toBe(false);
    expect(empty.hasSystemPromptField).toBe(false);
    expect(empty.isDirty).toBe(true);
  });

  it('exports serialized JSON payload', () => {
    const parsed = JSON.parse(exportEditAgentFormAuditJson('Coder', 'Write clean code.', true));
    expect(parsed.componentName).toBe('EditAgentForm');
    expect(parsed.isDirty).toBe(true);
    expect(parsed.exportedAt).toBe('2026-10-22');
  });
});
