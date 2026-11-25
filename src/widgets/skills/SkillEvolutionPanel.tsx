/**
 * SkillEvolutionPanel - 技能进化建议面板（M4）
 *
 * 展示基于执行反馈自动触发的技能优化建议。
 * 用户可审阅、批准或拒绝每条建议。
 */

import { useState } from 'react';

import type { EvolutionProposal } from '../../shared/api/types';

interface SkillEvolutionPanelProps {
  proposals: EvolutionProposal[];
  onApprove?: (proposal: EvolutionProposal) => void;
  onReject?: (proposal: EvolutionProposal) => void;
}

const triggerLabels: Record<string, string> = {
  low_success_rate: '成功率低',
  low_satisfaction: '满意度低',
  high_token_cost: '成本过高',
  frequent_merge: '频繁共现',
};

const typeLabels: Record<string, string> = {
  revise_description: '修订描述',
  revise_content: '修订内容',
  merge: '合并技能',
  archive: '归档',
};

export function SkillEvolutionPanel({
  proposals,
  onApprove,
  onReject,
}: SkillEvolutionPanelProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  if (proposals.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 p-4 text-center text-sm text-gray-500 dark:border-gray-700 dark:text-gray-400">
        暂无进化建议。技能健康状况良好。
      </div>
    );
  }

  const toggleExpand = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300">
        进化建议 ({proposals.length})
      </h3>
      {proposals.map((proposal, idx) => {
        const key = `${proposal.skill_name}-${proposal.trigger}-${idx}`;
        const isExpanded = expanded.has(key);
        return (
          <div
            key={key}
            className="rounded-lg border border-yellow-200 bg-yellow-50 p-3 dark:border-yellow-800 dark:bg-yellow-900/20"
          >
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm">{proposal.skill_name}</span>
                  <span className="rounded-full bg-yellow-200 px-2 py-0.5 text-xs text-yellow-800 dark:bg-yellow-800 dark:text-yellow-200">
                    {triggerLabels[proposal.trigger] || proposal.trigger}
                  </span>
                  <span className="rounded-full bg-gray-200 px-2 py-0.5 text-xs text-gray-700 dark:bg-gray-700 dark:text-gray-300">
                    {typeLabels[proposal.evolution_type] || proposal.evolution_type}
                  </span>
                </div>
                <p className="mt-1 text-xs text-gray-600 dark:text-gray-400">
                  {proposal.reason}
                </p>
                {isExpanded && proposal.stats && (
                  <pre className="mt-2 rounded bg-gray-100 p-2 text-xs text-gray-600 dark:bg-gray-800 dark:text-gray-400">
                    {JSON.stringify(proposal.stats, null, 2)}
                  </pre>
                )}
              </div>
              <div className="ml-2 flex items-center gap-1">
                <button
                  type="button"
                  className="rounded px-2 py-1 text-xs text-gray-500 hover:bg-gray-200 dark:hover:bg-gray-700"
                  onClick={() => toggleExpand(key)}
                >
                  {isExpanded ? '收起' : '详情'}
                </button>
                {onApprove && (
                  <button
                    type="button"
                    className="rounded bg-green-600 px-2 py-1 text-xs text-white hover:bg-green-700"
                    onClick={() => onApprove(proposal)}
                  >
                    批准
                  </button>
                )}
                {onReject && (
                  <button
                    type="button"
                    className="rounded bg-gray-400 px-2 py-1 text-xs text-white hover:bg-gray-500"
                    onClick={() => onReject(proposal)}
                  >
                    拒绝
                  </button>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
