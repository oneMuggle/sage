/**
 * Tab identifiers and URL-parameter parsing for the /office page.
 *
 * Deep links: `/office?tab=documents|generate`
 *
 * Unknown or missing values fall back to the defaults so stale bookmarks and
 * hand-edited URLs keep landing on a usable page instead of a blank tabpanel.
 *
 * win7 note: main ships four task domains (documents / generate / rules /
 * latex), but the LaTeX feature stack (backend `office_latex_routes` + seven
 * LaTeX panels) and the Word rule-extraction / batch-audit panels have not
 * been synced to release/win7 yet. Only the two domains that actually have
 * working features here are exposed; the other two tabs come back with their
 * feature syncs.
 */

import { useEffect, useState } from 'react';

export const OFFICE_TAB_PARAM = 'tab';

export const OFFICE_TAB_IDS = ['documents', 'generate'] as const;
export type OfficeTabId = (typeof OFFICE_TAB_IDS)[number];
export const DEFAULT_OFFICE_TAB: OfficeTabId = 'documents';

export function parseOfficeTab(value: string | null | undefined): OfficeTabId {
  return OFFICE_TAB_IDS.find((id) => id === value) ?? DEFAULT_OFFICE_TAB;
}

/**
 * Lazy-mount + keep-alive helper for Radix `forceMount` tabs.
 *
 * Returns the list of tab ids whose content must be mounted into the DOM:
 * starts with the initial `active`, grows as new tabs are visited, and never
 * drops entries — switching back to a previously visited tab keeps its panel
 * DOM node (and therefore local state) intact.
 *
 * The derived `active in result` check prevents a one-frame blank when the
 * active id changes mid-render (before the effect fires).
 */
export function useKeepAliveTabs<T extends string>(active: T): readonly T[] {
  const [mounted, setMounted] = useState<readonly T[]>([active]);
  useEffect(() => {
    setMounted((prev) => (prev.includes(active) ? prev : [...prev, active]));
  }, [active]);
  return mounted.includes(active) ? mounted : [...mounted, active];
}
