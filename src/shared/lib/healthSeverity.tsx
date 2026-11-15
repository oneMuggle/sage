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
    dot: 'bg-rose-500',
    text: 'text-rose-500',
    softBg: 'bg-rose-500/10',
    border: 'border-rose-500/25',
    badge: 'bg-rose-500/15 text-rose-500',
  },
  warning: {
    label: '关注',
    stateLabel: '需要关注',
    Icon: AlertCircle,
    dot: 'bg-amber-500',
    text: 'text-amber-500',
    softBg: 'bg-amber-500/10',
    border: 'border-amber-500/25',
    badge: 'bg-amber-500/15 text-amber-500',
  },
  ok: {
    label: '正常',
    stateLabel: '一切正常',
    Icon: CheckCircle2,
    dot: 'bg-emerald-500',
    text: 'text-emerald-500',
    softBg: 'bg-emerald-500/10',
    border: 'border-emerald-500/25',
    badge: 'bg-emerald-500/15 text-emerald-500',
  },
};

/** 展示顺序：风险优先。 */
export const SEVERITY_ORDER: HealthSeverity[] = ['critical', 'warning', 'ok'];
