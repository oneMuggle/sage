/** PlaybookVersionsPanel — 规程版本历史（2026-11-01，从 PlaybookCard 拆出）。 */
import type { PlaybookVersion } from '../../shared/api/playbookApi';
import { Button } from '../../shared/ui/Button';

import { usePlaybookI18n } from './usePlaybookI18n';

export interface PlaybookVersionsPanelProps {
  versions: PlaybookVersion[];
  onClose: () => void;
}

export function PlaybookVersionsPanel({ versions, onClose }: PlaybookVersionsPanelProps) {
  const { t } = usePlaybookI18n();
  return (
    <div
      className="space-y-1 rounded-md border border-border p-2 text-xs"
      data-testid="playbook-versions"
    >
      <div className="font-medium text-foreground">{t('playbook.versions.title')}</div>
      {versions.length === 0 ? (
        <div className="text-muted-foreground">{t('playbook.versions.empty')}</div>
      ) : (
        versions.map((item) => (
          <div key={item.version} className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground">
              v{item.version} · {item.source} · {new Date(item.created_at).toLocaleString()}
            </span>
            {item.active && <span className="text-primary">{t('playbook.versions.current')}</span>}
          </div>
        ))
      )}
      <Button size="sm" variant="secondary" onClick={onClose}>
        {t('playbook.versions.collapse')}
      </Button>
    </div>
  );
}

export default PlaybookVersionsPanel;
