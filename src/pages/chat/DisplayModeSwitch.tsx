import { Brain, ChevronDown } from 'lucide-react';
import { useState } from 'react';

import { DISPLAY_MODE_VALUES, type DisplayMode } from '../../features/chat/displayMode/types';
import { useDisplayMode } from '../../features/chat/displayMode/useDisplayMode';
import { useI18n } from '../../shared/lib/i18n';

interface DisplayModeSwitchProps {
  sessionId: string | null;
}

const MODE_LABELS = {
  detail: 'chat.displayMode.detail',
  trace: 'chat.displayMode.trace',
  result: 'chat.displayMode.result',
} as const satisfies Record<DisplayMode, string>;

export function DisplayModeSwitch({ sessionId }: DisplayModeSwitchProps) {
  const { t } = useI18n();
  const { mode, setSessionMode, clearSessionMode } = useDisplayMode(sessionId, null);
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="relative" data-testid="display-mode-switch">
      <button
        type="button"
        onClick={() => setMenuOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        aria-label={`${t('chat.displayMode.label')} · ${t(MODE_LABELS[mode])}`}
        data-testid="display-mode-button"
        className="flex items-center gap-1 px-2 py-1 text-xs border border-border rounded-radius-sm hover:bg-bg-hover transition-colors"
        title={t('chat.displayMode.label')}
      >
        <Brain className="w-3.5 h-3.5" aria-hidden />
        <span>{t(MODE_LABELS[mode])}</span>
        <ChevronDown className="w-3 h-3 opacity-60" aria-hidden />
      </button>

      {menuOpen && (
        <div
          role="menu"
          data-testid="display-mode-menu"
          className="absolute right-0 top-full mt-1 z-30 w-48 rounded border border-border bg-surface shadow-lg p-1"
        >
          {DISPLAY_MODE_VALUES.map((m) => {
            const active = m === mode;
            return (
              <button
                key={m}
                type="button"
                role="menuitemradio"
                aria-checked={active}
                data-testid={`display-mode-${m}`}
                onClick={() => {
                  setSessionMode(m);
                  setMenuOpen(false);
                }}
                className={`w-full text-left flex items-center gap-2 px-2 py-1.5 rounded text-xs hover:bg-bg-hover ${
                  active ? 'bg-primary/10 text-primary' : 'text-text'
                }`}
              >
                <Brain className="w-3.5 h-3.5 shrink-0" aria-hidden />
                <span>{t(MODE_LABELS[m])}</span>
              </button>
            );
          })}
          <div className="border-t border-border my-1" />
          <button
            type="button"
            role="menuitem"
            data-testid="display-mode-follow-global"
            onClick={() => {
              clearSessionMode();
              setMenuOpen(false);
            }}
            className="w-full text-left px-2 py-1.5 rounded text-xs text-text-secondary hover:bg-bg-hover"
          >
            {t('chat.displayMode.followGlobal')}
          </button>
        </div>
      )}
    </div>
  );
}
