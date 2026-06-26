import { ArrowLeft, Sparkles } from 'lucide-react';

import { useI18n } from '../../shared/lib/i18n';

interface WelcomeHeroProps {
  onBack?: () => void;
}

export function WelcomeHero({ onBack }: WelcomeHeroProps) {
  const { t } = useI18n();

  return (
    <div className="flex flex-col items-center text-center space-y-6">
      {onBack && (
        <button
          type="button"
          onClick={onBack}
          className="self-start inline-flex items-center gap-1 text-xs text-text-secondary hover:text-text transition-colors"
          aria-label={t('welcome.hero.back')}
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>{t('welcome.hero.back')}</span>
        </button>
      )}

      <div
        data-testid="welcome-avatar"
        className="w-16 h-16 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-lg"
      >
        <Sparkles className="w-8 h-8 text-white" />
      </div>

      <div>
        <h1 className="text-2xl font-semibold text-text mb-2">{t('welcome.hero.greeting')}</h1>
        <p className="text-sm text-text-tertiary">{t('welcome.hero.subtitle')}</p>
      </div>
    </div>
  );
}
