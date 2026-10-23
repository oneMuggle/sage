import { describe, expect, it } from 'vitest';

import {
  auditOfficeDeliveryDrawerGovernance,
  formatOfficeDeliveryJson,
  formatOfficeDeliveryMarkdown,
} from '../OfficeDeliveryDrawer';

describe('OfficeDeliveryDrawer governance audit (P164)', () => {
  it('returns ready governance status for OfficeDeliveryDrawer', () => {
    const snap = auditOfficeDeliveryDrawerGovernance();
    expect(snap).toEqual({
      moduleId: 'src/features/office/OfficeDeliveryDrawer.tsx',
      phase: 'P164',
      status: 'ready',
    });
  });

  it('formats office delivery markdown and json', () => {
    const params = {
      entryId: 'e1',
      workspacePath: '/ws',
      filePath: '/ws/out.docx',
      lintState: 'ready',
      lint: null,
      decided: false,
    };
    expect(formatOfficeDeliveryMarkdown(params)).toContain('/ws/out.docx');
    expect(JSON.parse(formatOfficeDeliveryJson(params))).toMatchObject({
      entryId: 'e1',
      decided: false,
    });
  });
});
