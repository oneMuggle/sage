/**
 * Desktop pet settings tab.
 *
 * Pet config is owned by the Electron main process (`pet-config.json`) and
 * accessed through the narrow `window.electronAPI.pet` bridge, so this tab
 * does not touch AppSettings or the backend settings schema.
 *
 * v2: a pets list (1–3). Each pet has its own pack and size; behavior
 * settings (tempo/bubble/sound/…) stay global.
 */

import { useEffect, useState } from 'react';

import { useI18n } from '../../shared/lib/i18n';
import type {
  PetConfigBridge,
  PetInstanceBridge,
  PetPackManifestBridge,
} from '../../shared/types/electron-api';

import { SettingRow, Toggle } from './components';

const MAX_PETS = 3;

const FALLBACK_CONFIG: PetConfigBridge = {
  version: 2,
  enabled: false,
  displayMode: 'desktop',
  tempo: 'standard',
  reduceMotion: false,
  bubbleMode: 'important',
  soundScenes: { waiting: true, error: false, done: false },
  showSessionTitle: false,
  compatibilityMode: 'auto',
  followActiveSession: true,
<<<<<<< HEAD
=======
  externalApi: false,
>>>>>>> origin/main
  pets: [{ id: 'default', petPack: 'dafeiyu', size: 'medium' }],
};

const SIZE_OPTIONS = [
  { value: 'mini', labelKey: 'settings.pet.size.mini' },
  { value: 'small', labelKey: 'settings.pet.size.small' },
  { value: 'medium', labelKey: 'settings.pet.size.medium' },
  { value: 'large', labelKey: 'settings.pet.size.large' },
  { value: 'huge', labelKey: 'settings.pet.size.huge' },
] as const;

function nextPetId(pets: PetInstanceBridge[]): string {
  for (let i = 1; i <= 99; i++) {
    const candidate = `pet-${i}`;
    if (!pets.some((pet) => pet.id === candidate)) return candidate;
  }
  return `pet-${Date.now().toString(36)}`;
}

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
  const [packs, setPacks] = useState<PetPackManifestBridge[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<'import' | 'export' | 'delete' | null>(null);
  const [deleteArmed, setDeleteArmed] = useState<string | null>(null);
  const [managePackId, setManagePackId] = useState<string>('');
<<<<<<< HEAD
=======
  const [apiInfo, setApiInfo] = useState<{
    enabled: boolean;
    port: number | null;
    error?: string | null;
  }>({
    enabled: false,
    port: null,
  });
>>>>>>> origin/main

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
    if (bridge.listPacks) {
      bridge
        .listPacks()
        .then((list) => {
          if (alive) setPacks(list);
        })
        .catch((err: unknown) => {
          if (alive) setError(err instanceof Error ? err.message : String(err));
        });
    }
    return () => {
      alive = false;
    };
  }, [bridge]);

<<<<<<< HEAD
=======
  useEffect(() => {
    if (!bridge) return undefined;
    let alive = true;
    if (!bridge.getApiInfo) return undefined;
    const refresh = (): void => {
      bridge
        .getApiInfo?.()
        .then((info) => {
          if (alive) setApiInfo(info);
        })
        .catch(() => undefined);
    };
    refresh();
    // Main starts/stops the server asynchronously; re-check shortly after.
    const timers = [300, 900, 1800].map((ms) => setTimeout(refresh, ms));
    return () => {
      alive = false;
      for (const timer of timers) clearTimeout(timer);
    };
  }, [bridge, config?.externalApi]);

