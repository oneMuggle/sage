import { describe, expect, it } from 'vitest';

import { auditCodeMirrorThemeEditorGovernance } from '../CodeMirrorThemeEditor';

describe('auditCodeMirrorThemeEditorGovernance (P169)', () => {
  it('returns compliant governance audit metadata for CodeMirrorThemeEditor', () => {
    const report = auditCodeMirrorThemeEditorGovernance();
    expect(report.module).toBe('src/features/theme/CodeMirrorThemeEditor.tsx');
    expect(report.phase).toBe('P169');
    expect(report.domain).toBe('theme');
    expect(report.editorHeightPx).toBe(320);
    expect(report.supportsFoldGutterAndLineNumbers).toBe(true);
    expect(report.compliant).toBe(true);
  });
});
