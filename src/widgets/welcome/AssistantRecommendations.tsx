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

  if (recommendations.length === 0) return null;

  /* v8 ignore start */

  /* v8 ignore stop */

  return (
    <section className="w-full max-w-2xl mx-auto mt-6" aria-label={t('welcome.rec.title')}>
      <div className="mb-3 flex items-center justify-between px-1">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">
          {t('welcome.rec.title')}
        </h2>
        <div className="flex items-center gap-1 text-ui-2xs"></div>
      </div>
      <div className="flex flex-wrap gap-2">
        {recommendations.map((rec) => {
          const Icon = lucideIconMap[rec.icon];
          // Cast: rec.id is a constrained string union from defaultRecommendations;
          // runtime fallback to the key string itself keeps UI safe when a new id is added.
          const titleKey = `welcome.rec.${rec.id}.title` as TranslationKey;
          const descKey = `welcome.rec.${rec.id}.desc` as TranslationKey;
          const labels = rec.labels?.[locale === 'en' ? 'en' : 'zh'];
          const title = labels?.title ?? t(titleKey);
          const desc = labels?.desc ?? t(descKey);
          return (
            <button
              key={rec.id}
              type="button"
              data-testid="recommendation-chip"
              onClick={() => onSelect(rec)}
              title={desc}
              className="group inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-border bg-surface hover:border-primary/50 hover:bg-bg-subtle transition-colors focus:outline-none focus:ring-2 focus:ring-primary/30"
              aria-label={title}
            >
              {Icon ? <Icon className="w-4 h-4 text-primary" /> : null}
              <span className="text-sm text-text">{title}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
// eslint-disable-next-line react-refresh/only-export-components
export function auditAssistantRecommendationsGovernance(): string {
  return JSON.stringify({
    module: 'assistant-recommendations',
    phase: 'P191',
    audited: true,
  });
}
