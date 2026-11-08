/**
 * Generate-workspace API client.
 *
 * These are FastAPI HTTP routes (not IPC commands), so they go through the
 * authenticated Electron relay. Bodies are forwarded verbatim — snake_case keys.
 */

import { backendRequest } from './backendRequest';
import type {
  OfficeGenerateResult,
  OfficeIterateRequest,
  OfficeNlGenerateRequest,
  OfficeTemplateChatRequest,
} from './types';
import { handleApiError } from './utils';

async function postGenerate<TRequest>(path: string, body: TRequest): Promise<OfficeGenerateResult> {
  try {
    return await backendRequest<OfficeGenerateResult>({ path, method: 'POST', body });
  } catch (error) {
    throw handleApiError(error);
  }
}

export const officeGenerateApi = {
  generateFromNl(req: OfficeNlGenerateRequest): Promise<OfficeGenerateResult> {
    return postGenerate('/api/v1/office/generate/nl', req);
  },

  generateFromTemplateChat(req: OfficeTemplateChatRequest): Promise<OfficeGenerateResult> {
    return postGenerate('/api/v1/office/generate/template-chat', req);
  },

  iterateDocument(req: OfficeIterateRequest): Promise<OfficeGenerateResult> {
    return postGenerate('/api/v1/office/generate/iterate', req);
  },
};
