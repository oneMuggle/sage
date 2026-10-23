import { describe, expect, it } from 'vitest';

import {
  evaluateArtifactViewerAudit,
  exportArtifactViewerAuditJson,
} from '../ArtifactViewer';

describe('ArtifactViewer audit diagnostics (Phase P136)', () => {
  it('validates sandboxed HTML artifact viewer', () => {
    const report = evaluateArtifactViewerAudit({
      artifactId: 'art-1',
      artifactType: 'HTML',
      contentByteLength: 512,
      sandboxEnabled: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.normalizedType).toBe('html');
  });

  it('flags unsandboxed rich artifact and missing id', () => {
    const parsed = JSON.parse(
      exportArtifactViewerAuditJson({
        artifactId: '',
        artifactType: 'svg',
        contentByteLength: 0,
        sandboxEnabled: false,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('missing_artifact_id');
    expect(parsed.issueCodes).toContain('unsandboxed_rich_artifact');
  });
});
