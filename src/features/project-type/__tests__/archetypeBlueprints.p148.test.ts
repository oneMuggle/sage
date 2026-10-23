import { describe, expect, it } from 'vitest';

import { auditArchetypeBlueprintsGovernance } from '../archetypeBlueprints';

describe('archetypeBlueprints P148 governance audit', () => {
  it('returns healthy defaults for archetypeBlueprints governance', () => {
    const res = auditArchetypeBlueprintsGovernance();
    expect(res.module).toBe('src/features/project-type/archetypeBlueprints.ts');
    expect(res.phase).toBe('P148');
    expect(res.blueprintCount).toBe(6);
    expect(res.supportsCustomArchetype).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('flags unhealthy when blueprintCount is below threshold', () => {
    const res = auditArchetypeBlueprintsGovernance({
      blueprintCount: 2,
      supportsCustomArchetype: false,
    });
    expect(res.blueprintCount).toBe(2);
    expect(res.supportsCustomArchetype).toBe(false);
    expect(res.healthy).toBe(false);
  });
});
