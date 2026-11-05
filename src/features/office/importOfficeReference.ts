/**
 * importOfficeReference — Task 7 (2026-07-26)
 *
 * Shared lifecycle helper for the office "import → read → finalize-or-discard"
 * flow. Used by two call sites:
 *
 *   1. `useOfficeDocuments.readDropped` (/office page): needs the parsed
 *      read result for preview. The returned `documentId` is unused but
 *      still useful for callers that need to record the doc (e.g. the
 *      page already adds it via `findDocument`).
 *
 *   2. `ChatInput` (chat-read path): receives a `FileSearchResult` from
 *      the `@`-menu, converts it to a `ChatOfficeRef` via this helper.
 *      The parsed read result is discarded — chat-read loads summaries
 *      server-side via `chat_refs.py` (PR-#210).
 *
 * Flow:
 *   1. `electron.office.importDroppedOfficeFile(workspacePath, docType, sourcePath)`
 *      → atomic copy into the managed directory → `{ managedPath, importToken, ... }`.
 *   2. `officeApi.read{Ppt|Word|Excel}` over the managed path → triggers
 *      the backend parser. The result is returned to the caller; the
 *      helper itself only uses the rejection to drive discard.
 *   3. On success → `electron.office.completeOfficeImport(importToken)`.
 *      The staged file becomes permanent.
 *   4. On error → `electron.office.discardOfficeImport(importToken)` (best
 *      effort). Re-throw the original error so the caller can show a
 *      user-facing message.
 *
 * The function is the **only** place that owns this lifecycle. Both
 * call sites delegate here to keep the token lifecycle in lock-step.
 */

import type { FileSearchResult } from '../../shared/api/fileSearchClient';
import { officeApi } from '../../shared/api/officeApi';
import type {
  ChatOfficeRef,
  OfficeDocType,
  OfficeExcelReadResult,
  OfficePdfReadResult,
  OfficePptReadResult,
  OfficeWordReadResult,
} from '../../shared/api/types';

/** P1-C: legacy extensions that go through staged in-place conversion. */
const LEGACY_EXTENSIONS = new Set(['doc', 'xls', 'ppt']);

/** Read result union — same shape as `useOfficeDocuments.OfficeReadResult`. */
export type OfficeReadResult =
  | OfficePptReadResult
  | OfficeWordReadResult
  | OfficeExcelReadResult
  | OfficePdfReadResult;

/** Result returned by `importOfficeReference`. */
export interface ImportOfficeReferenceResult {
  /** Managed docId (from the gateway's `documentId`). */
  documentId: string;
  /** Parsed read result — chat callers discard this; /office callers use it. */
  readResult: OfficeReadResult;
}

/**
 * Minimal shape we read off `window.electronAPI.office`. The full bridge
 * type lives in `shared/types/electron-api.d.ts`; we re-declare here to
 * keep this helper independent of that ambient declaration and easier
 * to mock from tests.
 */
export interface StagedOfficeGateway {
  completeOfficeImport(importToken: string): Promise<void>;
  discardOfficeImport(importToken: string): Promise<void>;
}

export interface ImportGateway extends StagedOfficeGateway {
  importDroppedOfficeFile(
    workspacePath: string,
    docType: OfficeDocType,
    sourcePath: string,
  ): Promise<{
    documentId: string;
    importToken: string;
    managedPath: string;
    originalName: string;
    filename: string;
    workspacePath: string;
    docType: OfficeDocType;
  }>;
}

/**
 * A file that has ALREADY been staged into the managed directory by the
 * Electron gateway.
 *
 * `docType` is resolved by the main process (extension → docType), so
 * callers never re-derive it from the filename — the mapping table
 * lives in exactly one place (`electron/officePaths.docTypeFromExtension`).
 */
export interface StagedOfficeFile {
  documentId: string;
  importToken: string;
  managedPath: string;
  docType: OfficeDocType;
  /** Original filename (before the managed-path copy) — for display. */
  originalName?: string;
}

/**
 * Type guard: a `FileSearchResult` is "importable" when it represents an
 * office doc that lives outside the managed directory. Plain files are
 * never importable through this helper.
 */
export function isImportableOfficeResult(result: FileSearchResult): boolean {
  if (result.kind === 'file') return false;
  if (!result.docType) return false;
  // managed office docs already have a docId — caller should pick the
  // managed-ref path, not the import path.
  if (result.docId) return false;
  return Boolean(result.sourcePath);
}

async function readByType(
  docType: OfficeDocType,
  workspacePath: string,
  managedPath: string,
): Promise<OfficeReadResult> {
  const req = { workspace_path: workspacePath, file_path: managedPath };
  if (docType === 'ppt') {
    return officeApi.readPpt(req);
  }
  if (docType === 'word') {
    return officeApi.readWord(req);
  }
  if (docType === 'pdf') {
    // PdfReadRequest is extra="forbid" — only the two path fields.
    return officeApi.readPdf({ workspace_path: workspacePath, file_path: managedPath });
  }
  return officeApi.readExcel(req);
}

