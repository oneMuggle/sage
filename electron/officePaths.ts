/**
 * Office document path helpers (M0 Task 5, brief §Step 3).
 *
 * Pure module — no I/O, no electron imports. Exposes the sandboxing
 * primitives that `officeIpc.ts` uses to:
 *
 *   1. build the canonical managed-path layout
 *      `<workspace>/office/<docType>/<documentId>/<filename.ext>`
 *
 *   2. verify a renderer-supplied candidate path lies inside the
 *      workspace (mirrors the Python `path_safety.resolve_within`
 *      containment check, but is callable from main-process TS code
 *      WITHOUT touching the filesystem).
 *
 *   3. map each doc type to its modern dialog filter so the picker
 *      can never be coerced into a legacy `.doc`/`.xls`/`.ppt` path
 *      (or an `*` "All Files" wildcard).
 *
 * Security properties (the ones the tests assert):
 *   - No legacy extension accepted anywhere — the dialog filter catalog
 *     only ships the modern OOXML/Office Open XML extensions.
 *   - Sibling-prefix attack (`/tmp/work-evil` vs `/tmp/work`) is
 *     defeated by the `path.relative` + `path.isAbsolute` check. The
 *     string-prefix shared start gets normalized to `..` segments
 *     by `path.resolve` and the relative path then starts with `..`,
 *     which `isAbsolute` and the `!startsWith('..')` rules together
 *     reject.
 *   - Filename containing `..` is rejected before any path math runs.
 */

import path from 'path';

/** Document kind — `ppt` (presentations), `word`, or `excel`. */
export type OfficeDocType = 'ppt' | 'word' | 'excel';

/** Reference to a managed Office document inside a workspace. */
export interface OfficeManagedRef {
  /** Absolute or workspace-relative workspace directory path. */
  workspacePath: string;
  docType: OfficeDocType;
  documentId: string;
  /** Basename (no slashes, no `..`). Filename extension must match docType. */
  filename: string;
}

/** Result returned by the pick-and-import / import-dropped IPC handlers. */
export interface ImportedOfficeFile extends OfficeManagedRef {
  /** Absolute path of the staging copy inside the workspace. */
  managedPath: string;
  originalName: string;
  sizeBytes: number;
  /** Opaque token the renderer uses to call complete / discard. */
  importToken: string;
}

// ----------------------------------------------------------------------------
// Modern dialog filter catalog (Step 1 RED assertion)
// ----------------------------------------------------------------------------

export interface OfficeDialogFilter {
  /** Human-readable filter label shown by the OS dialog. */
  name: string;
  /** File extensions (no leading dot). Modern formats only. */
  extensions: string[];
}

export interface OfficeDialogFilterMap {
  ppt: OfficeDialogFilter;
  word: OfficeDialogFilter;
  excel: OfficeDialogFilter;
}

const PPTX_FILTER: OfficeDialogFilter = {
  name: 'PowerPoint Presentation (.pptx)',
  extensions: ['pptx'],
};

const DOCX_FILTER: OfficeDialogFilter = {
  name: 'Word Document (.docx)',
  extensions: ['docx'],
};

const XLSX_FILTER: OfficeDialogFilter = {
  name: 'Excel Workbook (.xlsx)',
  extensions: ['xlsx'],
};

/**
 * Returns the dialog filter catalog for each Office doc type.
 *
 * Security rationale: every filter maps to exactly one OOXML extension
 * (`.pptx` / `.docx` / `.xlsx`). The legacy binary formats
 * (`.ppt`/`.doc`/`.xls`) are deliberately excluded — Sage cannot parse
 * them and a renderer that hand-rolls an `ipcRenderer.invoke` with a
 * legacy path must be rejected before any disk operation.
 *
 * No `All Files` / `*` wildcard entry is provided; an `*` filter would
 * downgrade the dialog's safety surface to "any file on disk".
 */
export function getOpenDialogFilters(): OfficeDialogFilterMap {
  return {
    ppt: PPTX_FILTER,
    word: DOCX_FILTER,
    excel: XLSX_FILTER,
  };
}

// ----------------------------------------------------------------------------
// Document-id policy (shared with backend `path_safety._validate_doc_id`)
// ----------------------------------------------------------------------------

/**
 * Re-use the same regex the backend enforces (`backend/office/path_safety.py`):
 *   ^[a-zA-Z0-9_-]{1,64}$
 * which already protects against:
 *   - path separators (`/`, `\`) — never allowed
 *   - parent traversal (`..`) — never matched
 *   - shell metacharacters — outside the character class
 *   - excessive length — bounded at 64 chars
 */
const DOC_ID_PATTERN = /^[a-zA-Z0-9_-]{1,64}$/;

/**
 * Per-doc-type canonical lowercase extension.
 *
 * Mirrors backend/office/path_safety._DOC_TYPE_EXTENSIONS so the
 * Electron main process and the FastAPI backend agree on the
 * filename ↔ docType mapping.
 */
