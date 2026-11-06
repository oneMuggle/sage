/**
 * Batch summary / governance helpers for useOfficeDocuments.
 *
 * Split out to keep useOfficeDocuments.ts under the file-size ratchet;
 * re-exported so existing test imports continue to resolve.
 */

export function formatOfficeDocumentsBatchSummary(result: {
  succeeded: string[];
  failed: string[];
}): string {
  return `succeeded=${result.succeeded.length} · failed=${result.failed.length}`;
}

export function formatOfficeDocumentsBatchJson(result: {
  succeeded: string[];
  failed: string[];
}): string {
  return JSON.stringify(
    {
      total: result.succeeded.length + result.failed.length,
      succeededCount: result.succeeded.length,
      failedCount: result.failed.length,
      succeeded: result.succeeded,
      failed: result.failed,
    },
    null,
    2,
  );
}

export function auditUseOfficeDocumentsGovernance(): {
  moduleId: string;
  phase: string;
  status: 'ready';
} {
  return {
    moduleId: 'src/features/office/officeDocumentsBatchFormat.ts',
    phase: 'P165',
    status: 'ready',
  };
}
