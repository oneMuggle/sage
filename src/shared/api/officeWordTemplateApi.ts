/**
 * Word template profile / fill client (M6e, §118).
 *
 * FastAPI HTTP routes reached through the authenticated Electron relay; the
 * body is forwarded verbatim (snake_case). Backend:
 * backend/api/office_word_template_profile_routes.py.
 */

import { backendRequest } from './backendRequest';
import type {
  OfficeWordTemplateFillRequest,
  OfficeWordTemplateFillResult,
  OfficeWordTemplateProfileRequest,
  OfficeWordTemplateProfileResult,
} from './types';
import { handleApiError } from './utils';

export const officeWordTemplateApi = {
  async analyzeProfile(
    req: OfficeWordTemplateProfileRequest,
  ): Promise<OfficeWordTemplateProfileResult> {
    try {
      return await backendRequest<OfficeWordTemplateProfileResult>({
        path: '/api/v1/office/word/template/profile',
        method: 'POST',
        body: req,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  async fillProfile(req: OfficeWordTemplateFillRequest): Promise<OfficeWordTemplateFillResult> {
    try {
      return await backendRequest<OfficeWordTemplateFillResult>({
        path: '/api/v1/office/word/template/profile/fill',
        method: 'POST',
        body: req,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },
};
