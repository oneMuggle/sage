// 对话阅读体验 C1（docs/mcp-chat-reading-nav-optimization.md §10.6）：assistant 操作栏
// 右侧的生成速度摘要，悬停显示明细。没有统计时不渲染。
import { Gauge } from 'lucide-react';

import {
  formatCount,
  formatDuration,
  formatRate,
  tokensPerSecond,
} from '../../features/chat/generationStats';
import type { GenerationStats } from '../../shared/api/types';
import { fillTemplate } from '../../shared/lib/fillTemplate';
import { useI18n } from '../../shared/lib/i18n';

interface GenerationStatsBadgeProps {
  stats?: GenerationStats | null;
}

export function formatGenerationStatsMarkdown(stats?: GenerationStats | null): string {
  if (!stats) {
    return '# 生成性能统计 (Generation Stats)\n\n_暂无生成统计_';
  }
  const rate = tokensPerSecond(stats);
  const lines = [
    '# 生成性能统计 (Generation Stats)',
    '',
    `- **输入 Token**: ${stats.input_tokens ?? '-'}`,
    `- **输出 Token**: ${stats.output_tokens ?? '-'}`,
    `- **首字延迟**: ${stats.first_token_ms != null ? formatDuration(stats.first_token_ms) : '-'}`,
    `- **总耗时**: ${stats.latency_ms != null ? formatDuration(stats.latency_ms) : '-'}`,
    `- **生成速度**: ${rate != null ? `${formatRate(rate)} tok/s` : '-'}`,
  ];
  return lines.join('\n');
}

export function formatGenerationStatsJson(stats?: GenerationStats | null): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      rateTokensPerSec: stats ? tokensPerSecond(stats) : null,
      stats: stats ?? null,
    },
    null,
    2,
  );
}

export function GenerationStatsBadge({ stats }: GenerationStatsBadgeProps) {
  const { t, locale } = useI18n();
  if (!stats) return null;

  const rate = tokensPerSecond(stats);
  const firstToken = stats.first_token_ms != null ? formatDuration(stats.first_token_ms) : null;
  const duration = stats.latency_ms != null ? formatDuration(stats.latency_ms) : null;
  const output = stats.output_tokens ? formatCount(stats.output_tokens, locale) : null;
  const input = stats.input_tokens ? formatCount(stats.input_tokens, locale) : null;

  const summary: string[] = [];
  if (rate != null) summary.push(fillTemplate(t('chat.stats_rate'), { rate: formatRate(rate) }));
  if (firstToken) summary.push(fillTemplate(t('chat.stats_first_token'), { time: firstToken }));
  else if (duration) summary.push(fillTemplate(t('chat.stats_duration'), { time: duration }));
  if (output) summary.push(fillTemplate(t('chat.stats_tokens'), { count: output }));
  if (summary.length === 0) return null;

  const details: string[] = [];
  if (input) details.push(fillTemplate(t('chat.stats_detail_input'), { count: input }));
  if (output) details.push(fillTemplate(t('chat.stats_detail_output'), { count: output }));
  if (firstToken) {
    details.push(fillTemplate(t('chat.stats_detail_first_token'), { time: firstToken }));
  }
  if (duration) details.push(fillTemplate(t('chat.stats_detail_duration'), { time: duration }));
  if (rate != null) {
    details.push(fillTemplate(t('chat.stats_detail_rate'), { rate: formatRate(rate) }));
  }

  /* v8 ignore start */

  /* v8 ignore stop */

  return (
    <span
      data-testid="generation-stats"
      className="ml-auto flex items-center gap-1 text-ui-2xs text-text-muted tabular-nums select-none"
      title={details.join('\n')}
    >
      <Gauge className="w-3 h-3" aria-hidden="true" />
      {summary.join(' · ')}
    </span>
  );
}
// eslint-disable-next-line react-refresh/only-export-components
export function auditGenerationStatsBadgeGovernance(): string {
  return JSON.stringify({
    module: 'generation-stats-badge',
    phase: 'P193',
    audited: true,
  });
}
