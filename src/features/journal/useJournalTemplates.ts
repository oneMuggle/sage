/**
 * useJournalTemplates — state + actions for the /journal side panel (Task 7).
 *
 * Mirrors src/features/office/useOfficeDocuments.ts shape: React useState
 * (no zustand) — the panel is single-instance and scoped to the active
 * workspace. The hook owns:
 *   - the currently parsed JournalSpec (or null)
 *   - the editing content (title/abstract/sections/refs)
 *   - validation violations
 *   - error message
 *
 * pickTemplate delegates to `window.electronAPI.office.pickOfficeFile('word')`
 * which already exists in electron/preload.ts (added in Phase 1.3) — no new
 * pickFile IPC needed.
 */
import { useCallback, useState } from 'react';

import { journalApi } from '../../shared/api/journalApi';
import type {
  JournalFillFromContentRequest,
  JournalFillFromContentResponse,
  JournalSpec,
  JournalValidateResponse,
  JournalViolation,
} from '../../shared/api/types';

export interface JournalContentDraft {
  title: string;
  abstract: string;
  sections: Record<string, string>;
  references: string[];
}

const EMPTY_CONTENT: JournalContentDraft = {
  title: '',
  abstract: '',
  sections: { keywords: '' },
  references: [],
};

export interface UseJournalTemplatesReturn {
  spec: JournalSpec | null;
  content: JournalContentDraft;
  violations: JournalViolation[];
  loading: boolean;
  error: string | null;
  /** Open native file dialog (reuses existing office.pickOfficeFile('word')), then parse. */
  pickTemplate: () => Promise<JournalSpec | null>;
  /** Validate a saved paper file against the active spec (or pass spec_id separately). */
  validateFile: (filePath: string, specId?: string) => Promise<JournalValidateResponse | null>;
  /** Fill a docx from the active spec + current content draft. */
  fillFromContent: (workspacePath: string, outputFilename: string) => Promise<JournalFillFromContentResponse | null>;
  setContent: (patch: Partial<JournalContentDraft>) => void;
  reset: () => void;
}

export function useJournalTemplates(): UseJournalTemplatesReturn {
  const [spec, setSpec] = useState<JournalSpec | null>(null);
  const [content, setContentState] = useState<JournalContentDraft>(EMPTY_CONTENT);
  const [violations, setViolations] = useState<JournalViolation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pickTemplate = useCallback(async (): Promise<JournalSpec | null> => {
    setError(null);
    setLoading(true);
    try {
      const picked = await window.electronAPI?.office.pickOfficeFile('word');
      if (!picked) return null; // user cancelled
      const { spec: parsed } = await journalApi.parseTemplate(picked.path);
      setSpec(parsed);
      return parsed;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const validateFile = useCallback(
    async (filePath: string, specId?: string): Promise<JournalValidateResponse | null> => {
      setError(null);
      setLoading(true);
      try {
        const result = await journalApi.validate({ spec_id: specId, file_path: filePath });
        setViolations(result.violations);
        return result;
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        return null;
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  const fillFromContent = useCallback(
    async (
      workspacePath: string,
      outputFilename: string,
    ): Promise<JournalFillFromContentResponse | null> => {
      if (!spec) {
        setError('未选择期刊模板，请先 pickTemplate');
        return null;
      }
      setError(null);
      setLoading(true);
      try {
        const req: JournalFillFromContentRequest = {
          spec_id: spec.spec_id,
          workspace_path: workspacePath,
          content: {
            title: content.title,
            abstract: content.abstract,
            sections: content.sections,
            references: content.references,
          },
          output_filename: outputFilename,
        };
        return await journalApi.fillFromContent(req);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        return null;
      } finally {
        setLoading(false);
      }
    },
    [spec, content],
  );

  const setContent = useCallback((patch: Partial<JournalContentDraft>) => {
    setContentState((prev) => ({ ...prev, ...patch }));
  }, []);

  const reset = useCallback(() => {
    setSpec(null);
    setContentState(EMPTY_CONTENT);
    setViolations([]);
    setError(null);
  }, []);

  return {
    spec,
    content,
    violations,
    loading,
    error,
    pickTemplate,
    validateFile,
    fillFromContent,
    setContent,
    reset,
  };
}