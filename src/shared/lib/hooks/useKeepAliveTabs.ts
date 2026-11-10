/**
 * useKeepAliveTabs — lazy-mount + keep-alive helper for Radix `forceMount` tabs.
 *
 * Returns the list of tab ids whose content must be mounted into the DOM:
 * starts with the initial `active`, grows as new tabs are visited, and never
 * drops entries — switching back to a previously visited tab keeps its panel
 * DOM node (and therefore local state) intact.
 *
 * The derived `active in result` check prevents a one-frame blank when the
 * active id changes mid-render (before the effect fires).
 *
 * Lives in `shared/lib/hooks` because both `pages/` (the Office top-level
 * tabs, the LaTeX sub-tabs) and `features/` (the rules sub-tabs) need it —
 * a page-local module could not be imported from `features/` without
 * inverting the layering.
 */

import { useEffect, useState } from 'react';

export function useKeepAliveTabs<T extends string>(active: T): readonly T[] {
  const [mounted, setMounted] = useState<readonly T[]>([active]);
  useEffect(() => {
    setMounted((prev) => (prev.includes(active) ? prev : [...prev, active]));
  }, [active]);
  return mounted.includes(active) ? mounted : [...mounted, active];
}
