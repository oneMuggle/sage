/**
 * Desktop pet settings tab.
 *
 * Pet config is owned by the Electron main process (`pet-config.json`) and
 * accessed through the narrow `window.electronAPI.pet` bridge, so this tab
 * does not touch AppSettings or the backend settings schema.
 */

import { useEffect, useState } from 'react';

import { useI18n } from '../../shared/lib/i18n';
import type { PetConfigBridge } from '../../shared/types/electron-api';

import { SettingRow, Toggle } from './components';

const FALLBACK_CONFIG: PetConfigBridge = {
  version: 1,
  enabled: false,
  displayMode: 'desktop',
  size: 'medium',
  tempo: 'standard',
  reduceMotion: false,
  bubbleMode: 'important',
  soundScenes: { waiting: true, error: false, done: false },
  showSessionTitle: false,
  compatibilityMode: 'auto',
  petPack: 'dafeiyu',
  followActiveSession: true,
};

function Select({
  value,
  options,
  onChange,
  testId,
}: {
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  testId?: string;
}): JSX.Element {
  return (
    <select
      data-testid={testId}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="rounded-md border border-line-strong bg-surface px-2 py-1 text-sm text-text"
    >
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

export function PetTab(): JSX.Element {
  const { t } = useI18n();
  const bridge = typeof window !== 'undefined' ? window.electronAPI?.pet : undefined;
  const [config, setConfig] = useState<PetConfigBridge | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!bridge) return;
    let alive = true;
    bridge
      .getConfig()
      .then((value) => {
        if (alive) setConfig(value);
      })
      .catch((err: unknown) => {
        if (alive) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      alive = false;
    };
  }, [bridge]);

  const update = (patch: Partial<PetConfigBridge>): void => {
    if (!bridge) return;
    bridge
      .setConfig(patch)
      .then(setConfig)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  };

  if (!bridge) {
    return (
      <div className="rounded-md border border-line bg-surface p-4 text-sm text-muted">
        {t('settings.pet.desktop_only')}
      </div>
    );
  }

  const current = config ?? FALLBACK_CONFIG;

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-base font-medium text-text">{t('settings.pet.title')}</h3>
        <p className="mt-1 text-xs text-muted">{t('settings.pet.desc')}</p>
      </div>

      {error ? (
        <div className="rounded-md border border-red-500/40 bg-red-500/10 p-3 text-xs text-red-400">
          {error}
        </div>
      ) : null}

      <div>
        <SettingRow
          label={t('settings.pet.enabled')}
          desc={t('settings.pet.enabled_desc')}
          anchor="pet_enabled"
        >
          <Toggle
            value={current.enabled}
            onChange={(enabled) => update({ enabled })}
            testId="pet-enabled-toggle"
          />
        </SettingRow>

        <SettingRow label={t('settings.pet.display_mode')} anchor="pet_display_mode">
          <Select
            value={current.displayMode}
            testId="pet-display-mode"
            onChange={(value) => update({ displayMode: value as PetConfigBridge['displayMode'] })}
            options={[
              { value: 'desktop', label: t('settings.pet.display.desktop') },
              { value: 'in-app', label: t('settings.pet.display.in_app') },
              { value: 'both', label: t('settings.pet.display.both') },
              { value: 'off', label: t('settings.pet.display.off') },
            ]}
          />
        </SettingRow>

        <SettingRow label={t('settings.pet.size')} anchor="pet_size">
          <Select
            value={current.size}
            testId="pet-size"
            onChange={(value) => update({ size: value as PetConfigBridge['size'] })}
            options={[
              { value: 'mini', label: t('settings.pet.size.mini') },
              { value: 'small', label: t('settings.pet.size.small') },
              { value: 'medium', label: t('settings.pet.size.medium') },
              { value: 'large', label: t('settings.pet.size.large') },
              { value: 'huge', label: t('settings.pet.size.huge') },
            ]}
          />
        </SettingRow>

        <SettingRow label={t('settings.pet.tempo')} anchor="pet_tempo">
          <Select
            value={current.tempo}
            testId="pet-tempo"
            onChange={(value) => update({ tempo: value as PetConfigBridge['tempo'] })}
            options={[
              { value: 'quiet', label: t('settings.pet.tempo.quiet') },
              { value: 'standard', label: t('settings.pet.tempo.standard') },
              { value: 'lively', label: t('settings.pet.tempo.lively') },
            ]}
          />
        </SettingRow>

        <SettingRow label={t('settings.pet.bubble')}>
          <Select
            value={current.bubbleMode}
            testId="pet-bubble-mode"
            onChange={(value) => update({ bubbleMode: value as PetConfigBridge['bubbleMode'] })}
            options={[
              { value: 'important', label: t('settings.pet.bubble.important') },
              { value: 'always', label: t('settings.pet.bubble.always') },
              { value: 'off', label: t('settings.pet.bubble.off') },
            ]}
          />
        </SettingRow>

        <SettingRow label={t('settings.pet.reduce_motion')}>
          <Toggle
            value={current.reduceMotion}
            onChange={(reduceMotion) => update({ reduceMotion })}
            testId="pet-reduce-motion"
          />
        </SettingRow>

        <SettingRow label={t('settings.pet.show_session_title')}>
          <Toggle
            value={current.showSessionTitle}
            onChange={(showSessionTitle) => update({ showSessionTitle })}
            testId="pet-show-session-title"
          />
        </SettingRow>

        <SettingRow label={t('settings.pet.sound_waiting')}>
          <Toggle
            value={current.soundScenes.waiting}
            onChange={(waiting) => update({ soundScenes: { ...current.soundScenes, waiting } })}
            testId="pet-sound-waiting"
          />
        </SettingRow>

        <SettingRow label={t('settings.pet.sound_error')}>
          <Toggle
            value={current.soundScenes.error}
            onChange={(errorScene) =>
              update({ soundScenes: { ...current.soundScenes, error: errorScene } })
            }
            testId="pet-sound-error"
          />
        </SettingRow>

        <SettingRow label={t('settings.pet.sound_done')}>
          <Toggle
            value={current.soundScenes.done}
            onChange={(done) => update({ soundScenes: { ...current.soundScenes, done } })}
            testId="pet-sound-done"
          />
        </SettingRow>

        <SettingRow
          label={t('settings.pet.compatibility')}
          desc={t('settings.pet.compatibility_desc')}
        >
          <Select
            value={current.compatibilityMode}
            testId="pet-compatibility-mode"
            onChange={(value) =>
              update({ compatibilityMode: value as PetConfigBridge['compatibilityMode'] })
            }
            options={[
              { value: 'auto', label: t('settings.pet.compat.auto') },
              { value: 'on', label: t('settings.pet.compat.on') },
              { value: 'off', label: t('settings.pet.compat.off') },
            ]}
          />
        </SettingRow>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          data-testid="pet-reset-position"
          onClick={() => bridge.resetPosition()}
          className="rounded-md border border-line-strong px-3 py-1.5 text-xs text-text hover:border-primary"
        >
          {t('settings.pet.reset_position')}
        </button>
        <span className="text-xs text-muted">{t('settings.pet.asset_notice')}</span>
      </div>
    </div>
  );
}
