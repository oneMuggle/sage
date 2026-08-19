/**
 * Sage API - Learn API (Background Review explicit trigger)
 *
 * Provides a frontend client for the POST /api/v1/learn endpoint.
 * When invoked, enqueues a review event (trigger_type="explicit_learn")
 * that the Background Review worker will process to produce skill draft
 * candidates from the current conversation.
 *
 * Backend endpoint: backend/api/legacy_routes.py (POST /learn).
 * IPC bridge: electron/commands.ts (`trigger_learn`).
 */

import { invoke } from './desktopInvoke';
import type { LearnResponse } from './types';
import { handleApiError, withRetry } from './utils';

export const learnApi = {
  /**
   * Trigger a Background Review of the given session.
   *
   * @param sessionId - The session to review (required by backend).
   * @param prompt - Optional user prompt passed as review context.
   * @returns The backend acknowledgement (`{status: "queued", message}`).
   */
  async trigger(sessionId: string, prompt: string = ''): Promise<LearnResponse> {
    return withRetry(async () => {
      try {
        return await invoke<LearnResponse>('trigger_learn', {
          session_id: sessionId,
          prompt,
        });
      } catch (error) {
        throw handleApiError(error);
      }
    });
  },
};
