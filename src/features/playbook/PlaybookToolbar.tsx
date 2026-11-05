/** 规程卡片工具条（2026-11-01 拆出；2026-11-03 M4 收束为 3 个主操作 + 更多菜单）。 */
import { ChevronDown, Download, FileUp, RefreshCw, Upload } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { Button } from '../../shared/ui/Button';

import { usePlaybookI18n } from './usePlaybookI18n';

export interface PlaybookToolbarProps {
  busy: string | null;
  hasPlaybook: boolean;
  onRefreshAudit: () => void;
  onAiAudit: () => void;
  onExport: (format: 'json' | 'md' | 'agents') => void;
  onWikiExport: () => void;
  onSaveToLibrary: () => void;
  onToggleLibrary: () => void;
  onEdit: () => void;
  onLoadVersions: () => void;
  onLoadActivity: () => void;
  onSeedMilestones: () => void;
  onCleanupRules: () => void;
  onUnbind: () => void;
  onImportClick: () => void;
  onDocumentImportClick: () => void;
}

const menuItemClass =
  'flex w-full items-center gap-1.5 whitespace-nowrap rounded px-2 py-1.5 text-left text-xs text-foreground hover:bg-muted disabled:opacity-50';
const menuPanelClass =
  'absolute right-0 top-full z-20 mt-1 min-w-[11rem] rounded-md border border-border bg-card p-1 shadow-lg';

export function PlaybookToolbar({
  busy,
  hasPlaybook,
  onRefreshAudit,
  onAiAudit,
  onExport,
  onWikiExport,
  onSaveToLibrary,
  onToggleLibrary,
  onEdit,
  onLoadVersions,
  onLoadActivity,
  onSeedMilestones,
  onCleanupRules,
  onUnbind,
  onImportClick,
  onDocumentImportClick,
}: PlaybookToolbarProps) {
  const { t } = usePlaybookI18n();
  const [exportOpen, setExportOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!exportOpen && !moreOpen) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setExportOpen(false);
        setMoreOpen(false);
      }
    };
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, [exportOpen, moreOpen]);

  const runAndClose = (action: () => void) => () => {
    setExportOpen(false);
    setMoreOpen(false);
    action();
  };

  return (
    <div
      ref={rootRef}
      className="flex flex-wrap items-center gap-2"
      data-testid="playbook-toolbar"
    >
      <Button
        size="sm"
        variant="secondary"
        onClick={onRefreshAudit}
        disabled={busy === 'audit'}
        data-testid="playbook-refresh-audit"
      >
        <RefreshCw className="mr-1 h-3.5 w-3.5" />
        {busy === 'audit' ? t('playbook.card.refreshing') : t('playbook.card.refresh')}
      </Button>
      <Button
        size="sm"
        variant="secondary"
        onClick={onAiAudit}
        disabled={busy === 'audit-ai'}
        data-testid="playbook-ai-audit"
      >
        {busy === 'audit-ai' ? t('playbook.card.aiChecking') : t('playbook.card.aiCheck')}
      </Button>

      <div className="relative">
        <Button
          size="sm"
          variant="secondary"
          onClick={() => {
            setExportOpen((value) => !value);
            setMoreOpen(false);
          }}
          data-testid="playbook-export-menu-btn"
          aria-expanded={exportOpen}
        >
          <Download className="mr-1 h-3.5 w-3.5" />
          {t('playbook.card.export')}
          <ChevronDown className="ml-1 h-3 w-3" />
        </Button>
        {exportOpen && (
          <div className={menuPanelClass} role="menu" data-testid="playbook-export-menu">
            <button
              type="button"
              className={menuItemClass}
              onClick={runAndClose(() => onExport('json'))}
              data-testid="playbook-export-json"
            >
              {t('playbook.card.export')} JSON
            </button>
            <button
              type="button"
              className={menuItemClass}
              onClick={runAndClose(() => onExport('md'))}
              data-testid="playbook-export-md"
            >
              {t('playbook.card.exportHandbook')}
            </button>
            <button
              type="button"
              className={menuItemClass}
              onClick={runAndClose(() => onExport('agents'))}
              data-testid="playbook-export-agents"
            >
              {t('playbook.card.exportAgents')}
            </button>
            <button
              type="button"
              className={menuItemClass}
              onClick={runAndClose(onWikiExport)}
              disabled={busy === 'wiki-export'}
              data-testid="playbook-wiki-export"
            >
              {busy === 'wiki-export'
                ? t('playbook.card.wikiWriting')
                : t('playbook.card.wikiExport')}
            </button>
          </div>
        )}
      </div>

      <div className="relative">
        <Button
          size="sm"
          variant="secondary"
          onClick={() => {
            setMoreOpen((value) => !value);
            setExportOpen(false);
          }}
          data-testid="playbook-more-menu-btn"
          aria-expanded={moreOpen}
        >
          更多
          <ChevronDown className="ml-1 h-3 w-3" />
        </Button>
        {moreOpen && (
          <div className={menuPanelClass} role="menu" data-testid="playbook-more-menu">
            <button
              type="button"
              className={menuItemClass}
              onClick={runAndClose(onEdit)}
              disabled={!hasPlaybook}
              data-testid="playbook-edit-btn"
            >
              {t('playbook.card.edit')}
            </button>
            <button
              type="button"
              className={menuItemClass}
              onClick={runAndClose(onLoadVersions)}
              data-testid="playbook-versions-btn"
            >
              {t('playbook.card.versions')}
            </button>
            <button
              type="button"
              className={menuItemClass}
              onClick={runAndClose(onLoadActivity)}
              data-testid="playbook-activity-btn"
            >
              {t('playbook.card.activity')}
            </button>
            <div className="my-1 border-t border-border/60" />
            <button
              type="button"
              className={menuItemClass}
              onClick={runAndClose(onSaveToLibrary)}
              disabled={busy === 'save-library'}
              data-testid="playbook-save-library"
            >
              {busy === 'save-library'
                ? t('playbook.card.savingLibrary')
                : t('playbook.card.saveLibrary')}
            </button>
            <button
              type="button"
              className={menuItemClass}
              onClick={runAndClose(onToggleLibrary)}
              data-testid="playbook-open-library"
            >
              {t('playbook.card.library')}
            </button>
            <button
              type="button"
              className={menuItemClass}
              onClick={runAndClose(onImportClick)}
              data-testid="playbook-import-btn"
            >
              <Upload className="h-3 w-3" />
              {t('playbook.card.import')}
            </button>
            <button
              type="button"
              className={menuItemClass}
              onClick={runAndClose(onDocumentImportClick)}
              data-testid="playbook-document-import-btn"
            >
              <FileUp className="h-3 w-3" />
              {t('playbook.card.importDocument')}
            </button>
            <div className="my-1 border-t border-border/60" />
            <button
              type="button"
              className={menuItemClass}
              onClick={runAndClose(onSeedMilestones)}
              disabled={busy === 'seed-milestones'}
              data-testid="playbook-seed-milestones"
            >
              {t('playbook.card.seedMilestones')}
            </button>
            <button
              type="button"
              className={menuItemClass}
              onClick={runAndClose(onCleanupRules)}
              data-testid="playbook-cleanup-rules"
            >
              {t('playbook.card.cleanupRules')}
            </button>
            <div className="my-1 border-t border-border/60" />
            <button
              type="button"
              className={`${menuItemClass} text-destructive`}
              onClick={runAndClose(onUnbind)}
              data-testid="playbook-unbind"
            >
              {t('playbook.card.unbind')}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default PlaybookToolbar;
