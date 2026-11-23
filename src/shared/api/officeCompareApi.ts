/**
 * Cross-document compare client (M6b).
 *
 * FastAPI HTTP route reached through the authenticated Electron relay; the
 * body is forwarded verbatim (snake_case). Backend: backend/office/compare.py.
 */

import { backendRequest } from './backendRequest';
import type { OfficeCompareRequest, OfficeCompareResult } from './types';
import { handleApiError } from './utils';

export const officeCompareApi = {
  async compareDocuments(req: OfficeCompareRequest): Promise<OfficeCompareResult> {
    try {
      return await backendRequest<OfficeCompareResult>({
        path: '/api/v1/office/compare',
        method: 'POST',
        body: req,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },
};
