import { useState } from 'react';

import { useI18n } from '../../shared/lib/i18n';

import { useTheme } from './ThemeProvider';

const PRESET_IDS = ['light', 'dark', 'ocean', 'forest', 'sunset'] as const;

export function ThemeSelector(): JSX.Element {
  const { t } = useI18n();
  const { active, setPreset, reset } = useTheme();
  const [open, setOpen] = useState(false);

  return (
    <div data-testid="theme-selector">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {t('theme.selector.title')}: {active.presetId}
      </button>
      {open && (
        <ul role="listbox" data-testid="theme-selector-listbox">
          {PRESET_IDS.map((id) => (
            <li
              key={id}
              role="option"
              aria-selected={active.presetId === id}
              onClick={() => {
                void setPreset(id);
                setOpen(false);
              }}
            >
              {t(`theme.presets.${id}.name`)}
            </li>
          ))}
          <li>
            <button
              type="button"
              onClick={() => {
                void reset();
                setOpen(false);
              }}
            >
              {t('theme.selector.reset')}
            </button>
          </li>
        </ul>
      )}
    </div>
  );
}
