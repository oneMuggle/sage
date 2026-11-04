/**
 * PlaybookActivityPanel — 规程最近活动与使用统计（2026-11-02）。
 *
 * 展示后端 best-effort 埋点记录：最近事件流水 + 时间窗内的操作分布。
 * 埋点失败不影响规程主流程，因此这里只读不写，缺数据时降级为空态。
 */
import type { PlaybookEvent, PlaybookEventAggregate } from '../../shared/api/playbookApi';
import type { PlaybookTranslationKey } from '../../shared/lib/i18n/locales/zh/playbook';
import { Button } from '../../shared/ui/Button';

import { usePlaybookI18n } from './usePlaybookI18n';

/** 事件名 → 词典 key；与后端 `ALLOWED_EVENTS` 白名单一一对应。 */
const EVENT_LABEL_KEYS: Partial<Record<string, PlaybookTranslationKey>> = {
  bind: 'playbook.event.bind',
  unbind: 'playbook.event.unbind',
  audit: 'playbook.event.audit',
  audit_ai: 'playbook.event.audit_ai',
  author: 'playbook.event.author',
  actions_apply: 'playbook.event.actions_apply',
  stage_confirm: 'playbook.event.stage_confirm',
  import: 'playbook.event.import',
  export_json: 'playbook.event.export_json',
  export_md: 'playbook.event.export_md',
  export_agents: 'playbook.event.export_agents',
  export_wiki: 'playbook.event.export_wiki',
  library_save: 'playbook.event.library_save',
  library_delete: 'playbook.event.library_delete',
  library_export: 'playbook.event.library_export',
  batch_move: 'playbook.event.batch_move',
  undo_batch_move: 'playbook.event.undo_batch_move',
  cleanup_rules: 'playbook.event.cleanup_rules',
  exemption_grant: 'playbook.event.exemption_grant',
  exemption_revoke: 'playbook.event.exemption_revoke',
  manual_complete: 'playbook.event.manual_complete',
  update_state: 'playbook.event.update_state',
};

export interface PlaybookActivityPanelProps {
  events: PlaybookEvent[];
  aggregate: PlaybookEventAggregate | null;
  onClose: () => void;
}

export function PlaybookActivityPanel({
  events,
  aggregate,
  onClose,
}: PlaybookActivityPanelProps) {
  const { t, tf } = usePlaybookI18n();
  const labelFor = (event: string): string =>
    t(EVENT_LABEL_KEYS[event] ?? 'playbook.activity.unknownEvent');
  const counts = aggregate?.counts ?? {};
  const ranked = Object.entries(counts).sort((a, b) => b[1] - a[1]);

  return (
    <div
      className="space-y-2 rounded-md border border-border p-2 text-xs"
      data-testid="playbook-activity"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="font-medium text-foreground">{t('playbook.activity.title')}</div>
        {aggregate && (
          <div className="text-muted-foreground" data-testid="playbook-activity-summary">
            {tf('playbook.activity.summary', {
              days: aggregate.days,
              total: aggregate.total,
            })}
          </div>
        )}
      </div>

      {ranked.length > 0 && (
        <div className="space-y-1">
          <div className="text-muted-foreground">{t('playbook.activity.counts')}</div>
          <div className="flex flex-wrap gap-1">
            {ranked.map(([event, count]) => (
              <span
                key={event}
                className="rounded border border-border px-1.5 py-0.5 text-muted-foreground"
                data-testid={`playbook-activity-count-${event}`}
              >
                {labelFor(event)} × {count}
              </span>
            ))}
          </div>
        </div>
      )}

      {events.length === 0 ? (
        <div className="text-muted-foreground">{t('playbook.activity.empty')}</div>
      ) : (
        <div className="space-y-1">
          {events.map((item) => (
            <div
              key={item.id}
              className="flex items-center justify-between gap-2"
              data-testid={`playbook-activity-event-${item.id}`}
            >
              <span className="text-muted-foreground">
                {labelFor(item.event)}
                {item.stage ? ' · ' + tf('playbook.activity.stageLabel', { stage: item.stage }) : ''}
              </span>
              <span className="whitespace-nowrap text-muted-foreground">
                {new Date(item.created_at).toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      )}

      <Button size="sm" variant="secondary" onClick={onClose} data-testid="playbook-activity-close">
        {t('playbook.activity.collapse')}
      </Button>
    </div>
  );
}

export default PlaybookActivityPanel;
