import { describe, expect, it } from 'vitest';

import {
  auditRegisterAssist,
  exportRegisterAssistAuditJson,
} from '../RegisterAssist';

describe('RegisterAssist audit diagnostics', () => {
  it('audits email presence and running state', () => {
    const def = auditRegisterAssist();
    expect(def.schemaVersion).toBe('1.0');
    expect(def.module).toBe('src/widgets/arena/RegisterAssist.tsx');
    expect(def.hasEmailInput).toBe(true);
    expect(def.isRunning).toBe(false);

    const busy = auditRegisterAssist('   ', true);
    expect(busy.hasEmailInput).toBe(false);
    expect(busy.isRunning).toBe(true);
  });

  it('exports serialized JSON payload', () => {
    const parsed = JSON.parse(exportRegisterAssistAuditJson('test@arena.ai', true));
    expect(parsed.componentName).toBe('RegisterAssist');
    expect(parsed.hasEmailInput).toBe(true);
    expect(parsed.exportedAt).toBe('2026-10-22');
  });
});
