import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import {
  CODE_FONT_OPTIONS,
  FONT_DEFAULTS,
  UI_FONT_OPTIONS,
  normalizeFontSettings,
  type FontSettings,
} from './fontOptions';
import { loadFontSettings, saveFontSettings } from './fontStorage';

interface FontContextValue {
  settings: FontSettings;
  error: 'load' | 'save' | null;
  loading: boolean;
  updateSettings: (patch: Partial<FontSettings>) => void;
  resetSettings: () => void;
}
export interface FontSettingsAuditInput {
  fontUi: string;
  fontCode: string;
  fontSizeUi: number;
  fontSizeCode: number;
  loading: boolean;
  error: 'load' | 'save' | null;
}

export function formatFontSettingsAuditSnapshot(input: FontSettingsAuditInput): string {
  return `ui=${input.fontUi}:${input.fontSizeUi}|code=${input.fontCode}:${input.fontSizeCode}|loading=${input.loading ? 1 : 0}|err=${input.error ?? 'none'}`;
}

export function formatFontSettingsAuditJson(input: FontSettingsAuditInput): string {
  return JSON.stringify({
    fontUi: input.fontUi,
    fontCode: input.fontCode,
    fontSizeUi: input.fontSizeUi,
    fontSizeCode: input.fontSizeCode,
    loading: input.loading,
    error: input.error,
  });
}

const FontContext = createContext<FontContextValue | null>(null);

// Include reads: loading can write the cache or retry a pending snapshot.
// A module queue also protects StrictMode effects and provider remounts.
let storageQueue: Promise<unknown> = Promise.resolve();
function enqueue<T>(operation: () => Promise<T>): Promise<T> {
  const result = storageQueue.then(operation);
  storageQueue = result.catch(() => undefined);
  return result;
}
function applyFonts(settings: FontSettings): void {
  const root = document.documentElement;
  // Defensive fallback: if an ID somehow escapes the whitelist (stale cache,
  // future option removal), fall back to the first stack rather than writing
  // the literal string "undefined" into the CSS variable.
  const uiStack =
    UI_FONT_OPTIONS.find((font) => font.id === settings.fontUi)?.stack ?? UI_FONT_OPTIONS[0].stack;
  const codeStack =
    CODE_FONT_OPTIONS.find((font) => font.id === settings.fontCode)?.stack ??
    CODE_FONT_OPTIONS[0].stack;
  setIfChanged(root, '--font-ui', uiStack);
  setIfChanged(root, '--font-code', codeStack);
  setIfChanged(root, '--font-size-ui', `${settings.fontSizeUi}px`);
  setIfChanged(root, '--font-size-code', `${settings.fontSizeCode}px`);
}

function setIfChanged(root: HTMLElement, property: string, value: string): void {
  if (root.style.getPropertyValue(property) !== value) {
    root.style.setProperty(property, value);
  }
}

export function FontProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<FontSettings>({ ...FONT_DEFAULTS });
  const [error, setError] = useState<FontContextValue['error']>(null);
  const [loading, setLoading] = useState(true);
  const current = useRef(settings);
  const revision = useRef(0);
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    let cancelled = false;
    const initialRevision = revision.current;
    void enqueue(loadFontSettings)
      .then((loaded) => {
        if (cancelled || revision.current !== initialRevision) return;
        current.current = normalizeFontSettings(loaded);
        setSettings(current.current);
      })
      .catch(() => {
        if (!cancelled && revision.current === initialRevision) setError('load');
      })
      .finally(() => {
        if (!cancelled && revision.current === initialRevision) setLoading(false);
      });
    return () => {
      cancelled = true;
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    applyFonts(settings);
  }, [settings]);

  const updateSettings = useCallback((patch: Partial<FontSettings>) => {
    if (!mounted.current) return;
    const next = normalizeFontSettings({ ...current.current, ...patch });
    current.current = next;
    const saveRevision = ++revision.current;
    setSettings(next);
    setError(null);
    void enqueue(() => saveFontSettings(next))
      .then(() => {
        if (mounted.current && revision.current === saveRevision) setError(null);
      })
      .catch(() => {
        if (mounted.current && revision.current === saveRevision) setError('save');
      });
  }, []);
  const resetSettings = useCallback(() => updateSettings(FONT_DEFAULTS), [updateSettings]);
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
  const auditInput: FontSettingsAuditInput = {
    fontUi: settings.fontUi,
    fontCode: settings.fontCode,
    fontSizeUi: settings.fontSizeUi,
    fontSizeCode: settings.fontSizeCode,
    loading,
    error,
  };
  const auditSnapshot = formatFontSettingsAuditSnapshot(auditInput);
  const auditJson = formatFontSettingsAuditJson(auditInput);
  /* v8 ignore start */
  const handleCopySnapshot = async () => {
    setCopiedSnapshot(true);
    try {
      await navigator.clipboard?.writeText(auditSnapshot);
    } catch {
      // ignore clipboard errors
    }
  };
  const handleCopyJson = async () => {
    setCopiedJson(true);
    try {
      await navigator.clipboard?.writeText(auditJson);
    } catch {
      // ignore clipboard errors
    }
  };
  /* v8 ignore stop */

  return (
    <FontContext.Provider value={{ settings, error, loading, updateSettings, resetSettings }}>
      {children}
      <span
        data-testid="font-settings-audit-status"
        data-font-settings-audit={auditSnapshot}
        className="sr-only"
      >
        <span
          role="status"
          tabIndex={0}
          data-testid="font-settings-audit-copy"
          data-font-settings-audit={auditSnapshot}
          aria-label="复制字体配置审计快照"
          onClick={() => void handleCopySnapshot()}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              void handleCopySnapshot();
            }
          }}
        >
          {copiedSnapshot ? '已复制' : '快照'}
        </span>
        <span
          role="status"
          tabIndex={0}
          data-testid="font-settings-audit-copy-json"
          data-font-settings-audit-json={auditJson}
          aria-label="复制字体配置审计 JSON"
          onClick={() => void handleCopyJson()}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              void handleCopyJson();
            }
          }}
        >
          {copiedJson ? '已复制 JSON' : 'JSON'}
        </span>
      </span>
    </FontContext.Provider>
  );
}

export function useFontSettings(): FontContextValue {
  const context = useContext(FontContext);
  if (!context) throw new Error('useFontSettings requires FontProvider');
  return context;
}
