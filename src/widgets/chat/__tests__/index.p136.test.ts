import { describe, expect, it } from 'vitest';

import {
  evaluateChatWidgetBarrelAudit,
  exportChatWidgetBarrelAuditJson,
} from '../index';

describe('chat widget barrel audit diagnostics (Phase P136)', () => {
  it('validates complete chat widget barrel exports', () => {
    const report = evaluateChatWidgetBarrelAudit({
      exportedComponentCount: 8,
      hasComposerExport: true,
      hasMessageListExport: true,
    });
    expect(report.healthy).toBe(true);
    expect(report.issueCodes).toEqual([]);
  });

  it('flags missing core exports in chat widget barrel', () => {
    const parsed = JSON.parse(
      exportChatWidgetBarrelAuditJson({
        exportedComponentCount: 0,
        hasComposerExport: false,
        hasMessageListExport: false,
      }),
    );
    expect(parsed.healthy).toBe(false);
    expect(parsed.issueCodes).toContain('empty_chat_widget_barrel');
    expect(parsed.issueCodes).toContain('missing_composer_export');
  });
});
