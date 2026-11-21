/**
 * DesignProgressStrip — 生成阶段进度条（composing → generating → linting …）。
 */
import { Loader2 } from 'lucide-react';

import type { TranslationKey } from '../../shared/lib/i18n';
import { useI18n } from '../../shared/lib/i18n';

const STAGE_KEYS: Record<string, TranslationKey> = {
  idle: 'design.stage.idle',
  starting: 'design.stage.starting',
  composing: 'design.stage.composing',
  generating: 'design.stage.generating',
  linting: 'design.stage.linting',
  saving: 'design.stage.saving',
  complete: 'design.stage.complete',
  error: 'design.stage.error',
};

interface DesignProgressStripProps {
  stage: string;
}

export function DesignProgressStrip({ stage }: DesignProgressStripProps) {
  const { t } = useI18n();
  const key = STAGE_KEYS[stage];
  return (
    <div className="mx-5 mt-2 flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-1.5 text-ui-xs text-text-secondary">
      <Loader2 className="h-3 w-3 animate-spin" />
      <span>{key ? t(key) : stage}</span>
    </div>
  );
}
