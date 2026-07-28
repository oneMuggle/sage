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
  OfficePptReadResult,
  OfficeWordReadResult,
} from '../../shared/api/types';

/** Read result union — same shape as `useOfficeDocuments.OfficeReadResult`. */
export type OfficeReadResult = OfficePptReadResult | OfficeWordReadResult | OfficeExcelReadResult;

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
interface ImportGateway {
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
  completeOfficeImport(importToken: string): Promise<void>;
  discardOfficeImport(importToken: string): Promise<void>;
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
  return officeApi.readExcel(req);
}

async function safeDiscard(gateway: ImportGateway, importToken: string): Promise<void> {
  try {
    await gateway.discardOfficeImport(importToken);
  } catch {
    // Best-effort: a failed discard just leaves the staging file on
    // disk. The next pick-and-import uses a fresh token, so the orphan
    // is bounded.
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
  try {
    const readResult = await readByType(docType, workspacePath, imported.managedPath);
    await gateway.completeOfficeImport(imported.importToken);
    return { documentId: imported.documentId, readResult };
  } catch (e) {
    await safeDiscard(gateway, imported.importToken);
    throw e;
  }
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
