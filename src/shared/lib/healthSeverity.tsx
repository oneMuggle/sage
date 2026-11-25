import { AlertCircle, AlertTriangle, CheckCircle2, type LucideIcon } from 'lucide-react';

/** 项目健康严重度 → 统一视觉 token（HealthDashboard / HealthSummaryCard 共用）。 */
export type HealthSeverity = 'ok' | 'warning' | 'critical';

export interface SeverityToken {
  /** 简短等级名：风险 / 关注 / 正常 */
  label: string;
  /** 状态句：存在风险 / 需要关注 / 一切正常 */
  stateLabel: string;
  Icon: LucideIcon;
  dot: string;
  text: string;
  softBg: string;
  border: string;
  badge: string;
}

export const SEVERITY_TOKENS: Record<HealthSeverity, SeverityToken> = {
  critical: {
    label: '风险',
    stateLabel: '存在风险',
    Icon: AlertTriangle,
    dot: 'bg-error',
    text: 'text-error',
    softBg: 'bg-error/10',
    border: 'border-error/25',
    badge: 'bg-error/15 text-error',
  },
  warning: {
    label: '关注',
    stateLabel: '需要关注',
    Icon: AlertCircle,
    dot: 'bg-warning',
    text: 'text-warning',
    softBg: 'bg-warning/10',
    border: 'border-warning/25',
    badge: 'bg-warning/15 text-warning',
  },
  ok: {
    label: '正常',
    stateLabel: '一切正常',
    Icon: CheckCircle2,
    dot: 'bg-success',
    text: 'text-success',
    softBg: 'bg-success/10',
    border: 'border-success/25',
    badge: 'bg-success/15 text-success',
  },
};

/** 展示顺序：风险优先。 */
export const SEVERITY_ORDER: HealthSeverity[] = ['critical', 'warning', 'ok'];
