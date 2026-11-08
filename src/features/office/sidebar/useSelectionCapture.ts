import { useEffect } from 'react';
import type { RefObject } from 'react';

import { useOfficeWorkspaceStore } from '../../../entities/office/officeWorkspaceStore';

import { normalizeSelection } from './selectionAnchor';

export function useSelectionCapture(rootRef: RefObject<HTMLElement>): void {
  const setSelection = useOfficeWorkspaceStore((s) => s.setSelection);

  useEffect(() => {
    const handle = () => {
      const root = rootRef.current;
      if (!root) return;
      const normalized = normalizeSelection(root, window.getSelection());
      setSelection(normalized);
    };

    document.addEventListener('selectionchange', handle);
    return () => document.removeEventListener('selectionchange', handle);
  }, [rootRef, setSelection]);
}
