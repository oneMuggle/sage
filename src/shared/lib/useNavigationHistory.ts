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
