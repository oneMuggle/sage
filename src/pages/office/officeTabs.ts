/**
 * Tab identifiers and URL-parameter parsing for the /office page.
 *
 * Deep links: `/office?tab=documents|generate|rules|latex`
 * and, within LaTeX: `&latex=project|templates|audit`.
 *
 * Unknown or missing values fall back to the defaults so stale bookmarks and
 * hand-edited URLs keep landing on a usable page instead of a blank tabpanel.
 */

export const OFFICE_TAB_PARAM = 'tab';
export const OFFICE_LATEX_PARAM = 'latex';

export const OFFICE_TAB_IDS = ['documents', 'generate', 'rules', 'latex'] as const;
export type OfficeTabId = (typeof OFFICE_TAB_IDS)[number];
export const DEFAULT_OFFICE_TAB: OfficeTabId = 'documents';

export const OFFICE_LATEX_TAB_IDS = ['project', 'templates', 'audit'] as const;
export type OfficeLatexTabId = (typeof OFFICE_LATEX_TAB_IDS)[number];
export const DEFAULT_OFFICE_LATEX_TAB: OfficeLatexTabId = 'project';

export function parseOfficeTab(value: string | null | undefined): OfficeTabId {
  return OFFICE_TAB_IDS.find((id) => id === value) ?? DEFAULT_OFFICE_TAB;
}

export function parseOfficeLatexTab(value: string | null | undefined): OfficeLatexTabId {
  return OFFICE_LATEX_TAB_IDS.find((id) => id === value) ?? DEFAULT_OFFICE_LATEX_TAB;
}
