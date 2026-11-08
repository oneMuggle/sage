import { ChevronDown, ChevronRight, CheckCircle2, ArrowRight, HelpCircle, X } from 'lucide-react';
import { useState } from 'react';

import type { RecapResult } from '../../shared/api/types';
import { useI18n } from '../../shared/lib/i18n';

interface RecapCardProps {
  recap: RecapResult;
  onDismiss: () => void;
}

/**
 * Recap (2026-11-08): 会话进度总结卡片（对标 Claude Code /recap）。
 *
 * 可折叠展示 progress / decisions / nextSteps / openQuestions 四段；
 * 默认展开 progress 和 nextSteps，decisions/openQuestions 折叠以减少视觉噪音。
 */
export function RecapCard({ recap, onDismiss }: RecapCardProps) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    progress: true,
    decisions: false,
    nextSteps: true,
    openQuestions: Boolean(recap.openQuestions?.length),
  });

  const toggle = (key: string) =>
    setExpanded((prev) => ({ ...prev, [key]: !prev[key] }));

  return (
    <div
      data-testid="recap-card"
      className="mx-4 my-2 rounded-radius border border-border bg-bg-subtle overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 bg-bg-elevated border-b border-border">
        <CheckCircle2 className="w-4 h-4 text-primary flex-shrink-0" />
        <span className="text-sm font-medium text-text-primary">
          {t('recap.title')}
        </span>
        <button
          type="button"
          data-testid="recap-card-dismiss"
          onClick={onDismiss}
          aria-label={t('recap.dismiss')}
          className="ml-auto p-1 rounded hover:bg-bg-hover text-text-secondary"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Sections */}
      <div className="divide-y divide-border">
        <Section
          label={t('recap.progress')}
          icon={<CheckCircle2 className="w-3.5 h-3.5 text-primary" />}
          expanded={expanded.progress}
          onToggle={() => toggle('progress')}
        >
          <p className="text-sm text-text-primary leading-relaxed">{recap.progress}</p>
        </Section>

        {recap.decisions.length > 0 && (
          <Section
            label={t('recap.decisions')}
            icon={<CheckCircle2 className="w-3.5 h-3.5 text-success" />}
            count={recap.decisions.length}
            expanded={expanded.decisions}
            onToggle={() => toggle('decisions')}
          >
            <ul className="space-y-1">
              {recap.decisions.map((d, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-text-primary">
                  <span className="text-success mt-0.5 flex-shrink-0">•</span>
                  <span>{d}</span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {recap.nextSteps.length > 0 && (
          <Section
            label={t('recap.next_steps')}
            icon={<ArrowRight className="w-3.5 h-3.5 text-info" />}
            count={recap.nextSteps.length}
            expanded={expanded.nextSteps}
            onToggle={() => toggle('nextSteps')}
          >
            <ol className="space-y-1 list-decimal list-inside">
              {recap.nextSteps.map((s, i) => (
                <li key={i} className="text-sm text-text-primary">{s}</li>
              ))}
            </ol>
          </Section>
        )}

        {recap.openQuestions && recap.openQuestions.length > 0 && (
          <Section
            label={t('recap.open_questions')}
            icon={<HelpCircle className="w-3.5 h-3.5 text-warning" />}
            count={recap.openQuestions.length}
            expanded={expanded.openQuestions}
            onToggle={() => toggle('openQuestions')}
          >
            <ul className="space-y-1">
              {recap.openQuestions.map((q, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-text-primary">
                  <span className="text-warning mt-0.5 flex-shrink-0">?</span>
                  <span>{q}</span>
                </li>
              ))}
            </ul>
          </Section>
        )}
      </div>
    </div>
  );
}

function Section({
  label,
  icon,
  count,
  expanded,
  onToggle,
  children,
}: {
  label: string;
  icon: React.ReactNode;
  count?: number;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        className="flex items-center gap-2 w-full px-3 py-2 text-left hover:bg-bg-hover/50 transition-colors"
      >
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5 text-text-secondary flex-shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-text-secondary flex-shrink-0" />
        )}
        {icon}
        <span className="text-xs font-medium text-text-secondary uppercase tracking-wide">
          {label}
        </span>
        {count !== undefined && (
          <span className="text-xs text-text-tertiary bg-bg-subtle px-1.5 rounded-radius-sm">
            {count}
          </span>
        )}
      </button>
      {expanded && <div className="px-3 pb-2 pl-8">{children}</div>}
    </div>
  );
}
