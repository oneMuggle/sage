// src/features/chat/AtFileMenu.tsx
import { useState, useEffect, useRef } from 'react';
import {
  fileSearchClient,
  FileSearchTimeoutError,
} from '../../shared/api/fileSearchClient';
import { useI18n } from '../../shared/lib/i18n';

interface FileSearchResult {
  path: string;
  name: string;
  size?: number;
}

interface AtFileMenuProps {
  query: string | null;
  onSelect: (path: string) => void;
  onClose: () => void;
}

export function AtFileMenu({ query, onSelect }: AtFileMenuProps) {
  const { t } = useI18n();
  const [results, setResults] = useState<FileSearchResult[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Search files when query changes
  useEffect(() => {
    if (query === null) return;

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
      .search(query, { signal: controller.signal })
      .then((res) => {
        setResults(res);
        setIsLoading(false);
      })
      .catch((err) => {
        if (err.name === 'AbortError') {
          // Search was cancelled, ignore
          return;
        }
        if (err instanceof FileSearchTimeoutError) {
          setError('timeout');
        } else {
          setError(err.message);
        }
        setIsLoading(false);
      });

    // Cleanup on unmount or query change
    return () => {
      controller.abort();
    };
  }, [query]);

  // Don't render if query is null
  if (query === null) {
    return null;
  }

  const handleSelect = (path: string) => {
    onSelect(path);
  };

  const handleRetry = () => {
    if (query !== null) {
      // Trigger search again by setting query to itself
      // This will cause useEffect to re-run
      setError(null);
      setIsLoading(true);

      fileSearchClient
        .search(query)
        .then((res) => {
          setResults(res);
          setIsLoading(false);
        })
        .catch((err) => {
          if (err instanceof FileSearchTimeoutError) {
            setError('timeout');
          } else {
            setError(err.message);
          }
          setIsLoading(false);
        });
    }
  };

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
      {isLoading && (
        <div className="at-file-menu__loading">{t('chat.atFile.searching')}</div>
      )}

      {error === 'timeout' && (
        <div className="at-file-menu__error">
          <span>{t('chat.atFile.timeout')}</span>
          <button type="button" onClick={handleRetry} className="at-file-menu__retry">
            {t('chat.atFile.retry')}
          </button>
        </div>
      )}

      {error && error !== 'timeout' && (
        <div className="at-file-menu__error">
          {t('chat.atFile.error')}
        </div>
      )}

      {!isLoading && !error && results.length === 0 && (
        <div className="at-file-menu__empty">{t('chat.atFile.empty')}</div>
      )}

      {!isLoading && !error && results.length > 0 && (
        <ul className="at-file-menu__list">
          {results.map((file, idx) => (
            <li key={file.path}>
              <button
                type="button"
                className={`at-file-menu__item ${idx === selectedIdx ? 'at-file-menu__item--selected' : ''}`}
                onClick={() => handleSelect(file.path)}
                onMouseEnter={() => setSelectedIdx(idx)}
              >
                <span className="at-file-menu__item-name">{file.name}</span>
                <span className="at-file-menu__item-path">{file.path}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
