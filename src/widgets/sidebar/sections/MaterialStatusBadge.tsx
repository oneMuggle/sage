import type { ProjectMaterial } from '../../../shared/api/projectApi';
import { useI18n } from '../../../shared/lib/i18n';

/** P3: 资料状态徽标——颜色映射 ready/pending/failed, 标签本地化 */
export function MaterialStatusBadge({ status }: { status: ProjectMaterial['status'] }) {
  const { t } = useI18n();
  const palette = {
    ready: 'bg-success/15 text-success border-success/30',
    pending_index: 'bg-muted/20 text-muted border-muted/30',
    failed: 'bg-warning/15 text-warning border-warning/30',
  } as const;
  const labelKey = {
    ready: 'sider.project.material_status_ready',
    pending_index: 'sider.project.material_status_pending',
    failed: 'sider.project.material_status_failed',
  } as const;
  return (
    <span
      data-testid={`project-material-status-${status}`}
      className={`shrink-0 px-1 py-px rounded border text-[9px] ${palette[status]}`}
    >
      {t(labelKey[status])}
    </span>
  );
}
