/** 规程卡片工具条（2026-11-01，从 PlaybookCard 拆出以控制行数）。 */
import { Download, RefreshCw, Upload } from 'lucide-react';

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
  onSeedMilestones: () => void;
  onCleanupRules: () => void;
  onUnbind: () => void;
  onImportClick: () => void;
}

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
  onSeedMilestones,
  onCleanupRules,
  onUnbind,
  onImportClick,
}: PlaybookToolbarProps) {
  const { t } = usePlaybookI18n();
  return (
    <div className="flex flex-wrap items-center gap-2">
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
      <Button
        size="sm"
        variant="secondary"
        onClick={() => onExport('json')}
        disabled={busy === 'export-json'}
      >
        <Download className="mr-1 h-3.5 w-3.5" />
        {t('playbook.card.export')}
      </Button>
      <Button size="sm" variant="secondary" onClick={() => onExport('md')}>
        {t('playbook.card.exportHandbook')}
      </Button>
      <Button size="sm" variant="secondary" onClick={() => onExport('agents')}>
        {t('playbook.card.exportAgents')}
      </Button>
      <Button
        size="sm"
        variant="secondary"
        onClick={onWikiExport}
        disabled={busy === 'wiki-export'}
        data-testid="playbook-wiki-export"
      >
        {busy === 'wiki-export' ? t('playbook.card.wikiWriting') : t('playbook.card.wikiExport')}
      </Button>
      <Button
        size="sm"
        variant="secondary"
        onClick={onSaveToLibrary}
        disabled={busy === 'save-library'}
        data-testid="playbook-save-library"
      >
        {busy === 'save-library'
          ? t('playbook.card.savingLibrary')
          : t('playbook.card.saveLibrary')}
      </Button>
      <Button
        size="sm"
        variant="secondary"
        onClick={onToggleLibrary}
        data-testid="playbook-open-library"
      >
        {t('playbook.card.library')}
      </Button>
      <Button
        size="sm"
        variant="secondary"
        onClick={onEdit}
        disabled={!hasPlaybook}
        data-testid="playbook-edit-btn"
      >
        {t('playbook.card.edit')}
      </Button>
      <Button
        size="sm"
        variant="secondary"
        onClick={onLoadVersions}
        data-testid="playbook-versions-btn"
      >
        {t('playbook.card.versions')}
      </Button>
      <Button
        size="sm"
        variant="secondary"
        onClick={onSeedMilestones}
        disabled={busy === 'seed-milestones'}
        data-testid="playbook-seed-milestones"
      >
        {t('playbook.card.seedMilestones')}
      </Button>
      <Button
        size="sm"
        variant="secondary"
        onClick={onCleanupRules}
        data-testid="playbook-cleanup-rules"
      >
        {t('playbook.card.cleanupRules')}
      </Button>
      <Button size="sm" variant="secondary" onClick={onUnbind} data-testid="playbook-unbind">
        {t('playbook.card.unbind')}
      </Button>
      <Button size="sm" variant="secondary" onClick={onImportClick}>
        <Upload className="mr-1 h-3.5 w-3.5" />
        {t('playbook.card.import')}
      </Button>
    </div>
  );
}

export default PlaybookToolbar;
