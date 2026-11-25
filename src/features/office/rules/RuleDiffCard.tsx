/**
 * RuleDiffCard — one AI refine action rendered as a reviewable diff.
 *
 * add:     green "+ rule" card with the proposed rule fields
 * modify:  before → after for each changed field
 * delete:  red "− rule" card
 * explain: plain assistant text (no accept/reject)
 */

import type { WireRefineAction } from '../../../shared/api/types/officeRulesTypes';

import type { DraftRule } from './ruleDraftStore';

export interface RuleDiffCardProps {
  action: WireRefineAction;
  /** The current draft rule the action targets (for before values). */
  currentRule?: DraftRule;
  onAccept: () => void;
  onReject: () => void;
}

function ParamLine({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="flex gap-1 text-[11px]">
      <span className="text-muted">{label}:</span>
      <span className="text-text">{String(value)}</span>
    </div>
  );
}

export function RuleDiffCard({ action, currentRule, onAccept, onReject }: RuleDiffCardProps) {
  if (action.type === 'explain') {
    return (
      <div className="rounded-md border border-border bg-surface px-3 py-2 text-xs text-text">
        {action.explanation}
      </div>
    );
  }

  const isDelete = action.type === 'delete';
  const isAdd = action.type === 'add';
  const header = isAdd
    ? '＋ AI 建议新增规则'
    : isDelete
      ? '－ AI 建议删除规则'
      : '～ AI 建议修改规则';
  const headerColor = isAdd ? 'text-green-700' : isDelete ? 'text-red-600' : 'text-blue-700';
  const borderColor = isAdd ? 'border-green-300' : isDelete ? 'border-red-300' : 'border-blue-300';

  const patch = action.patch ?? {};
  const addedRule = action.rule;

  return (
    <div
      className={`rounded-md border ${borderColor} bg-white px-3 py-2`}
      data-testid="rule-diff-card"
    >
      <div className={`text-xs font-medium ${headerColor}`}>{header}</div>

      {action.explanation && (
        <div className="mt-0.5 text-[11px] text-text-secondary">{action.explanation}</div>
      )}

      {isAdd && addedRule && (
        <div className="mt-1 space-y-0.5">
          <div className="text-xs font-medium">{addedRule.name}</div>
          {addedRule.params &&
            Object.entries(addedRule.params).map(([k, v]) => (
              <ParamLine key={k} label={k} value={v} />
            ))}
          {addedRule.description && (
            <div className="text-[11px] text-muted">{addedRule.description}</div>
          )}
        </div>
      )}

      {isDelete && (
        <div className="mt-1">
          <span className="text-xs line-through text-text-secondary">
            {currentRule?.name ?? action.temp_id}
          </span>
        </div>
      )}

      {action.type === 'modify' && (
        <div className="mt-1 space-y-1">
          {currentRule && <div className="text-xs font-medium">{currentRule.name}</div>}
          {patch.name !== undefined && (
            <div className="text-[11px]">
              <span className="text-red-500 line-through">{currentRule?.name}</span>
              {' → '}
              <span className="text-green-700">{patch.name}</span>
            </div>
          )}
          {patch.params !== undefined &&
            Object.entries(patch.params).map(([k, v]) => {
              const before = currentRule?.params?.[k];
              return (
                <div key={k} className="text-[11px]">
                  <span className="text-muted">{k}:</span>{' '}
                  <span className="text-red-500 line-through">{String(before ?? '(无)')}</span>
                  {' → '}
                  <span className="text-green-700">{String(v)}</span>
                </div>
              );
            })}
          {patch.severity !== undefined && currentRule && (
            <div className="text-[11px]">
              <span className="text-muted">severity:</span>{' '}
              <span className="text-red-500 line-through">{currentRule.severity}</span>
              {' → '}
              <span className="text-green-700">{patch.severity}</span>
            </div>
          )}
          {patch.ai_prompt !== undefined && (
            <div className="text-[11px] text-text-secondary">
              <span className="text-muted">ai_prompt:</span> {patch.ai_prompt}
            </div>
          )}
          {patch.description !== undefined && (
            <div className="text-[11px] text-text-secondary">
              <span className="text-muted">description:</span> {patch.description}
            </div>
          )}
        </div>
      )}

      <div className="mt-1.5 flex items-center gap-2">
        <button
          type="button"
          onClick={onAccept}
          className="rounded bg-green-600 px-2 py-0.5 text-[11px] text-white hover:bg-green-700"
        >
          接受
        </button>
        <button
          type="button"
          onClick={onReject}
          className="rounded border border-border px-2 py-0.5 text-[11px] text-text-secondary hover:bg-surface-hover"
        >
          拒绝
        </button>
      </div>
    </div>
  );
}
