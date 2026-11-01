/** PlaybookVersionsPanel — 规程版本历史（2026-11-01，从 PlaybookCard 拆出）。 */
import type { PlaybookVersion } from '../../shared/api/playbookApi';
import { Button } from '../../shared/ui/Button';

export interface PlaybookVersionsPanelProps {
  versions: PlaybookVersion[];
  onClose: () => void;
}

export function PlaybookVersionsPanel({ versions, onClose }: PlaybookVersionsPanelProps) {
  return (
    <div
      className="space-y-1 rounded-md border border-border p-2 text-xs"
      data-testid="playbook-versions"
    >
      <div className="font-medium text-foreground">版本历史</div>
      {versions.length === 0 ? (
        <div className="text-muted-foreground">暂无版本记录</div>
      ) : (
        versions.map((item) => (
          <div key={item.version} className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground">
              v{item.version} · {item.source} · {new Date(item.created_at).toLocaleString()}
            </span>
            {item.active && <span className="text-primary">当前</span>}
          </div>
        ))
      )}
      <Button size="sm" variant="secondary" onClick={onClose}>
        收起
      </Button>
    </div>
  );
}

export default PlaybookVersionsPanel;
