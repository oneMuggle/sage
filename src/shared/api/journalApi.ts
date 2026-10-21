/**
 * Journal template API client (Task 7, 2026-09-10).
 * Mirrors src/shared/api/officeApi.ts — thin wrapper over IPC bridge.
 * Backend: backend/api/office_routes.py (5 endpoints under /api/v1/office/journal/*).
 */
import { invoke } from './desktopInvoke';
import type {
  JournalFillFromContentRequest,
  JournalFillFromContentResponse,
  JournalGetSpecResponse,
  JournalListSpecsResponse,
  JournalParseTemplateResponse,
  JournalValidateResponse,
} from './types';
import { handleApiError } from './utils';


export const journalApi = {
  async parseTemplate(filePath: string): Promise<JournalParseTemplateResponse> {
    try {
      return await invoke<JournalParseTemplateResponse>('office_journal_parse_template', {
        file_path: filePath,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  async listSpecs(): Promise<JournalListSpecsResponse> {
    try {
      return await invoke<JournalListSpecsResponse>('office_journal_list_specs', {});
    } catch (error) {
      throw handleApiError(error);
    }
  },

  async getSpec(specId: string): Promise<JournalGetSpecResponse> {
    try {
      return await invoke<JournalGetSpecResponse>('office_journal_get_spec', {
        spec_id: specId,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },

  async validate(args: { spec_id?: string; file_path?: string }): Promise<JournalValidateResponse> {
    try {
      return await invoke<JournalValidateResponse>('office_journal_validate', args);
    } catch (error) {
      throw handleApiError(error);
    }
  },

  async fillFromContent(
    req: JournalFillFromContentRequest,
  ): Promise<JournalFillFromContentResponse> {
    try {
      return await invoke<JournalFillFromContentResponse>('office_journal_fill_from_content', {
        spec_id: req.spec_id,
        workspace_path: req.workspace_path,
        content: req.content,
        output_filename: req.output_filename,
      });
    } catch (error) {
      throw handleApiError(error);
    }
  },
};

export function formatJournalFillSummary(
  req?: Partial<JournalFillFromContentRequest> | null,
): string {
  if (!req) return 'journal-fill: empty';
  /* v8 ignore start */
  const spec = req.spec_id || 'none';
  const out = req.output_filename || 'auto';
  const sectionCount = req.content?.sections ? Object.keys(req.content.sections).length : 0;
  /* v8 ignore stop */
  return `journal-fill: spec=${spec} -> ${out} · ${sectionCount} sections`;
}

export function formatJournalFillJson(
  req?: Partial<JournalFillFromContentRequest> | null,
): string {
  return JSON.stringify(
    {
      /* v8 ignore start */
      specId: req?.spec_id ?? null,
      workspacePath: req?.workspace_path ?? null,
      outputFilename: req?.output_filename ?? null,
      sectionCount: req?.content?.sections ? Object.keys(req.content.sections).length : 0,
      referenceCount: req?.content?.references ? req.content.references.length : 0,
      /* v8 ignore stop */
    },
    null,
    2,
  );
}
