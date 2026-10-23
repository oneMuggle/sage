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
      className={`shrink-0 px-1 py-px rounded border text-ui-xs ${palette[status]}`}
    >
      {t(labelKey[status])}
    </span>
  );
}

export interface MaterialStatusBadgeAuditInput {
  status: string;
  hasLabelText: boolean;
  hasAccessibleTitle: boolean;
}

export interface MaterialStatusBadgeAuditReport {
  recognizedStatus: boolean;
  status: string;
  healthy: boolean;
  issueCodes: string[];
}

// eslint-disable-next-line react-refresh/only-export-components
export function evaluateMaterialStatusBadgeGovernanceAudit(
  input: MaterialStatusBadgeAuditInput,
): MaterialStatusBadgeAuditReport {
  const issueCodes: string[] = [];
  const validStatuses = new Set(['indexed', 'indexing', 'failed', 'pending', 'ready', 'stale']);
  const normalizedStatus = input.status.trim();
  const recognizedStatus = validStatuses.has(normalizedStatus);
  if (!recognizedStatus) {
    issueCodes.push('MATERIAL_STATUS_UNRECOGNIZED');
  }
  if (!input.hasLabelText) {
    issueCodes.push('MATERIAL_STATUS_LABEL_MISSING');
  }
  if (!input.hasAccessibleTitle) {
    issueCodes.push('MATERIAL_STATUS_TITLE_MISSING');
  }
  return {
    recognizedStatus,
    status: normalizedStatus,
    healthy: issueCodes.length === 0,
    issueCodes,
  };
}