async function safeDiscard(gateway: StagedOfficeGateway, importToken: string): Promise<void> {
  try {
    await gateway.discardOfficeImport(importToken);
  } catch {
    // Best-effort: a failed discard just leaves the staging file on
    // disk. The next pick-and-import uses a fresh token, so the orphan
    // is bounded.
  }
}

/**
 * Finish the import lifecycle for an ALREADY-STAGED file:
 *
 *   1. P1-C: legacy `.doc`/`.xls`/`.ppt` are staged as-is → convert them
 *      in place to the modern format before reading.
 *   2. Read the (converted) managed file through the type-specific
 *      backend parser.
 *   3. On success → `completeOfficeImport(importToken)` (the staged file
 *      becomes permanent). On any failure → `discardOfficeImport(importToken)`
 *      (best effort) and re-throw so the caller can surface a message.
 *
 * This is the single owner of the "staged → readable → finalized" tail.
 * Both the single-file path (`importOfficeByType`) and the unified
 * multi-file path (`useOfficeDocuments.importAndReadMulti`) route through
 * it, so the token lifecycle cannot drift between them.
 */
export async function readStagedOfficeFile(
  gateway: StagedOfficeGateway,
  workspacePath: string,
  staged: StagedOfficeFile,
): Promise<ImportOfficeReferenceResult> {
  try {
    let managedPath = staged.managedPath;
    const stagedExt = managedPath.slice(managedPath.lastIndexOf('.') + 1).toLowerCase();
    if (LEGACY_EXTENSIONS.has(stagedExt)) {
      const converted = await officeApi.convertLegacyImport({
        workspace_path: workspacePath,
        file_path: managedPath,
      });
      if (!converted.ok || !converted.converted_path) {
        throw new Error(converted.error ?? 'legacy import conversion failed');
      }
      managedPath = converted.converted_path;
    }
    const readResult = await readByType(staged.docType, workspacePath, managedPath);
    await gateway.completeOfficeImport(staged.importToken);
    return { documentId: staged.documentId, readResult };
  } catch (e) {
    await safeDiscard(gateway, staged.importToken);
    throw e;
  }
}

/**
 * Low-level helper that takes the docType + sourcePath directly. Used by
 * `useOfficeDocuments.readDropped` (which has these as separate args).
 */
export async function importOfficeByType(
  workspacePath: string,
  docType: OfficeDocType,
  sourcePath: string,
): Promise<ImportOfficeReferenceResult> {
  const gateway = (window as unknown as { electronAPI?: { office?: ImportGateway } }).electronAPI
    ?.office;
  if (!gateway) {
    throw new Error('importOfficeReference: electron.office bridge unavailable');
  }

  const imported = await gateway.importDroppedOfficeFile(workspacePath, docType, sourcePath);
  return readStagedOfficeFile(gateway, workspacePath, {
    documentId: imported.documentId,
    importToken: imported.importToken,
    managedPath: imported.managedPath,
    docType,
    originalName: imported.originalName,
  });
}

/**
 * Chat-side helper: takes a `FileSearchResult` from the @-menu and returns
 * a `ChatOfficeRef`. Discards the read result (server-side loads it).
 *
 * Throws on:
 * - missing sourcePath (programmer error — caller must filter first)
 * - missing docType (programmer error — caller must filter first)
 * - gateway import / read / complete failures (with discard already
 *   attempted; caller should show a user-facing error)
 */
export async function importOfficeReference(
  workspacePath: string,
  result: FileSearchResult,
): Promise<ChatOfficeRef> {
  if (!result.docType) {
    throw new Error('importOfficeReference: missing docType on result');
  }
  if (!result.sourcePath) {
    throw new Error('importOfficeReference: missing sourcePath on result');
  }
  const { documentId } = await importOfficeByType(workspacePath, result.docType, result.sourcePath);
  return {
    docId: documentId,
    docType: result.docType,
    filename: result.name,
  };
}

export function formatOfficeImportRefSummary(ref: ChatOfficeRef): string {
  return `${ref.docId} · ${ref.docType} · ${ref.filename}`;
}

export function formatOfficeImportRefJson(ref: ChatOfficeRef): string {
  return JSON.stringify(
    {
      docId: ref.docId,
      docType: ref.docType,
      filename: ref.filename,
    },
    null,
    2,
  );
}

export function auditImportOfficeReferenceGovernance(): {
  moduleId: string;
  phase: string;
  status: 'ready';
} {
  return {
    moduleId: 'src/features/office/importOfficeReference.ts',
    phase: 'P165',
    status: 'ready',
  };
}
