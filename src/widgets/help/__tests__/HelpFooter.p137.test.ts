import { describe, expect, it } from 'vitest';

import { evaluateHelpFooterGovernanceAudit } from '../HelpFooter';

describe('evaluateHelpFooterGovernanceAudit (Phase P137)', () => {
  it('returns healthy report when all help footer external links use https and noopener', () => {
    const report = evaluateHelpFooterGovernanceAudit({
      externalUrls: [
        'https://github.com/oneMuggle/sage/tree/main/docs/user-manual',
        'https://github.com/oneMuggle/sage/issues/new',
        'https://github.com/oneMuggle/sage',
      ],
      allLinksHaveNoopener: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.validHttpsLinkCount).toBe(3);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags empty or insecure links and missing noopener attribute', () => {
    const report = evaluateHelpFooterGovernanceAudit({
      externalUrls: ['http://example.com/docs'],
      allLinksHaveNoopener: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'HELP_FOOTER_INSECURE_EXTERNAL_URL',
      'HELP_FOOTER_NOOPENER_MISSING',
    ]);
  });
});
