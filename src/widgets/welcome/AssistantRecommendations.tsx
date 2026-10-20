import { useState } from 'react';

import {
  lucideIconMap,
  type AssistantRecommendation,
} from '../../entities/welcome/recommendations';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

interface AssistantRecommendationsProps {
  recommendations: AssistantRecommendation[];
  onSelect: (rec: AssistantRecommendation) => void;
}

export function formatRecommendationsMarkdown(
  recommendations: ReadonlyArray<AssistantRecommendation>,
): string {
  const lines = [
    '# 欢迎页推荐任务列表 (Assistant Recommendations)',
    '',
    `- **推荐总数**: ${recommendations.length}`,
  ];
  if (recommendations.length === 0) {
    lines.push('', '_暂无推荐任务_');
  } else {
    lines.push('', '## 推荐卡片');
    for (const rec of recommendations) {
      const zhTitle = rec.labels?.zh?.title || rec.id;
      lines.push(`- **${zhTitle}** (\`${rec.id}\`): ${rec.prompt}`);
    }
  }
  return lines.join('\n');
}

export function formatRecommendationsJson(
  recommendations: ReadonlyArray<AssistantRecommendation>,
): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      total: recommendations.length,
      recommendations,
    },
    null,
    2,
  );
}

export function AssistantRecommendations({
  recommendations,
  onSelect,
}: AssistantRecommendationsProps) {
  const { t, locale } = useI18n();
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  if (recommendations.length === 0) return null;

  /* v8 ignore start */
  const handleCopyMarkdown = async () => {
    try {
      setCopiedMd(true);
      await navigator.clipboard?.writeText(formatRecommendationsMarkdown(recommendations));
      setTimeout(() => setCopiedMd(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };

  const handleCopyJson = async () => {
    try {
      setCopiedJson(true);
      await navigator.clipboard?.writeText(formatRecommendationsJson(recommendations));
      setTimeout(() => setCopiedJson(false), 1500);
    } catch {
      // ignore clipboard errors
    }
  };
  /* v8 ignore stop */

  return (
    <section className="w-full max-w-2xl mx-auto mt-6" aria-label={t('welcome.rec.title')}>
      <div className="mb-3 flex items-center justify-between px-1">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">
          {t('welcome.rec.title')}
        </h2>
        <div className="flex items-center gap-1 text-ui-2xs">
          <span
            data-testid="recommendations-copy-md"
            onClick={() => void handleCopyMarkdown()}
            className="cursor-pointer rounded border border-border px-1.5 py-0.5 text-text-secondary hover:bg-bg-hover"
          >
            {copiedMd ? '已复制 MD' : '复制 MD'}
          </span>
          <span
            data-testid="recommendations-copy-json"
            onClick={() => void handleCopyJson()}
            className="cursor-pointer rounded border border-border px-1.5 py-0.5 text-text-secondary hover:bg-bg-hover"
          >
            {copiedJson ? '已复制 JSON' : '复制 JSON'}
          </span>
        </div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {recommendations.map((rec) => {
          const Icon = lucideIconMap[rec.icon];
          // Cast: rec.id is a constrained string union from defaultRecommendations;
          // runtime fallback to the key string itself keeps UI safe when a new id is added.
          const titleKey = `welcome.rec.${rec.id}.title` as TranslationKey;
          const descKey = `welcome.rec.${rec.id}.desc` as TranslationKey;
          const labels = rec.labels?.[locale === 'en' ? 'en' : 'zh'];
          return (
            <button
              key={rec.id}
              type="button"
              data-testid="recommendation-card"
              onClick={() => onSelect(rec)}
              className="group text-left p-4 rounded-radius-md border border-border bg-surface hover:border-primary/50 hover:-translate-y-0.5 hover:shadow-md transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-primary/30"
              aria-label={labels?.title ?? t(titleKey)}
            >
              <div
                className={`w-10 h-10 rounded-radius-sm flex items-center justify-center text-primary mb-2 ${rec.gradient}`}
              >
                {Icon ? <Icon className="w-5 h-5" /> : null}
              </div>
              <div className="text-sm font-medium text-text">{labels?.title ?? t(titleKey)}</div>
              <div className="text-xs text-text-tertiary mt-0.5 line-clamp-2">
                {labels?.desc ?? t(descKey)}
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}