>>>>>>> origin/main
  const refresh = async (): Promise<void> => {
    if (!bridge) return;
    const [nextConfig, nextPacks] = await Promise.all([
      bridge.getConfig(),
      bridge.listPacks ? bridge.listPacks() : Promise.resolve([]),
    ]);
    setConfig(nextConfig);
    setPacks(nextPacks);
  };

  const update = (patch: Partial<PetConfigBridge>): void => {
    if (!bridge) return;
    bridge
      .setConfig(patch)
      .then(setConfig)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)));
  };

  const updatePet = (id: string, patch: Partial<PetInstanceBridge>): void => {
    if (!config) return;
    update({
      pets: config.pets.map((pet) => (pet.id === id ? { ...pet, ...patch } : pet)),
    });
  };

  const addPet = (): void => {
    if (!config || config.pets.length >= MAX_PETS) return;
    update({
      pets: [
        ...config.pets,
        {
          id: nextPetId(config.pets),
          petPack: config.pets[0]?.petPack ?? 'dafeiyu',
          size: 'medium',
        },
      ],
    });
  };

  const removePet = (id: string): void => {
    if (!config || config.pets.length <= 1) return;
    update({ pets: config.pets.filter((pet) => pet.id !== id) });
    if (deleteArmed) setDeleteArmed(null);
  };

  const importPack = async (): Promise<void> => {
    if (!bridge) return;
    setBusy('import');
    setError(null);
    setNotice(null);
    try {
      const result = await bridge.importPack();
      if (result.canceled) return;
      if (!result.ok) {
        setError(result.error ?? t('settings.pet.pack_failed'));
        return;
      }
      setManagePackId(result.manifest?.id ?? '');
      setNotice(`${t('settings.pet.pack_imported')}${result.manifest?.name ?? ''}`);
      await refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const exportPack = async (): Promise<void> => {
    const id = managePackId || config?.pets[0]?.petPack;
    if (!bridge || !id) return;
    setBusy('export');
    setError(null);
    setNotice(null);
    try {
      const result = await bridge.exportPack(id);
      if (result.canceled) return;
      if (!result.ok) {
        setError(result.error ?? t('settings.pet.pack_failed'));
        return;
      }
      setNotice(`${t('settings.pet.pack_exported')}${result.path ?? ''}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const deletePack = async (): Promise<void> => {
    const id = managePackId || config?.pets[0]?.petPack;
    if (!bridge || !id) return;
    if (deleteArmed !== id) {
      setDeleteArmed(id);
      return;
    }
    setBusy('delete');
    setError(null);
    setNotice(null);
    try {
      const result = await bridge.deletePack(id);
      if (!result.ok) {
        setError(result.error ?? t('settings.pet.pack_failed'));
        return;
      }
      setDeleteArmed(null);
      setManagePackId('');
      setNotice(t('settings.pet.pack_deleted'));
      await refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  if (!bridge) {
    return (
      <div className="rounded-md border border-line bg-surface p-4 text-sm text-muted">
        {t('settings.pet.desktop_only')}
      </div>
    );
  }

  const current = config ?? FALLBACK_CONFIG;
  const activeManagePackId = managePackId || current.pets[0]?.petPack || 'dafeiyu';
  const packOptions = [
    { value: 'dafeiyu', label: t('settings.pet.pack_builtin') },
    ...packs.map((pack) => ({ value: pack.id, label: pack.name })),
  ];
  for (const id of new Set([...current.pets.map((pet) => pet.petPack), activeManagePackId])) {
    if (!packOptions.some((option) => option.value === id)) {
      packOptions.push({ value: id, label: `${id} (${t('settings.pet.pack_missing')})` });
    }
  }
  const selectedUserPack = packs.find((pack) => pack.id === activeManagePackId) ?? null;
  const sizeOptions = SIZE_OPTIONS.map((option) => ({
    value: option.value,
    label: t(option.labelKey),
  }));
  const actionButtonClass =
    'rounded-md border border-line-strong px-3 py-1.5 text-xs text-text hover:border-primary disabled:cursor-default disabled:opacity-50';
  const dangerButtonClass =
    'rounded-md border border-red-500/50 px-3 py-1.5 text-xs text-red-400 hover:border-red-400 disabled:cursor-default disabled:opacity-50';

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

      {notice ? (
        <div
          data-testid="pet-pack-notice"
          className="rounded-md border border-green-500/40 bg-green-500/10 p-3 text-xs text-green-400"
        >
          {notice}
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

        <SettingRow
          label={t('settings.pet.pets')}
          desc={t('settings.pet.pets_desc')}
          anchor="pet_pets"
        >
          <div className="flex w-full flex-col gap-2">
            {current.pets.map((instance, index) => (
              <div
                key={instance.id}
                data-testid={`pet-row-${instance.id}`}
                className="flex flex-wrap items-center justify-end gap-2"
              >
                <span className="text-xs text-muted">
                  {t('settings.pet.pet_label')} {index + 1}
                </span>
                <Select
                  value={instance.petPack}
                  testId={`pet-pack-${instance.id}`}
                  onChange={(value) => updatePet(instance.id, { petPack: value })}
                  options={packOptions}
                />
                <Select
                  value={instance.size}
                  testId={`pet-size-${instance.id}`}
                  onChange={(value) =>
                    updatePet(instance.id, { size: value as PetInstanceBridge['size'] })
                  }
                  options={sizeOptions}
                />
                {current.pets.length > 1 ? (
                  <button
                    type="button"
                    data-testid={`pet-remove-${instance.id}`}
                    onClick={() => removePet(instance.id)}
                    className={dangerButtonClass}
                  >
                    {t('settings.pet.remove_pet')}
                  </button>
                ) : null}
              </div>
            ))}
            {current.pets.length < MAX_PETS ? (
              <div className="flex justify-end">
                <button
                  type="button"
                  data-testid="pet-add"
                  onClick={addPet}
                  className={actionButtonClass}
                >
                  {t('settings.pet.add_pet')}
                </button>
              </div>
            ) : (
              <div className="text-right text-xs text-muted">{t('settings.pet.pets_max')}</div>
            )}
          </div>
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

        <SettingRow
<<<<<<< HEAD
=======
          label={t('settings.pet.external_api')}
          desc={t('settings.pet.external_api_desc')}
          anchor="pet_external_api"
        >
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted" data-testid="pet-api-port">
              {current.externalApi
                ? apiInfo.error
                  ? `${t('settings.pet.external_api_failed')}: ${apiInfo.error}`
                  : apiInfo.port
                    ? t('settings.pet.external_api_port').replace('{port}', String(apiInfo.port))
                    : t('settings.pet.external_api_starting')
                : ''}
            </span>
            <Toggle
              value={current.externalApi}
              onChange={(externalApi) => update({ externalApi })}
              testId="pet-external-api"
            />
          </div>
        </SettingRow>

        <SettingRow
>>>>>>> origin/main
          label={t('settings.pet.pack_actions')}
          desc={
            selectedUserPack
              ? `${selectedUserPack.name} v${selectedUserPack.version} · ${selectedUserPack.license}`
              : t('settings.pet.pack_builtin_desc')
          }
          anchor="pet_pack_manage"
        >
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Select
              value={activeManagePackId}
              testId="pet-pack-manage"
              onChange={(value) => {
                setDeleteArmed(null);
                setManagePackId(value);
              }}
              options={packOptions}
            />
            <button
              type="button"
              data-testid="pet-pack-import"
              disabled={busy !== null}
              onClick={() => void importPack()}
              className={actionButtonClass}
            >
              {busy === 'import'
                ? t('settings.pet.pack_import_busy')
                : t('settings.pet.pack_import')}
            </button>
            {selectedUserPack ? (
              <>
                <button
                  type="button"
                  data-testid="pet-pack-export"
                  disabled={busy !== null}
                  onClick={() => void exportPack()}
                  className={actionButtonClass}
                >
                  {t('settings.pet.pack_export')}
                </button>
                <button
                  type="button"
                  data-testid="pet-pack-delete"
                  disabled={busy !== null}
                  onClick={() => void deletePack()}
                  className={
                    deleteArmed === activeManagePackId
                      ? 'rounded-md border border-red-500 bg-red-500/15 px-3 py-1.5 text-xs text-red-300 disabled:opacity-50'
                      : dangerButtonClass
                  }
                >
                  {deleteArmed === activeManagePackId
                    ? t('settings.pet.pack_delete_confirm')
                    : t('settings.pet.pack_delete')}
                </button>
              </>
            ) : null}
          </div>
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
