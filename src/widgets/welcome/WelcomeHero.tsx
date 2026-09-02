import { ArrowLeft } from 'lucide-react';

import { useI18n } from '../../shared/lib/i18n';
import { BrandLogo } from '../../shared/ui';

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

      {/* U-Brand: 用 BrandLogo 替代 lucide Sparkles 占位；保留 welcome-avatar testid 给现有 e2e/快照测试用 */}
      <BrandLogo size="xl" testId="welcome-avatar" />

      <div>
        <h1 className="text-2xl font-semibold text-text mb-2">{t('welcome.hero.greeting')}</h1>
        <p className="text-sm text-text-tertiary">{t('welcome.hero.subtitle')}</p>
      </div>
    </div>
  );
}
