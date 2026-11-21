/**
 * DesignTweaksPanel — 微调面板：覆盖设计 token，不重新生成产物。
 */
import { Loader2, RotateCcw } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';

import { useDesignStore } from '../../entities/design/designStore';
import type { ProjectTweaks } from '../../entities/design/types';
import { useI18n } from '../../shared/lib/i18n';

import { deletePreset, loadPresets, savePreset, type TweakPreset } from './designTweakPresets';
import { extractTweakDefaults } from './designTweaks';

interface DesignTweaksPanelProps {
  projectId: string;
}

interface SliderRowProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}

const FONT_OPTIONS = [
  { key: 'auto', value: null },
  { key: 'sans', value: 'system-ui, -apple-system, "Segoe UI", sans-serif' },
  { key: 'serif', value: 'Georgia, "Times New Roman", serif' },
  { key: 'mono', value: 'ui-monospace, Menlo, Consolas, monospace' },
] as const;

function SliderRow({ label, value, min, max, step, onChange }: SliderRowProps) {
  return (
    <label className="block">
      <div className="flex items-center justify-between">
        <span className="text-text-secondary">{label}</span>
        <span className="text-text-muted">{value}px</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        aria-label={label}
        onChange={(event) => onChange(Number(event.target.value))}
        className="mt-1 w-full"
      />
    </label>
  );
}

export function DesignTweaksPanel({ projectId }: DesignTweaksPanelProps) {
  const { t } = useI18n();
  const tweaks = useDesignStore((s) => s.tweaks);
  const systems = useDesignStore((s) => s.systems);
  const project = useDesignStore((s) => s.currentProject);
  const updateTweaksLocal = useDesignStore((s) => s.updateTweaksLocal);
  const persistTweaks = useDesignStore((s) => s.persistTweaks);
  const applyTweaksPreset = useDesignStore((s) => s.applyTweaksPreset);

  const [presets, setPresets] = useState<TweakPreset[]>(() => loadPresets());
  const [presetName, setPresetName] = useState('');

  const defaults = useMemo(() => {
    const system = systems.find((item) => item.id === project?.system_id);
    return extractTweakDefaults(system?.tokens_css ?? '');
  }, [systems, project?.system_id]);

  const timer = useRef<number | null>(null);
  const [saving, setSaving] = useState(false);

  const schedulePersist = (patch: Partial<ProjectTweaks>) => {
    updateTweaksLocal(patch);
    if (timer.current != null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      setSaving(true);
      void persistTweaks(projectId).finally(() => setSaving(false));
    }, 500);
  };

  useEffect(
    () => () => {
      if (timer.current != null) window.clearTimeout(timer.current);
    },
    [],
  );

  const accent = tweaks.accent ?? defaults.accent;
  const radius = tweaks.radius ?? defaults.radius;
  const fontSize = tweaks.font_size ?? defaults.fontSize;
  const density = tweaks.density ?? defaults.density;
  const selectedFontKey =
    FONT_OPTIONS.find((option) => option.value === (tweaks.font_family ?? null))?.key ?? 'auto';
  const hasOverrides = Object.values(tweaks).some((value) => value !== null && value !== undefined);

  const handleSavePreset = () => {
    if (!presetName.trim() || !hasOverrides) return;
    setPresets(savePreset(presetName, tweaks));
    setPresetName('');
  };

  return (
    <aside className="flex h-full min-h-0 flex-col rounded-lg border border-border bg-surface">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <span className="text-ui-sm font-medium text-text">{t('design.tweaks.title')}</span>
        {saving && <Loader2 className="h-3 w-3 animate-spin text-text-muted" />}
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-3 py-3 text-ui-xs">
        <label className="block">
          <span className="text-text-secondary">{t('design.tweaks.accent')}</span>
          <div className="mt-1 flex items-center gap-2">
            <input
              type="color"
              value={accent}
              aria-label={t('design.tweaks.accent')}
              onChange={(event) => schedulePersist({ accent: event.target.value })}
              className="h-7 w-10 cursor-pointer rounded border border-border bg-transparent p-0.5"
            />
            <code className="text-text-muted">{accent}</code>
          </div>
        </label>

        <label className="block">
          <span className="text-text-secondary">{t('design.tweaks.fontFamily')}</span>
          <select
            value={selectedFontKey}
            aria-label={t('design.tweaks.fontFamily')}
            onChange={(event) => {
              const option = FONT_OPTIONS.find((item) => item.key === event.target.value);
              schedulePersist({ font_family: option?.value ?? null });
            }}
            className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1 outline-none focus:border-accent"
          >
            {FONT_OPTIONS.map((option) => (
              <option key={option.key} value={option.key}>
                {t(`design.tweaks.font.${option.key}` as const)}
              </option>
            ))}
          </select>
        </label>

        <SliderRow
          label={t('design.tweaks.radius')}
          value={radius}
          min={0}
          max={24}
          step={1}
          onChange={(value) => schedulePersist({ radius: value })}
        />
        <SliderRow
          label={t('design.tweaks.fontSize')}
          value={fontSize}
          min={12}
          max={22}
          step={1}
          onChange={(value) => schedulePersist({ font_size: value })}
        />
        <SliderRow
          label={t('design.tweaks.density')}
          value={density}
          min={8}
          max={32}
          step={2}
          onChange={(value) => schedulePersist({ density: value })}
        />

        <button
          type="button"
          className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 hover:bg-bg-hover"
          onClick={() =>
            schedulePersist({
              accent: null,
              radius: null,
              font_size: null,
              density: null,
              font_family: null,
            })
          }
        >
          <RotateCcw className="h-3 w-3" />
          {t('design.tweaks.reset')}
        </button>

        <section className="space-y-2 border-t border-border pt-3">
          <div className="text-text-secondary">{t('design.tweaks.presets')}</div>
          <div className="flex gap-2">
            <input
              value={presetName}
              onChange={(event) => setPresetName(event.target.value)}
              placeholder={t('design.tweaks.presetName')}
              className="min-w-0 flex-1 rounded-md border border-border bg-surface px-2 py-1 outline-none focus:border-accent"
            />
            <button
              type="button"
              className="shrink-0 rounded border border-border px-2 py-1 hover:bg-bg-hover disabled:opacity-40"
              disabled={!presetName.trim() || !hasOverrides}
              onClick={handleSavePreset}
            >
              {t('design.tweaks.savePreset')}
            </button>
          </div>
          {presets.map((preset) => (
            <div
              key={preset.name}
              className="flex items-center justify-between gap-2 rounded border border-border px-2 py-1"
            >
              <span className="truncate text-text">{preset.name}</span>
              <div className="flex shrink-0 gap-1">
                <button
                  type="button"
                  className="rounded border border-border px-1.5 py-0.5 hover:bg-bg-hover"
                  onClick={() => void applyTweaksPreset(projectId, preset.tweaks)}
                >
                  {t('design.tweaks.applyPreset')}
                </button>
                <button
                  type="button"
                  className="rounded border border-border px-1.5 py-0.5 hover:bg-bg-hover"
                  onClick={() => setPresets(deletePreset(preset.name))}
                >
                  {t('design.tweaks.deletePreset')}
                </button>
              </div>
            </div>
          ))}
        </section>
      </div>
    </aside>
  );
}
