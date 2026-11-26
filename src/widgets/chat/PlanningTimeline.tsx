// src/widgets/chat/PlanningTimeline.tsx
import { ChevronDown } from 'lucide-react';
import { useState } from 'react';

import {
  selectSessionSlots,
  useChatStreamStore,
} from '../../features/send-message/chatStreamStore';
import { isPlanningActive, type PlanStageState } from '../../features/send-message/planProgress';

interface PlanningTimelineProps {
  sessionId: string | null | undefined;
}

const STAGE_LABELS: Record<PlanStageState['stage'], string> = {
  mode_classify: '识别处理方式',
  complexity_classify: '评估任务复杂度',
  clarify: '澄清需求',
  scout: '事实侦察',
  scout_deep: '深度调研',
  decompose: '拆解任务',
};

const STATUS_DOT: Record<PlanStageState['status'], string> = {
  started: 'bg-primary animate-pulse',
  progress: 'bg-primary animate-pulse',
  done: 'bg-emerald-500',
  skipped: 'bg-muted',
  failed: 'bg-red-500',
};

export function PlanningTimeline({ sessionId }: PlanningTimelineProps) {
  const stages = useChatStreamStore((s) => selectSessionSlots(s, sessionId).planProgress);
  const [collapsed, setCollapsed] = useState(false);

  if (!stages || stages.length === 0) return null;

  const active = isPlanningActive(stages);
  const settled = stages.filter(
    (stage) => stage.status === 'done' || stage.status === 'skipped',
  ).length;

  return (
    <div
      data-testid="planning-timeline"
      aria-live="polite"
      className="mb-2 px-3 py-2 rounded-radius-sm border border-border bg-bg-subtle text-ui-xs leading-relaxed"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-text-muted">
          {active ? '规划中' : '规划完成'} · {settled}/{stages.length} 步
        </span>
        <button
          type="button"
          data-testid="planning-timeline-toggle"
          aria-expanded={!collapsed}
          aria-label={collapsed ? '展开规划进度' : '折叠规划进度'}
          onClick={() => setCollapsed((value) => !value)}
          className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-text-muted hover:text-text hover:bg-bg-hover transition-colors"
        >
          <span>{collapsed ? '展开' : '收起'}</span>
          <ChevronDown
            className={`w-3 h-3 transition-transform ${collapsed ? '' : 'rotate-180'}`}
          />
        </button>
      </div>

      {!collapsed && (
        <ol className="mt-1.5 space-y-1">
          {stages.map((stage) => (
            <li key={stage.stage} data-testid={`planning-stage-${stage.stage}`}>
              <div className="flex items-center gap-1.5">
                <span
                  className={`w-1.5 h-1.5 rounded-full ${STATUS_DOT[stage.status]}`}
                  aria-hidden="true"
                />
                <span className="font-medium">{STAGE_LABELS[stage.stage]}</span>
                {stage.status === 'skipped' && <span className="text-text-muted">已跳过</span>}
                {stage.status === 'failed' && <span className="text-red-500">失败</span>}
                {typeof stage.elapsedMs === 'number' && stage.elapsedMs > 0 && (
                  <span className="text-text-muted">{(stage.elapsedMs / 1000).toFixed(1)}s</span>
                )}
              </div>
              {stage.lines.length > 0 && (
                <ul className="ml-3 mt-0.5 space-y-0.5 text-text-muted">
                  {stage.lines.slice(-3).map((line, index) => (
                    <li key={`${line.kind}-${index}`} className="truncate">
                      {line.text}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
