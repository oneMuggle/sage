/**
 * RED tests for electron/officePaths.ts (M0 Task 5, brief §Step 1).
 *
 * Asserts the pure path/filename helpers and the modern-format dialog
 * filter catalog. The actual implementation is expected to live in
 * `electron/officePaths.ts` (created in Step 3) — these tests fail
 * with `Cannot find module` until then.
 *
 * Scope:
 *   - buildManagedPath builds `<workspace>/office/<docType>/<id>/<file>`
 *     - on POSIX and Windows path flavors
 *     - rejecting sibling-prefix (`/tmp/work-evil` vs `/tmp/work`)
 *     - rejecting `..` traversal
 *   - isPathWithinWorkspace mirrors buildManagedPath's containment check
 *   - the dialog filter catalog maps each doc type to exactly one
 *     extension AND excludes legacy + "All Files" entries
 */

import { describe, expect, it } from 'vitest';
import {
  buildManagedPath,
  isPathWithinWorkspace,
  getOpenDialogFilters,
} from '../officePaths';

const REF_PPT = {
  workspacePath: '/workspace',
  docType: 'ppt' as const,
  documentId: 'doc-001',
  filename: 'deck.pptx',
};

const REF_WORD = {
  workspacePath: '/workspace',
  docType: 'word' as const,
  documentId: 'doc-002',
  filename: 'report.docx',
};

const REF_EXCEL = {
  workspacePath: '/workspace',
  docType: 'excel' as const,
  documentId: 'doc-003',
  filename: 'sheet.xlsx',
};

describe('buildManagedPath', () => {
  it('joins workspace + office + docType + id + filename on POSIX', () => {
    const p = buildManagedPath(REF_PPT);
    // Path joining on POSIX: workspace/office/ppt/doc-001/deck.pptx
    expect(p.replace(/\\/g, '/')).toBe('/workspace/office/ppt/doc-001/deck.pptx');
  });

  it('joins workspace + office + docType + id + filename with Windows-style workspace', () => {
    // Pass a Windows-style workspace path and assert the joined result
    // contains the expected segments regardless of host platform. The
    // real cross-platform guarantee comes from isPathWithinWorkspace.
    const windowsRef = {
      ...REF_WORD,
      workspacePath: 'C:/work/alpha',
    };
    const p = buildManagedPath(windowsRef);
    expect(p.replace(/\\/g, '/').toLowerCase()).toContain(
      '/work/alpha/office/word/doc-002/report.docx',
    );
  });

  it('rejects workspace traversal via .. segment in filename', () => {
    expect(() =>
      buildManagedPath({
        ...REF_PPT,
        filename: '../escape.pptx',
      }),
    ).toThrow();
  });

  it('rejects sibling-prefix attempts that share workspace string prefix', () => {
    // The runtime check that backs buildManagedPath internally — a
    // candidate path that starts with the workspace's *string* prefix
    // but lives outside it must NOT be accepted by isPathWithinWorkspace.
    expect(
      isPathWithinWorkspace('/tmp/workspace', '/tmp/workspace-evil/payload.pptx'),
    ).toBe(false);
  });

  it('accepts valid paths inside the workspace', () => {
    expect(
      isPathWithinWorkspace('/tmp/workspace', '/tmp/workspace/office/ppt/d/file.pptx'),
    ).toBe(true);
  });

  it('rejects absolute paths that escape the workspace', () => {
    expect(
      isPathWithinWorkspace('/tmp/workspace', '/etc/passwd'),
    ).toBe(false);
  });

  it('rejects reversed-prefix escapes via .. segments', () => {
    // /tmp/workspace/../etc starts with "/tmp/workspace" but escapes it.
    // The brief's relative+isAbsolute check (Step 3 implementation)
    // catches this; we assert the *property* here.
    expect(isPathWithinWorkspace('/tmp/workspace', '/tmp/workspace/../etc/passwd')).toBe(false);
  });
});

describe('extension mapping per doc type', () => {
  it('maps each doc type to exactly one modern extension', () => {
    const cases: Array<{
      ref: typeof REF_PPT | typeof REF_WORD | typeof REF_EXCEL;
      expectedExt: string;
    }> = [
      { ref: REF_PPT, expectedExt: 'pptx' },
      { ref: REF_WORD, expectedExt: 'docx' },
      { ref: REF_EXCEL, expectedExt: 'xlsx' },
    ];
    for (const { ref, expectedExt } of cases) {
      const built = buildManagedPath(ref).replace(/\\/g, '/');
      expect(built.endsWith(`.${expectedExt}`)).toBe(true);
    }
  });
});

describe('dialog filter catalog (modern formats only)', () => {
  it('returns a filter entry for every doc type', () => {
    const filters = getOpenDialogFilters();
    expect(filters.ppt).toBeDefined();
    expect(filters.word).toBeDefined();
    expect(filters.excel).toBeDefined();
  });

  it('does not list "*" wildcard filter (security: dialog must not allow arbitrary extensions)', () => {
    const filters = getOpenDialogFilters();
    const all = Object.values(filters);
    for (const f of all) {
      const extensionsJoined = f.extensions.join(',');
      expect(extensionsJoined, f.name).not.toContain('*');
    }
  });

  it('does not include legacy extensions (.doc, .xls, .ppt)', () => {
    const filters = getOpenDialogFilters();
    for (const f of Object.values(filters)) {
      for (const ext of f.extensions) {
        expect(ext, `${f.name} includes legacy ${ext}`).not.toBe('doc');
        expect(ext, `${f.name} includes legacy ${ext}`).not.toBe('xls');
        expect(ext, `${f.name} includes legacy ${ext}`).not.toBe('ppt');
      }
    }
  });

  it('maps ppt filter to only the modern .pptx extension', () => {
    const filters = getOpenDialogFilters();
    expect(filters.ppt.extensions).toEqual(['pptx']);
  });

  it('maps word filter to only the modern .docx extension', () => {
    const filters = getOpenDialogFilters();
    expect(filters.word.extensions).toEqual(['docx']);
  });

  it('maps excel filter to only the modern .xlsx extension', () => {
    const filters = getOpenDialogFilters();
    expect(filters.excel.extensions).toEqual(['xlsx']);
  });
});
