/**
 * 超长文档检索注入（实验，从 GeneralTab 迁出，2026-10-28 设置页整理 P0）。
 *
 * 附件 >100k 字符时按相关度检索注入。配置存 localStorage（聊天行为级），
 * 发送时由 Chat.tsx 读取并随请求携带。
 */

import { clsx } from 'clsx';
import { useState } from 'react';

import {
  loadAttachmentRagConfig,
  saveAttachmentRagConfig,
  type AttachmentRagConfig,
} from '../../shared/api/attachmentRagConfig';
import { useI18n } from '../../shared/lib/i18n';

import { SettingRow, Toggle } from './components';

export function AttachmentRagCard() {
  const { t } = useI18n();
  const [config, setConfig] = useState<AttachmentRagConfig>(() => loadAttachmentRagConfig());
  // 最近一次落盘的配置：dirty = 当前草稿与之不同。用户的改动只在点「保存」后
  // 才进入 localStorage，切走 tab 会丢草稿 —— 未保存提示必须常显，不能一闪而过。
  const [savedConfig, setSavedConfig] = useState<AttachmentRagConfig>(config);
  const [saved, setSaved] = useState(false);

  // 结构固定、键序稳定（改值走浅合并，不重排键），因此序列化比较足够。
  const dirty = JSON.stringify(config) !== JSON.stringify(savedConfig);

  const update = (patch: Partial<AttachmentRagConfig>) => {
    setSaved(false);
    setConfig({ ...config, ...patch });
  };

  const handleSave = () => {
    saveAttachmentRagConfig(config);
    setSavedConfig(config);
    setSaved(true);
    window.setTimeout(() => setSaved(false), 2000);
  };

  const inputClass =
    'px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text w-full';

  return (
    <section data-testid="attachment-rag-section">
      <h3 className="text-sm font-semibold text-text mb-3">{t('settings.rag.title')}</h3>
      <SettingRow
        anchor="attachment_rag"
        label={t('settings.rag.enable.label')}
        desc={t('settings.rag.enable.desc')}
      >
        <Toggle value={config.enabled} onChange={(v) => update({ enabled: v })} />
      </SettingRow>
      {config.enabled && (
        <div className="mt-2 space-y-2 grid grid-cols-2 gap-2">
          <label className="text-xs text-muted space-y-1 col-span-2">
            <span>Embedding Base URL</span>
            <input
              data-testid="attachment-rag-base-url"
              value={config.embed.base_url}
              onChange={(e) => update({ embed: { ...config.embed, base_url: e.target.value } })}
              placeholder="https://api.example.com/v1"
              className={inputClass}
            />
          </label>
          <label className="text-xs text-muted space-y-1">
            <span>API Key</span>
            <input
              data-testid="attachment-rag-api-key"
              type="password"
              value={config.embed.api_key}
              onChange={(e) => update({ embed: { ...config.embed, api_key: e.target.value } })}
              className={inputClass}
            />
          </label>
          <label className="text-xs text-muted space-y-1">
            <span>{t('settings.rag.model.label')}</span>
            <input
              data-testid="attachment-rag-model"
              value={config.embed.model}
              onChange={(e) => update({ embed: { ...config.embed, model: e.target.value } })}
              placeholder="text-embedding-3-small"
              className={inputClass}
            />
          </label>
          <label className="text-xs text-muted space-y-1">
            <span>{t('settings.rag.dim.label')}</span>
            <input
              data-testid="attachment-rag-dim"
              type="number"
              value={config.embed.dim}
              onChange={(e) => update({ embed: { ...config.embed, dim: Number(e.target.value) } })}
              className={inputClass}
            />
          </label>
          <label className="text-xs text-muted space-y-1">
            <span>{t('settings.rag.top_k.label')}</span>
            <input
              data-testid="attachment-rag-top-k"
              type="number"
              value={config.top_k}
              onChange={(e) => update({ top_k: Number(e.target.value) })}
              className={inputClass}
            />
          </label>
        </div>
      )}
      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          data-testid="attachment-rag-save"
          onClick={handleSave}
          disabled={!dirty}
          className={clsx(
            'px-3 py-1 text-xs rounded-radius-sm transition-colors',
            dirty
              ? 'bg-primary text-text-inverse hover:bg-primary-hover'
              : 'bg-bg-muted text-muted cursor-not-allowed',
          )}
        >
          {t('settings.common.save')}
        </button>
        {dirty && (
          <span data-testid="attachment-rag-unsaved" className="text-xs text-muted">
            {t('settings.common.unsaved')}
          </span>
        )}
        {saved && !dirty && (
          <span data-testid="attachment-rag-saved" className="text-xs text-green-500">
            {t('settings.rag.saved')}
          </span>
        )}
      </div>
    </section>
  );
}
