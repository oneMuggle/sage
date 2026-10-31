import { ArrowLeft, ArrowRight, Globe, RotateCw } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { useI18n } from '../../shared/lib/i18n';

type PanelApi = NonNullable<Window['electronAPI']>['browserPanel'];

function panelApi(): PanelApi | undefined {
  return typeof window !== 'undefined' ? window.electronAPI?.browserPanel : undefined;
}

/**
 * 右栏「浏览器」面板：控件在渲染层，页面本身由主进程 BrowserView 覆盖在
 * 占位区上方。bounds 通过 getBoundingClientRect 上报，主进程负责钳制。
 */
export function BrowserPanel(): JSX.Element {
  const { t } = useI18n();
  const api = panelApi();
  const contentRef = useRef<HTMLDivElement | null>(null);
  const inputFocused = useRef(false);
  const [address, setAddress] = useState('');
  const [canBack, setCanBack] = useState(false);
  const [canForward, setCanForward] = useState(false);
  const [error, setError] = useState('');

  const reportBounds = useCallback(() => {
    const apiRef = panelApi();
    const element = contentRef.current;
    if (!apiRef || !element) return;
    const rect = element.getBoundingClientRect();
    void apiRef
      .setBounds({ x: rect.left, y: rect.top, width: rect.width, height: rect.height })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const apiRef = panelApi();
    if (!apiRef) return;
    void apiRef.show().then(() => reportBounds()).catch(() => undefined);
    const observer = new ResizeObserver(() => reportBounds());
    if (contentRef.current) observer.observe(contentRef.current);
    window.addEventListener('resize', reportBounds);
    const interval = window.setInterval(() => {
      void apiRef
        .current()
        .then((state) => {
          if (!inputFocused.current) setAddress(state.url || '');
          setCanBack(state.canGoBack);
          setCanForward(state.canGoForward);
        })
        .catch(() => undefined);
    }, 1000);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', reportBounds);
      window.clearInterval(interval);
      void apiRef.hide().catch(() => undefined);
    };
  }, [reportBounds]);

  const navigate = async (raw: string): Promise<void> => {
    const apiRef = panelApi();
    if (!apiRef) return;
    const url = raw.trim();
    if (!/^https?:\/\//i.test(url)) {
      setError(t('browser.panel.invalid_url'));
      return;
    }
    setError('');
    try {
      await apiRef.navigate(url);
      reportBounds();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  if (!api) {
    return (
      <div className="h-full flex items-center justify-center p-4 text-xs text-muted">
        {t('browser.panel.desktop_only')}
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col" data-testid="browser-panel">
      <div className="flex items-center gap-1 px-2 py-1.5 border-b border-border">
        <button
          type="button"
          aria-label={t('browser.panel.back')}
          className="p-1 rounded hover:bg-bg-hover disabled:opacity-40"
          disabled={!canBack}
          onClick={() => void api.back().catch(() => undefined)}
        >
          <ArrowLeft className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          aria-label={t('browser.panel.forward')}
          className="p-1 rounded hover:bg-bg-hover disabled:opacity-40"
          disabled={!canForward}
          onClick={() => void api.forward().catch(() => undefined)}
        >
          <ArrowRight className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          aria-label={t('browser.panel.reload')}
          className="p-1 rounded hover:bg-bg-hover"
          onClick={() => void api.reload().catch(() => undefined)}
        >
          <RotateCw className="w-3.5 h-3.5" />
        </button>
        <Globe className="w-3.5 h-3.5 text-text-secondary shrink-0" />
        <input
          data-testid="browser-panel-address"
          value={address}
          onChange={(event) => setAddress(event.target.value)}
          onFocus={() => {
            inputFocused.current = true;
          }}
          onBlur={() => {
            inputFocused.current = false;
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') void navigate(address);
          }}
          placeholder={t('browser.panel.placeholder')}
          className="flex-1 min-w-0 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
        />
      </div>
      {error && <div className="px-2 py-1 text-xs text-error">{error}</div>}
      <div ref={contentRef} className="flex-1 min-h-0 bg-bg" data-testid="browser-panel-content" />
    </div>
  );
}
