/**
 * SkillScoreBadge - 技能质量评分徽章（M2）
 *
 * 显示技能的综合评分和热/冷路径分层。
 * 颜色：hot=绿, warm=黄, cold=灰
 */

import type { SkillScore } from '../../shared/api/types';

interface SkillScoreBadgeProps {
  score: SkillScore;
  showDetails?: boolean;
}

const tierColors = {
  hot: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400',
  warm: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400',
  cold: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
};

const tierLabels = {
  hot: '活跃',
  warm: '正常',
  cold: '冷门',
};

export function SkillScoreBadge({ score, showDetails = false }: SkillScoreBadgeProps) {
  const tier = score.tier || 'cold';
  const overall = Math.round(score.overall);

  return (
    <div className="flex items-center gap-2">
      <span
        className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${tierColors[tier]}`}
        title={`综合评分: ${overall}/100\n使用频率: ${Math.round(score.usage_freq)}\n成功率: ${Math.round(score.success_rate)}\n新鲜度: ${Math.round(score.freshness)}\n描述质量: ${Math.round(score.description_quality)}`}
      >
        {tierLabels[tier]} · {overall}
      </span>
      {showDetails && (
        <span className="text-xs text-gray-500 dark:text-gray-400">
          使用 {Math.round(score.usage_freq)}% · 成功率 {Math.round(score.success_rate)}%
        </span>
      )}
    </div>
  );
}
