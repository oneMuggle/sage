import { describe, expect, it } from 'vitest';

import { auditMcpClientGovernance } from '../mcpClient';

describe('mcpClient P144 governance audit', () => {
  it('returns healthy defaults for mcpClient governance', () => {
    const res = auditMcpClientGovernance();
    expect(res.module).toBe('src/shared/api/mcpClient.ts');
    expect(res.phase).toBe('P144');
    expect(res.serverName).toBe('shuncode-bridge');
    expect(res.serverState).toBe('ready');
    expect(res.toolCount).toBe(16);
    expect(res.validName).toBe(true);
    expect(res.healthy).toBe(true);
  });

  it('validates serverName against MCP_NAME_REGEX and serverState', () => {
    const res = auditMcpClientGovernance({
      serverName: 'Invalid Name!',
      serverState: 'failed',
      toolCount: 3.4,
    });
    expect(res.validName).toBe(false);
    expect(res.serverState).toBe('failed');
    expect(res.toolCount).toBe(3);
    expect(res.healthy).toBe(false);
  });
});
