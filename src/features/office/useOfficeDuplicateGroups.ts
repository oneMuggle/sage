/**
 * Advisory duplicate-group loading for the office document list
 * (Phase 1 Item A: 文档库重复清理).
 *
 * Split out of useOfficeDocuments.ts to keep that hook under the
 * file-size ratchet, and to make the failure isolation explicit: a
 * grouping error hides the "重复" badge but must never clear the
 * document list.
 */

import { useCallback, useRef, useState } from 'react';

import { officeDedupApi } from '../../shared/api/officeDedupApi';
import type { OfficeDuplicateGroup } from '../../shared/api/officeDuplicateTypes';

export interface UseOfficeDuplicateGroupsResult {
  duplicateGroups: OfficeDuplicateGroup[];
  /** Refetch advisory grouping. Never throws. */
  reload: () => Promise<void>;
  /** Drop groups immediately (workspace switch, archived view). */
  clear: () => void;
}

export function useOfficeDuplicateGroups(
  workspacePath: string | null,
  live: boolean,
): UseOfficeDuplicateGroupsResult {
  const [duplicateGroups, setDuplicateGroups] = useState<OfficeDuplicateGroup[]>([]);
  // Discards responses that land after a workspace/view switch.
  const seqRef = useRef(0);

  const reload = useCallback(async (): Promise<void> => {
    const seq = ++seqRef.current;
    if (!workspacePath || !live) {
      setDuplicateGroups([]);
      return;
    }
    try {
      const result = await officeDedupApi.listDuplicateGroups(workspacePath);
      if (seq === seqRef.current) setDuplicateGroups(result.groups);
    } catch {
      if (seq === seqRef.current) setDuplicateGroups([]);
    }
  }, [workspacePath, live]);

  const clear = useCallback(() => {
    seqRef.current += 1;
    setDuplicateGroups([]);
  }, []);

  return { duplicateGroups, reload, clear };
}