const DOC_TYPE_EXTENSION: Record<OfficeDocType, string> = {
  ppt: 'pptx',
  word: 'docx',
  excel: 'xlsx',
};

function assertSafeDocId(documentId: string): void {
  if (!DOC_ID_PATTERN.test(documentId)) {
    throw new Error(
      `documentId contains unsafe characters (must match ${DOC_ID_PATTERN}): ${JSON.stringify(
        documentId,
      )}`,
    );
  }
}

function assertSafeFilename(filename: string, docType: OfficeDocType): void {
  if (typeof filename !== 'string' || filename.length === 0) {
    throw new Error(`filename must be a non-empty string`);
  }
  if (filename.includes('/') || filename.includes('\\')) {
    throw new Error(`filename contains path separator: ${JSON.stringify(filename)}`);
  }
  if (filename.includes('..')) {
    throw new Error(`filename contains '..' segment: ${JSON.stringify(filename)}`);
  }

  const expectedExt = DOC_TYPE_EXTENSION[docType];
  const lowered = filename.toLowerCase();
  if (lowered.endsWith(`.${expectedExt}`)) {
    return;
  }
  // Accept no-extension filenames by auto-appending. Reject anything
  // else — never silently rewrite a wrong extension.
  const lastDot = lowered.lastIndexOf('.');
  if (lastDot >= 0 && lastDot < lowered.length - 1) {
    const actualExt = lowered.slice(lastDot + 1);
    throw new Error(
      `filename extension ${JSON.stringify(actualExt)} does not match doc type ${docType} (expected ${expectedExt}): ${JSON.stringify(filename)}`,
    );
  }
}

// ----------------------------------------------------------------------------
// Public path helpers
// ----------------------------------------------------------------------------

/**
 * Build the canonical managed-path for an Office document reference.
 *
 *   <workspace>/office/<docType>/<documentId>/<filename.ext>
 *
 * Both `workspacePath` and `filename` are validated BEFORE any path
 * resolution happens:
 *   - `documentId` must match the safe-id regex (no `..`, no slashes)
 *   - `filename` must be a basename (no separators, no `..`) carrying
 *     the docType-canonical extension (or no extension at all, which
 *     is auto-appended)
 *
 * The returned string is the result of `path.resolve(...)` — fully
 * canonicalized, OS-appropriate separators, ready for IPC.
 */
export function buildManagedPath(ref: OfficeManagedRef): string {
  assertSafeDocId(ref.documentId);
  assertSafeFilename(ref.filename, ref.docType);
  if (typeof ref.workspacePath !== 'string' || ref.workspacePath.length === 0) {
    throw new Error(`workspacePath must be a non-empty string`);
  }
  const expectedExt = DOC_TYPE_EXTENSION[ref.docType];
  let filename = ref.filename;
  if (!filename.toLowerCase().endsWith(`.${expectedExt}`)) {
    filename = `${filename}.${expectedExt}`;
  }
  // path.join treats both POSIX and Windows separators per host
  // platform; path.resolve canonicalizes the result.
  const joined = path.join(ref.workspacePath, 'office', ref.docType, ref.documentId, filename);
  return path.resolve(joined);
}

/**
 * Return `true` iff `targetPath` lies within `workspacePath`.
 *
 * Implementation note (mirrors `backend/office/path_safety.is_within`):
 *
 *   1. `path.resolve` both arguments first. This collapses `..`
 *      segments and normalizes `/./` to `/`. Done as strings we get
 *      `..` segments preserved verbatim — the string form is what we
 *      diff, not the file system view.
 *   2. Compute `path.relative(workspace, target)`. Per Node docs:
 *      - If `target === workspace`, the result is `''`.
 *      - If `target` is inside `workspace`, the result never starts
 *        with `..` and is not absolute.
 *      - If `target` is outside (including sibling-prefix
 *        `/tmp/work-evil` vs `/tmp/work`), the result either starts
 *        with `..` or is absolute (when on a different drive letter
 *        on Windows).
 *   3. The check below covers all three cases without string-prefix
 *      comparison.
 *
 * This helper intentionally does **not** touch the filesystem (no
 * `fs.existsSync`, no `realpathSync`). It is callable on guaranteed
 * synthetic paths in the test suite and on empty / not-yet-created
 * workspaces during the import workflow.
 */
export function isPathWithinWorkspace(workspacePath: string, targetPath: string): boolean {
  if (!workspacePath || !targetPath) return false;
  const resolvedWorkspace = path.resolve(workspacePath);
  const resolvedTarget = path.resolve(targetPath);
  const relative = path.relative(resolvedWorkspace, resolvedTarget);
  if (relative === '') return true;
  if (relative.startsWith('..')) return false;
  if (path.isAbsolute(relative)) return false;
  return true;
}

/**
 * Extension associated with a given docType (canonical lowercase, no
 * leading dot). Useful for IPC handlers that need to confirm a filename
 * without pulling in the helper graph above.
 */
export function extensionForDocType(docType: OfficeDocType): string {
  return DOC_TYPE_EXTENSION[docType];
}
