/**
 * 设置页「本地 OCR」卡片：状态展示 + 语言/优先策略配置。
 *
 * 数据源：
 * - `GET /api/v1/ocr/capabilities`（引擎/模型可用性）
 * - preferences KV `ocr_config`（JSON：enabled/engine/lang/prefer_local_for_images）
 */

import { useEffect, useState } from 'react';

import { ocrApi, type OcrCapabilities } from '../../shared/api/ocrApi';
import { settingsClient } from '../../shared/api/settingsClient';
import { useI18n } from '../../shared/lib/i18n';

export interface LocalOcrConfig {
  enabled: boolean;
  engine: 'auto' | 'rapidocr' | 'tesseract';
  lang: 'auto' | 'ch' | 'en';
  prefer_local_for_images: boolean;
}

const DEFAULT_CONFIG: LocalOcrConfig = {
  enabled: true,
  engine: 'auto',
  lang: 'auto',
  prefer_local_for_images: false,
};

function parseConfig(raw: string | null): LocalOcrConfig {
  if (!raw) return DEFAULT_CONFIG;
  try {
    const parsed = JSON.parse(raw) as Partial<LocalOcrConfig>;
    return {
      enabled: parsed.enabled ?? DEFAULT_CONFIG.enabled,
      engine: parsed.engine ?? DEFAULT_CONFIG.engine,
      lang: parsed.lang ?? DEFAULT_CONFIG.lang,
      prefer_local_for_images:
        parsed.prefer_local_for_images ?? DEFAULT_CONFIG.prefer_local_for_images,
    };
  } catch {
    return DEFAULT_CONFIG;
  }
}

export function LocalOcrCard() {
  const { t } = useI18n();
  const [caps, setCaps] = useState<OcrCapabilities | null>(null);
  const [config, setConfig] = useState<LocalOcrConfig>(DEFAULT_CONFIG);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      ocrApi.capabilities().catch(() => null),
      settingsClient.getPreference('ocr_config').catch(() => null),
    ]).then(([nextCaps, rawConfig]) => {
      if (cancelled) return;
      setCaps(nextCaps);
      setConfig(parseConfig(rawConfig));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const save = async (next: LocalOcrConfig) => {
    setConfig(next);
    setSaving(true);
    try {
      await settingsClient.setPreference('ocr_config', JSON.stringify(next), 'ocr');
    } finally {
      setSaving(false);
    }
  };

  const available = Boolean(caps?.enabled && caps?.available);
  const engineLabel = caps?.selected_engine ?? t('settings.ocr.engine_none');
  const reason = caps?.reason || t('settings.ocr.install_hint');

  return (
    <div data-testid="settings-local-ocr" className="space-y-3 rounded border border-border p-3">
      <div>
        <h3 className="text-sm font-semibold text-text">{t('settings.ocr.title')}</h3>
        <p className="mt-0.5 text-xs text-muted">{t('settings.ocr.desc')}</p>
      </div>

      <div className="flex items-center gap-2 text-xs">
        <span
          className={`inline-flex items-center rounded-full border px-2 py-0.5 ${
            available
              ? 'border-success/30 bg-success/10 text-success'
              : 'border-border bg-bg-subtle text-muted'
          }`}
        >
          {available
            ? t('settings.ocr.available').replace('{engine}', engineLabel)
            : t('settings.ocr.unavailable')}
        </span>
        {!available && <span className="text-muted">{reason}</span>}
        {saving && <span className="text-muted">{t('settings.ocr.saving')}</span>}
      </div>

      <label className="flex items-center justify-between gap-3 text-xs">
        <span className="text-text">{t('settings.ocr.lang')}</span>
        <select
          data-testid="settings-ocr-lang"
          value={config.lang}
          onChange={(e) => save({ ...config, lang: e.target.value as LocalOcrConfig['lang'] })}
          className="rounded-radius-sm border border-border bg-surface px-2 py-1 text-xs text-text"
        >
          <option value="auto">{t('settings.ocr.lang_auto')}</option>
          <option value="ch">{t('settings.ocr.lang_ch')}</option>
          <option value="en">{t('settings.ocr.lang_en')}</option>
        </select>
      </label>

      <label className="flex items-start justify-between gap-3 text-xs">
        <span>
          <span className="block text-text">{t('settings.ocr.prefer_local')}</span>
          <span className="block text-muted">{t('settings.ocr.prefer_local_desc')}</span>
        </span>
        <input
          type="checkbox"
          data-testid="settings-ocr-prefer-local"
          checked={config.prefer_local_for_images}
          onChange={(e) => save({ ...config, prefer_local_for_images: e.target.checked })}
        />
      </label>
    </div>
  );
}
