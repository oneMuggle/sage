// src/features/send-message/planProgress.ts
import type {
  PlanProgressItem,
  PlanProgressStage,
} from '../../shared/api/types/chatAndEventTypes';

export interface PlanStageLine {
  kind: PlanProgressItem['kind'];
  text: string;
}

export interface PlanStageState {
  stage: PlanProgressStage;
  status: PlanProgressItem['status'];
  lines: PlanStageLine[];
  elapsedMs?: number;
}

export const PLAN_STAGE_ORDER: PlanProgressStage[] = [
  'mode_classify',
  'complexity_classify',
  'clarify',
  'scout',
  'scout_deep',
  'decompose',
];

const MAX_LINES_PER_STAGE = 20;
const MAX_TEXT_LENGTH = 240;

function trimText(text: string): string {
  const trimmed = text.trim();
  return trimmed.length > MAX_TEXT_LENGTH
    ? `${trimmed.slice(0, MAX_TEXT_LENGTH)}…`
    : trimmed;
}

export function reducePlanProgress(
  prev: PlanStageState[] | null,
  item: PlanProgressItem,
): PlanStageState[] {
  const current = prev ?? [];
  const index = current.findIndex((stage) => stage.stage === item.stage);
  const base: PlanStageState =
    index >= 0
      ? current[index]
      : { stage: item.stage, status: 'started', lines: [] };

  const text = item.text ? trimText(item.text) : '';
  const lastLine = base.lines[base.lines.length - 1];
  const shouldAppend =
    text.length > 0 && item.kind !== 'heartbeat' && lastLine?.text !== text;

  const lines = shouldAppend
    ? [...base.lines, { kind: item.kind, text }].slice(-MAX_LINES_PER_STAGE)
    : base.lines;

  const next: PlanStageState = {
    stage: base.stage,
    status: item.status,
    lines,
    elapsedMs: item.elapsed_ms ?? base.elapsedMs,
  };

  const merged =
    index >= 0
      ? current.map((stage, i) => (i === index ? next : stage))
      : [...current, next];

  return [...merged].sort(
    (a, b) => PLAN_STAGE_ORDER.indexOf(a.stage) - PLAN_STAGE_ORDER.indexOf(b.stage),
  );
}

export function isPlanningActive(stages: PlanStageState[] | null): boolean {
  if (!stages || stages.length === 0) return false;
  return stages.some((stage) => stage.status === 'started' || stage.status === 'progress');
}
