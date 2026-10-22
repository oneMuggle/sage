import { describe, expect, it } from 'vitest';

import { evaluateDeliveryDrawerHostGovernanceAudit } from '../DeliveryDrawerHost';

describe('evaluateDeliveryDrawerHostGovernanceAudit (Phase P140)', () => {
  it('returns healthy report when delivery drawer host has session and close callback', () => {
    const report = evaluateDeliveryDrawerHostGovernanceAudit({
      isOpen: true,
      activeSessionId: 'sess-delivery-42',
      deliverableCount: 4,
      hasCloseCallback: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.normalizedSessionId).toBe('sess-delivery-42');
    expect(report.normalizedDeliverableCount).toBe(4);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags missing session when open, negative count, and missing close callback', () => {
    const report = evaluateDeliveryDrawerHostGovernanceAudit({
      isOpen: true,
      activeSessionId: '   ',
      deliverableCount: -1,
      hasCloseCallback: false,
    });
    expect(report.healthy).toBe(false);
    expect(report.issueCodes).toEqual([
      'DELIVERY_DRAWER_HOST_SESSION_MISSING',
      'DELIVERY_DRAWER_HOST_COUNT_NEGATIVE',
      'DELIVERY_DRAWER_HOST_CLOSE_CALLBACK_MISSING',
    ]);
  });
});
