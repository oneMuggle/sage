import type { OfficeDocumentSummary } from '../../shared/api/types';

type SummaryPathFields = Pick<
  OfficeDocumentSummary,
  'workspace_path' | 'doc_type' | 'id' | 'generated_filename'
>;

/** Absolute path of a managed office document, mirroring backend document_path(). */
export function officeDocumentPath(summary: SummaryPathFields): string | null {
  if (!summary.workspace_path) {
    return null;
  }
  const base = summary.workspace_path.replace(/[\\/]+$/, '');
  return `${base}/office/${summary.doc_type}/${summary.id}/${summary.generated_filename}`;
}
