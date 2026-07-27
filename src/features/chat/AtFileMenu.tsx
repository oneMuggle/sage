// src/features/chat/AtFileMenu.tsx
import { useEffect, useRef, useState } from 'react';

import {
  fileSearchClient,
  FileSearchTimeoutError,
  classifyAtFileSelection,
  type AtFileSelection,
  type FileSearchResult,
} from '../../shared/api/fileSearchClient';
import { useI18n } from '../../shared/lib/i18n';
import { useOptionalWorkspaceContext } from '../../shared/lib/workspaceContext';

const KIND_ICON: Record<FileSearchResult['kind'], string> = {
  file: '📄',
  'office-ppt': '📊',
  'office-word': '📝',
  'office-excel': '📈',
};

interface AtFileMenuProps {
  query: string | null;
  /**
   * AtFileMenu notifies the caller of a selection. The payload is a
   * discriminated union:
   *   - `{ kind: 'file', path, name }` — plain file; caller inserts `@<path>`
   *   - `{ kind: 'office-import', result }` — unmanaged office doc; caller
   *     must call `importOfficeReference` to materialize a `ChatOfficeRef`
   *   - `{ kind: 'office', ref }` — managed office doc; caller adds the
   *     ref directly (no import needed)
   *
   * AtFileMenu never fabricates a `ChatOfficeRef` for a plain file.
   */
  onSelect: (selection: AtFileSelection) => void;
  onClose: () => void;
}

export function AtFileMenu({ query, onSelect }: AtFileMenuProps) {
  const { t } = useI18n();
  // Task 7 (2026-07-26): read both sessionId and workspacePath from the
  // session-workspace context. sessionId is required by fileSearchClient;
  // workspacePath is required by `importOfficeReference` for the
  // `kind: 'office-import'` selection. Both come from the same provider
  // so the menu stays in lock-step with Chat's binding state.
  //
  // Use the optional variant so legacy tests (which don't mount the
  // provider) keep working — the menu just returns no results.
  const wsCtx = useOptionalWorkspaceContext();
  const sessionId = wsCtx?.sessionId ?? null;
  const workspacePath = wsCtx?.binding?.workspacePath;
  const [results, setResults] = useState<FileSearchResult[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Search files when query changes
  useEffect(() => {
    if (query === null) return;
    if (!sessionId) {
      // No active session → empty results, no loading state.
      setResults([]);
      setIsLoading(false);
      setError(null);
      return;
    }

    // Cancel previous search
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;

    setIsLoading(true);
    setError(null);
    setSelectedIdx(0);

    fileSearchClient
      .search(sessionId, query, { signal: controller.signal })
      .then((res) => {
        setResults(res);
        setIsLoading(false);
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') {
          return;
        }
        if (err instanceof FileSearchTimeoutError) {
          setError('timeout');
        } else {
          setError(err instanceof Error ? err.message : String(err));
        }
        setIsLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [query, sessionId]);

  // Don't render if query is null
  if (query === null) {
    return null;
  }

  const handleSelect = (result: FileSearchResult) => {
    const kind = classifyAtFileSelection(result);
    if (kind === 'file') {
      onSelect({ kind: 'file', path: result.path, name: result.name });
      return;
    }
    if (kind === 'office') {
      // Managed office doc — build the ref inline. Path is irrelevant
      // here (the backend resolves the docId).
      if (!result.docId || !result.docType) {
        // Should never happen — classifyAtFileSelection guarantees it.
        // Fall back to the import path so the user still gets a result.
        onSelect({ kind: 'office-import', result });
        return;
      }
      onSelect({
        kind: 'office',
        ref: { docId: result.docId, docType: result.docType, filename: result.name },
      });
      return;
    }
    // kind === 'office-import'
    onSelect({ kind: 'office-import', result });
  };

  const handleRetry = () => {
    if (query === null || !sessionId) return;
    setError(null);
    setIsLoading(true);
    fileSearchClient
      .search(sessionId, query)
      .then((res) => {
        setResults(res);
        setIsLoading(false);
      })
      .catch((err: unknown) => {
        if (err instanceof FileSearchTimeoutError) {
          setError('timeout');
        } else {
          setError(err instanceof Error ? err.message : String(err));
        }
        setIsLoading(false);
      });
  };

  // Disable office selection when no workspace is bound — managed refs
  // require a backend route, and import-on-pick needs the workspace path.
  const officeSearchDisabled = !workspacePath;

  return (
    <div
      className="at-file-menu"
      style={{
        position: 'absolute',
        bottom: '100%',
        left: 0,
        right: 0,
        marginBottom: '0.5rem',
        maxHeight: '300px',
        overflowY: 'auto',
        backgroundColor: 'var(--bg-surface)',
        border: '1px solid var(--border-default)',
        borderRadius: 'var(--radius-md)',
        boxShadow: '0 4px 12px rgba(0, 0, 0, 0.1)',
        zIndex: 1000,
      }}
    >
      {isLoading && <div className="at-file-menu__loading">{t('chat.atFile.searching')}</div>}

      {error === 'timeout' && (
        <div className="at-file-menu__error">
          <span>{t('chat.atFile.timeout')}</span>
          <button type="button" onClick={handleRetry} className="at-file-menu__retry">
            {t('chat.atFile.retry')}
          </button>
        </div>
      )}

      {error && error !== 'timeout' && (
        <div className="at-file-menu__error">{t('chat.atFile.error')}</div>
      )}

      {!isLoading && !error && results.length === 0 && (
        <div className="at-file-menu__empty">{t('chat.atFile.empty')}</div>
      )}

      {!isLoading && !error && results.length > 0 && (
        <ul className="at-file-menu__list">
          {results.map((file, idx) => {
            const kind = classifyAtFileSelection(file);
            const disabled =
              officeSearchDisabled && (kind === 'office' || kind === 'office-import');
            return (
              <li key={`${file.path}-${idx}`}>
                <button
                  type="button"
                  className={`at-file-menu__item ${idx === selectedIdx ? 'at-file-menu__item--selected' : ''}`}
                  onClick={() => handleSelect(file)}
                  disabled={disabled}
                  onMouseEnter={() => setSelectedIdx(idx)}
                  title={disabled ? 'Bind a workspace first to use managed Office refs' : undefined}
                >
                  <span className="at-file-menu__item-kind" aria-label={file.kind}>
                    {KIND_ICON[file.kind] ?? '📄'}
                  </span>
                  <span className="at-file-menu__item-name">{file.name}</span>
                  <span className="at-file-menu__item-path">{file.path}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
