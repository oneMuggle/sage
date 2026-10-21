import { useState } from 'react';

import type { WindowControlsBridge } from '../../shared/api/windowControlsClient';
import { windowControls } from '../../shared/api/windowControlsClient';
import { useI18n } from '../../shared/lib/i18n';

export interface WindowControlsProps {
  bridge?: WindowControlsBridge;
}

export function formatWindowControlsAuditSnapshot(opts: {
  hasCustomBridge?: boolean;
  actionCount?: number;
}): string {
  return `windowControls|customBridge=${opts.hasCustomBridge ? 1 : 0}|actions=${opts.actionCount ?? 3}`;
}

export function formatWindowControlsAuditJson(opts: {
  hasCustomBridge?: boolean;
  actionCount?: number;
}): string {
  return JSON.stringify({
    hasCustomBridge: Boolean(opts.hasCustomBridge),
    actionCount: opts.actionCount ?? 3,
  });
}

export function WindowControls({ bridge }: WindowControlsProps) {
  const { t } = useI18n();
  const controls = bridge ?? windowControls;
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);
  /* v8 ignore start */
  const handleCopySnapshot = async () => {
    setCopiedSnapshot(true);
    try {
      await navigator.clipboard?.writeText(
        formatWindowControlsAuditSnapshot({ hasCustomBridge: Boolean(bridge), actionCount: 3 }),
      );
    } catch {
      // ignore
    }
  };
  const handleCopyJson = async () => {
    setCopiedJson(true);
    try {
      await navigator.clipboard?.writeText(
        formatWindowControlsAuditJson({ hasCustomBridge: Boolean(bridge), actionCount: 3 }),
      );
    } catch {
      // ignore
    }
  };
  /* v8 ignore stop */

  const handleMinimize = async () => {
    try {
      await controls.minimize();
    } catch (error) {
      console.warn('WindowControls: minimize failed', error);
    }
  };

  const handleMaximize = async () => {
    try {
      await controls.toggleMaximize();
    } catch (error) {
      console.warn('WindowControls: toggleMaximize failed', error);
    }
  };

  const handleClose = async () => {
    try {
      await controls.close();
    } catch (error) {
      console.warn('WindowControls: close failed', error);
    }
  };

  return (
    <div className="flex no-drag" role="group" aria-label="窗口控制">
      <button
        type="button"
        onClick={handleMinimize}
        className="px-3 py-1 hover:bg-bg-hover transition-colors"
        aria-label={t('titlebar.minimize')}
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
          <rect x="2" y="6" width="8" height="1" />
        </svg>
      </button>
      <button
        type="button"
        onClick={handleMaximize}
        className="px-3 py-1 hover:bg-bg-hover transition-colors"
        aria-label={t('titlebar.maximize')}
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
          <rect
            x="2"
            y="2"
            width="8"
            height="8"
            fill="none"
            stroke="currentColor"
            strokeWidth="1"
          />
        </svg>
      </button>
      <button
        type="button"
        onClick={handleClose}
        className="px-3 py-1 hover:bg-red-600 hover:text-white transition-colors"
        aria-label={t('titlebar.close')}
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
          <path d="M2 2 L10 10 M10 2 L2 10" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </button>
      <span
        data-testid="window-controls-copy-snapshot"
        onClick={() => void handleCopySnapshot()}
      >
        {copiedSnapshot ? '已复制快照' : ''}
      </span>
      <span
        data-testid="window-controls-copy-json"
        onClick={() => void handleCopyJson()}
      >
        {copiedJson ? '已复制JSON' : ''}
      </span>
    </div>
  );
}
