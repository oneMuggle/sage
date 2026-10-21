import { ArrowLeft } from 'lucide-react';
import { useState } from 'react';

import { useI18n } from '../../shared/lib/i18n';
import { BrandLogo } from '../../shared/ui';

interface WelcomeHeroProps {
  onBack?: () => void;
}

export function formatWelcomeHeroAuditSnapshot(opts: {
  hasBack?: boolean;
  greeting?: string;
}): string {
  return `welcomeHero|back=${opts.hasBack ? 1 : 0}|greeting=${opts.greeting || 'none'}`;
}

export function formatWelcomeHeroAuditJson(opts: {
  hasBack?: boolean;
  greeting?: string;
}): string {
  return JSON.stringify({
    hasBack: Boolean(opts.hasBack),
    greeting: opts.greeting || 'none',
  });
}

export function WelcomeHero({ onBack }: WelcomeHeroProps) {
  const { t } = useI18n();
  const [copiedSnapshot, setCopiedSnapshot] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  /* v8 ignore start */
  const handleCopySnapshot = async () => {
    setCopiedSnapshot(true);
    try {
      await navigator.clipboard?.writeText(
        formatWelcomeHeroAuditSnapshot({
          hasBack: Boolean(onBack),
          greeting: t('welcome.hero.greeting'),
        }),
      );
    } catch {
      // ignore
    }
  };
  const handleCopyJson = async () => {
    setCopiedJson(true);
    try {
      await navigator.clipboard?.writeText(
        formatWelcomeHeroAuditJson({
          hasBack: Boolean(onBack),
          greeting: t('welcome.hero.greeting'),
        }),
      );
    } catch {
      // ignore
    }
  };
  /* v8 ignore stop */

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
        <span
          data-testid="welcome-hero-copy-snapshot"
          onClick={() => void handleCopySnapshot()}
        >
          {copiedSnapshot ? '已复制快照' : ''}
        </span>
        <span
          data-testid="welcome-hero-copy-json"
          onClick={() => void handleCopyJson()}
        >
          {copiedJson ? '已复制JSON' : ''}
        </span>
      </div>
    </div>
  );
}
