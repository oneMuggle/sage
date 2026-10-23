import { useContext } from 'react';

import {
  NavHistoryContext,
  type NavHistoryContextValue,
} from '../../app/providers/NavHistoryProvider';

/**
 * Hook to access navigation history context.
 * Returns null if used outside NavHistoryProvider.
 * Use optional chaining on consumers: `navigationHistory?.back()`.
 */
export function useNavigationHistory(): NavHistoryContextValue | null {
  return useContext(NavHistoryContext);
}

export function formatNavHistorySummary(ctx?: NavHistoryContextValue | null): string {
  if (!ctx) return 'nav-history: unavailable';
  return `nav-history: canBack=${Boolean(ctx.canBack)} · canForward=${Boolean(ctx.canForward)}`;
}

export function formatNavHistoryJson(ctx?: NavHistoryContextValue | null): string {
  return JSON.stringify(
    {
      available: Boolean(ctx),
      /* v8 ignore start */
      canBack: Boolean(ctx?.canBack),
      canForward: Boolean(ctx?.canForward),
      /* v8 ignore stop */
    },
    null,
    2,
  );
}

export function auditUseNavigationHistoryGovernance(): string {
  return JSON.stringify(
    {
      schema: 'sage.shared.lib.use_navigation_history.governance.v1',
      phase: 'P180',
      unavailableSummary: formatNavHistorySummary(null),
    },
    null,
    2,
  );
}
