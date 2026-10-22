import { describe, expect, it } from 'vitest';

import { auditChatRightPanelGovernance } from '../RightPanel';

describe('RightPanel P148 governance audit', () => {
  it('returns healthy defaults for RightPanel governance', () => {
    const res = auditChatRightPanelGovernance();
    expect(res.module).toBe('src/widgets/chat/RightPanel.tsx');
    expect(res.phase).toBe('P148');
    expect(res.activeSectionCount).toBe(3);
    expect(res.panelWidthPx).toBe(340);
    expect(res.healthy).toBe(true);
  });

  it('clamps panelWidthPx and checks activeSectionCount', () => {
    const res = auditChatRightPanelGovernance({
      activeSectionCount: 0,
      panelWidthPx: 1200,
    });
    expect(res.activeSectionCount).toBe(0);
    expect(res.panelWidthPx).toBe(720);
    expect(res.healthy).toBe(false);
  });
});
