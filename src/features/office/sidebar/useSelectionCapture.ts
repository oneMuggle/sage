import { useEffect } from 'react';
import type { RefObject } from 'react';

import { useOfficeWorkspaceStore } from '../../../entities/office/officeWorkspaceStore';

import { normalizeSelection } from './selectionAnchor';

export function useSelectionCapture(rootRef: RefObject<HTMLElement>): void {
  const setSelection = useOfficeWorkspaceStore((s) => s.setSelection);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    const handle = () => {
      const selection = window.getSelection();
      const normalized = normalizeSelection(root, selection);
      setSelection(normalized);
    };

    document.addEventListener('selectionchange', handle);
    return () => document.removeEventListener('selectionchange', handle);
  }, [rootRef, setSelection]);
}
