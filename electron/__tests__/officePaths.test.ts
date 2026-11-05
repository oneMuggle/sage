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

import path from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  buildManagedPath,
  docTypeFromExtension,
  getAllOpenDialogFilters,
  getOpenDialogFilters,
  isPathWithinWorkspace,
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
  it('joins workspace + office + docType + id + filename with a root-relative workspace', () => {
    const p = buildManagedPath(REF_PPT);
    // A root-relative path also acquires the current drive on Windows.
    expect(p.replace(/\\/g, '/')).toBe(
      path.resolve('/workspace/office/ppt/doc-001/deck.pptx').replace(/\\/g, '/'),
    );
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
    expect(isPathWithinWorkspace('/tmp/workspace', '/tmp/workspace-evil/payload.pptx')).toBe(false);
  });

  it('accepts valid paths inside the workspace', () => {
    expect(isPathWithinWorkspace('/tmp/workspace', '/tmp/workspace/office/ppt/d/file.pptx')).toBe(
      true,
    );
  });

  it('rejects absolute paths that escape the workspace', () => {
    expect(isPathWithinWorkspace('/tmp/workspace', '/etc/passwd')).toBe(false);
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

describe('dialog filter catalog (modern + legacy, P1-C)', () => {
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

  it('includes legacy counterparts per doc type (P1-C: converted on import)', () => {
    const filters = getOpenDialogFilters();
    expect(filters.ppt.extensions).toContain('ppt');
    expect(filters.word.extensions).toContain('doc');
    expect(filters.excel.extensions).toContain('xls');
    // pdf 没有 legacy 对应物
    expect(filters.pdf.extensions).toEqual(['pdf']);
  });

  it('maps ppt filter to modern + legacy extensions', () => {
    const filters = getOpenDialogFilters();
    expect(filters.ppt.extensions).toEqual(['pptx', 'ppt']);
  });

  it('maps word filter to modern + legacy extensions', () => {
    const filters = getOpenDialogFilters();
    expect(filters.word.extensions).toEqual(['docx', 'doc']);
  });

  it('maps excel filter to modern + legacy extensions', () => {
    const filters = getOpenDialogFilters();
    expect(filters.excel.extensions).toEqual(['xlsx', 'xls']);
  });
});

describe('docTypeFromExtension (Phase 0 unified intake)', () => {
  it('maps modern OOXML extensions to their docType', () => {
    expect(docTypeFromExtension('report.docx')).toBe('word');
    expect(docTypeFromExtension('deck.pptx')).toBe('ppt');
    expect(docTypeFromExtension('budget.xlsx')).toBe('excel');
    expect(docTypeFromExtension('scan.pdf')).toBe('pdf');
  });

  it('is case-insensitive', () => {
    expect(docTypeFromExtension('Report.DOCX')).toBe('word');
    expect(docTypeFromExtension('DECK.Pptx')).toBe('ppt');
  });

  it('maps legacy binary extensions to the same docType (P1-C)', () => {
    expect(docTypeFromExtension('old.doc')).toBe('word');
    expect(docTypeFromExtension('old.xls')).toBe('excel');
    expect(docTypeFromExtension('old.ppt')).toBe('ppt');
  });

  it('maps extra allowed extensions (.csv → excel)', () => {
    expect(docTypeFromExtension('data.csv')).toBe('excel');
  });

  it('accepts a bare extension without a filename', () => {
    expect(docTypeFromExtension('docx')).toBe('word');
    expect(docTypeFromExtension('.docx')).toBe('word');
  });

  it('returns null for unrecognised extensions', () => {
    expect(docTypeFromExtension('readme.txt')).toBeNull();
    expect(docTypeFromExtension('image.png')).toBeNull();
    expect(docTypeFromExtension('archive.zip')).toBeNull();
    expect(docTypeFromExtension('noextension')).toBeNull();
  });

  it('returns null for empty / whitespace input', () => {
    expect(docTypeFromExtension('')).toBeNull();
    expect(docTypeFromExtension('   ')).toBeNull();
  });

  it('handles filenames with multiple dots (uses last extension)', () => {
    expect(docTypeFromExtension('archive.2026.11.final.docx')).toBe('word');
    expect(docTypeFromExtension('weird..docx')).toBe('word');
  });
});

describe('getAllOpenDialogFilters (Phase 0 unified intake)', () => {
  it('returns a combined "Office 文档" entry as the first filter', () => {
    const all = getAllOpenDialogFilters();
    expect(all.length).toBeGreaterThanOrEqual(1);
    const combined = all[0]!;
    expect(combined.name).toContain('Office 文档');
    // Combined entry must include modern + legacy + extra extensions.
    for (const ext of ['pptx', 'docx', 'xlsx', 'pdf', 'ppt', 'doc', 'xls', 'csv']) {
      expect(combined.extensions, `missing ${ext}`).toContain(ext);
    }
  });

  it('does not list "*" wildcard filter (security: dialog must not allow arbitrary extensions)', () => {
    const all = getAllOpenDialogFilters();
    for (const f of all) {
      const extensionsJoined = f.extensions.join(',');
      expect(extensionsJoined, f.name).not.toContain('*');
    }
  });

  it('also exposes the per-type entries after the combined one', () => {
    const all = getAllOpenDialogFilters();
    // first is combined; remaining 4 are per-type
    expect(all.length).toBe(5);
    const names = all.slice(1).map((f) => f.name);
    expect(names.some((n) => n.includes('Word'))).toBe(true);
    expect(names.some((n) => n.includes('PowerPoint'))).toBe(true);
    expect(names.some((n) => n.includes('Excel'))).toBe(true);
    expect(names.some((n) => n.includes('PDF'))).toBe(true);
  });
});
