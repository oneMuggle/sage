import type { OfficeDocType } from '../../shared/api/types';

/**
 * Whether fidelity mode should be ON by default for this doc type.
 * Word always (docx-preview needs no converter); Excel/PPT only when a converter exists.
 */
export function shouldDefaultFidelityOn(
  docType: OfficeDocType | undefined,
  fidelityAvailable: boolean,
): boolean {
  if (docType === 'word') return true;
  if (docType === 'excel' || docType === 'ppt') return fidelityAvailable;
  return false;
}

/**
 * Whether fidelity should be auto-loaded on mount (async conversion kickoff).
 * Word uses synchronous docx-preview, no need. Excel/PPT need soffice and
 * should kick off the conversion automatically when available.
 */
export function shouldAutoLoadFidelity(
  docType: OfficeDocType | undefined,
  fidelityAvailable: boolean,
): boolean {
  return (docType === 'excel' || docType === 'ppt') && fidelityAvailable;
}

/**
 * Resolves the initial fidelity state: explicit override wins,
 * otherwise falls back to shouldDefaultFidelityOn.
 */
export function resolveDefaultFidelity(
  docType: OfficeDocType | undefined,
  fidelityAvailable: boolean,
  override?: boolean,
): boolean {
  return override ?? shouldDefaultFidelityOn(docType, fidelityAvailable);
}
