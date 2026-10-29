/**
 * 插件与技能 — 合并自原 PluginsTab + SkillsTab（2026-10-28 P1-b）。
 *
 * 页内子导航切换两个独立组件，避免在左侧 nav 中占据两项。
 * 子 tab 状态用 useState 管理，不持久化（切换成本低、无外链需求）。
 */
import { useState } from 'react';

import { useI18n } from '../../shared/lib/i18n';

import { PluginsTab } from './PluginsTab';
import { SkillsTab } from './SkillsTab';

type SubTab = 'plugins' | 'skills';

export function PluginsSkillsTab(): JSX.Element {
  const { t } = useI18n();
  const [sub, setSub] = useState<SubTab>('plugins');

  return (
    <div className="space-y-4">
      <div className="flex gap-1 border-b border-border" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={sub === 'plugins'}
          onClick={() => setSub('plugins')}
          className={`px-3 py-1.5 text-ui-sm border-b-2 transition-colors ${
            sub === 'plugins'
              ? 'border-primary text-primary font-medium'
              : 'border-transparent text-muted hover:text-text'
          }`}
        >
          {t('settings.tab.plugins')}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={sub === 'skills'}
          onClick={() => setSub('skills')}
          className={`px-3 py-1.5 text-ui-sm border-b-2 transition-colors ${
            sub === 'skills'
              ? 'border-primary text-primary font-medium'
              : 'border-transparent text-muted hover:text-text'
          }`}
        >
          {t('settings.tab.skills')}
        </button>
      </div>
      <div role="tabpanel">{sub === 'plugins' ? <PluginsTab /> : <SkillsTab />}</div>
    </div>
  );
}
