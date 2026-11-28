// src/features/send-message/planProgress.ts
import type {
  PlanProgressItem,
  PlanProgressStage,
  ScoutFact,
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
  /**
   * 2026-11-27: scout 阶段解析出的结构化事实清单（实时下发）。
   * 渲染职责在「事实侦察」折叠块（FactReconBlock）；这里只做形状校验
   * 与容量兜底 —— 事实正文**不截断**，用户要能核对内容是否完整。
   */
  facts?: ScoutFact[];
  /** 后端因条数超上限而截断了事实清单时为 true */
  factsTruncated?: boolean;
}

export const PLAN_STAGE_ORDER: PlanProgressStage[] = [
  'mode_classify',
  'complexity_classify',
  'clarify',
  'scout',
  'scout_deep',
  'decompose',
];

const DEFAULT_MAX_LINES_PER_STAGE = 20;
const DEFAULT_MAX_TEXT_LENGTH = 240;
// scout 的过程行整体移交「侦察过程」二级折叠展示 —— 上限放宽，避免丢过程。
const SCOUT_MAX_LINES_PER_STAGE = 60;
const SCOUT_MAX_TEXT_LENGTH = 500;
/** 事实条数兜底（后端 scout 上限 12 条，这里只是防御）。 */
const MAX_FACTS_PER_STAGE = 60;
/** 与后端 SCOUT_FACT_MAX_CHARS 对齐（= 上游 raw 上限，生产路径永不触发；
 *  仅作畸形载荷兜底）。 */
const MAX_FACT_TEXT_LENGTH = 4000;
/** 与后端 SCOUT_SOURCE_MAX_CHARS 对齐。 */
const MAX_FACT_SOURCE_LENGTH = 120;

function limitsFor(stage: PlanProgressStage): { maxLines: number; maxText: number } {
  return stage === 'scout'
    ? { maxLines: SCOUT_MAX_LINES_PER_STAGE, maxText: SCOUT_MAX_TEXT_LENGTH }
    : { maxLines: DEFAULT_MAX_LINES_PER_STAGE, maxText: DEFAULT_MAX_TEXT_LENGTH };
}

function trimText(text: string, maxLength: number): string {
  const trimmed = text.trim();
  return trimmed.length > maxLength ? `${trimmed.slice(0, maxLength)}…` : trimmed;
}

/**
 * 从 plan_progress 事件的 detail 里解析结构化事实清单。
 *
 * 保守策略（与后端 parser 同取向）：只认数组 + 逐项 `text` 为字符串，
 * 非法项直接丢弃；**不截断正文** —— 用户的诉求正是核对事实是否完整。
 */
export function parseScoutFacts(detail: Record<string, unknown> | undefined): ScoutFact[] {
  const raw = detail?.facts;
  if (!Array.isArray(raw)) return [];
  const facts: ScoutFact[] = [];
  for (const entry of raw) {
    if (facts.length >= MAX_FACTS_PER_STAGE) break;
    if (!entry || typeof entry !== 'object') continue;
    const record = entry as { text?: unknown; source?: unknown };
    if (typeof record.text !== 'string') continue;
    const text = record.text.trim();
    if (!text) continue;
    const source = typeof record.source === 'string' ? record.source.trim() : '';
    facts.push({
      text:
        text.length > MAX_FACT_TEXT_LENGTH
          ? `${text.slice(0, MAX_FACT_TEXT_LENGTH)}…`
          : text,
      source:
        source.length > MAX_FACT_SOURCE_LENGTH
          ? source.slice(0, MAX_FACT_SOURCE_LENGTH)
          : source,
    });
  }
  return facts;
}

export function reducePlanProgress(
  prev: PlanStageState[] | null,
  item: PlanProgressItem,
): PlanStageState[] {
  const current = prev ?? [];
  const index = current.findIndex((stage) => stage.stage === item.stage);
  const base: PlanStageState =
    index >= 0 ? current[index] : { stage: item.stage, status: 'started', lines: [] };

  const { maxLines, maxText } = limitsFor(item.stage);
  const text = item.text ? trimText(item.text, maxText) : '';
  const lastLine = base.lines[base.lines.length - 1];
  const shouldAppend = text.length > 0 && item.kind !== 'heartbeat' && lastLine?.text !== text;

  const lines = shouldAppend
    ? [...base.lines, { kind: item.kind, text }].slice(-maxLines)
    : base.lines;

  const detailFacts =
    item.stage === 'scout' && item.detail ? parseScoutFacts(item.detail) : undefined;

  const next: PlanStageState = {
    stage: base.stage,
    status: item.status,
    lines,
    elapsedMs: item.elapsed_ms ?? base.elapsedMs,
    ...(detailFacts && detailFacts.length > 0
      ? {
          facts: detailFacts,
          // 单调合并：后续事件缺 truncated 字段时不得把已置位的 true 抹掉。
          factsTruncated: base.factsTruncated === true || item.detail?.truncated === true,
        }
      : base.facts
        ? { facts: base.facts, factsTruncated: base.factsTruncated }
        : {}),
  };

  const merged =
    index >= 0 ? current.map((stage, i) => (i === index ? next : stage)) : [...current, next];

  return [...merged].sort(
    (a, b) => PLAN_STAGE_ORDER.indexOf(a.stage) - PLAN_STAGE_ORDER.indexOf(b.stage),
  );
}

export function isPlanningActive(stages: PlanStageState[] | null): boolean {
  if (!stages || stages.length === 0) return false;
  return stages.some((stage) => stage.status === 'started' || stage.status === 'progress');
}
