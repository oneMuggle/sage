/**
 * RuleConflictResolver — displays extraction conflicts and lets the user
 * choose which conflicting rule variants to keep.
 */

import type { WireDraftConflict } from '../../../shared/api/types/officeRulesTypes';

import type { DraftRule } from './ruleDraftStore';

export interface RuleConflictResolverProps {
  conflicts: WireDraftConflict[];
  rules: DraftRule[];
  onToggle: (tempId: string) => void;
}

export function RuleConflictResolver({ conflicts, rules, onToggle }: RuleConflictResolverProps) {
  if (conflicts.length === 0) return null;

  return (
    <div className="space-y-2" data-testid="rule-conflict-resolver">
      {conflicts.map((conflict) => {
        const conflictRules = rules.filter((r) => conflict.rule_ids.includes(r.tempId));
        if (conflictRules.length < 2) return null;

        return (
          <div
            key={conflict.kind}
            className="rounded-lg border border-yellow-300 bg-yellow-50/50 p-3"
          >
            <div className="text-xs font-medium text-yellow-800">⚠️ 冲突：{conflict.message}</div>
            <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
              {conflictRules.map((rule) => (
                <label
                  key={rule.tempId}
                  className={`flex cursor-pointer items-start gap-2 rounded border p-2 ${
                    rule.selected
                      ? 'border-yellow-400 bg-white'
                      : 'border-border bg-surface opacity-60'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={rule.selected}
                    onChange={() => onToggle(rule.tempId)}
                    className="mt-0.5"
                  />
                  <div className="min-w-0 text-xs">
                    <div className="font-medium">{rule.name}</div>
                    <div className="mt-0.5 text-text-secondary">
                      {Object.entries(rule.params)
                        .map(([k, v]) => `${k}=${String(v)}`)
                        .join(', ')}
                    </div>
                    <div className="mt-0.5 text-muted">
                      置信度 {Math.round(rule.confidence * 100)}%
                    </div>
                  </div>
                </label>
              ))}
            </div>
            <div className="mt-1.5 text-ui-2xs text-yellow-700">
              请勾选保留的版本（可只保留一个）
            </div>
          </div>
        );
      })}
    </div>
  );
}
