import {
  lucideIconMap,
  type AssistantRecommendation,
} from '../../entities/welcome/recommendations';
import { useI18n, type TranslationKey } from '../../shared/lib/i18n';

interface AssistantRecommendationsProps {
  recommendations: AssistantRecommendation[];
  onSelect: (rec: AssistantRecommendation) => void;
}

export function AssistantRecommendations({
  recommendations,
  onSelect,
}: AssistantRecommendationsProps) {
  const { t } = useI18n();

  if (recommendations.length === 0) return null;

  return (
    <section className="w-full max-w-2xl mx-auto mt-6" aria-label={t('welcome.rec.title')}>
      <h2 className="text-xs font-semibold uppercase tracking-wide text-muted mb-3 px-1">
        {t('welcome.rec.title')}
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {recommendations.map((rec) => {
          const Icon = lucideIconMap[rec.icon];
          // rec.id is constrained to 'code' | 'search' | 'idea' from defaultRecommendations.
          // Template literal can't be statically verified, so cast to TranslationKey;
          // t() has a runtime fallback to the key string itself when missing.
          const titleKey = `welcome.rec.${rec.id}.title` as TranslationKey;
          const descKey = `welcome.rec.${rec.id}.desc` as TranslationKey;
          return (
            <button
              key={rec.id}
              type="button"
              data-testid="recommendation-card"
              onClick={() => onSelect(rec)}
              className="group text-left p-4 rounded-radius-md border border-border bg-surface hover:border-primary/50 hover:-translate-y-0.5 hover:shadow-md transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-primary/30"
              aria-label={t(titleKey)}
            >
              <div
                className={`w-10 h-10 rounded-radius-sm flex items-center justify-center text-text-inverse mb-2 ${rec.gradient}`}
              >
                {Icon ? <Icon className="w-5 h-5" /> : null}
              </div>
              <div className="text-sm font-medium text-text">{t(titleKey)}</div>
              <div className="text-xs text-text-tertiary mt-0.5 line-clamp-2">{t(descKey)}</div>
            </button>
          );
        })}
      </div>
    </section>
  );
}
