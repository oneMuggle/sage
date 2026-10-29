/**
 * 超长文档检索注入（实验，从 GeneralTab 迁出，2026-10-28 设置页整理 P0）。
 *
 * 附件 >100k 字符时按相关度检索注入。配置存 localStorage（聊天行为级），
 * 发送时由 Chat.tsx 读取并随请求携带。
 */

import { useState } from 'react';

import {
  loadAttachmentRagConfig,
  saveAttachmentRagConfig,
  type AttachmentRagConfig,
} from '../../shared/api/attachmentRagConfig';

import { SettingRow, Toggle } from './components';

export function AttachmentRagCard() {
  const [config, setConfig] = useState<AttachmentRagConfig>(() => loadAttachmentRagConfig());
  const [saved, setSaved] = useState(false);

  const update = (patch: Partial<AttachmentRagConfig>) => {
    setSaved(false);
    setConfig({ ...config, ...patch });
  };

  const handleSave = () => {
    saveAttachmentRagConfig(config);
    setSaved(true);
    window.setTimeout(() => setSaved(false), 2000);
  };

  const inputClass =
    'px-2 py-1 border border-border rounded-radius-sm text-xs font-mono bg-surface text-text w-full';

  return (
    <section data-testid="attachment-rag-section">
      <h3 className="text-sm font-semibold text-text mb-3">超长文档检索注入（实验）</h3>
      <SettingRow
        anchor="attachment_rag"
        label="启用附件检索"
        desc="文档超过 10 万字符时不再整段截断，改为嵌入问题并注入最相关的片段（需在下方填写嵌入端点）"
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
            <span>模型</span>
            <input
              data-testid="attachment-rag-model"
              value={config.embed.model}
              onChange={(e) => update({ embed: { ...config.embed, model: e.target.value } })}
              placeholder="text-embedding-3-small"
              className={inputClass}
            />
          </label>
          <label className="text-xs text-muted space-y-1">
            <span>维度</span>
            <input
              data-testid="attachment-rag-dim"
              type="number"
              value={config.embed.dim}
              onChange={(e) => update({ embed: { ...config.embed, dim: Number(e.target.value) } })}
              className={inputClass}
            />
          </label>
          <label className="text-xs text-muted space-y-1">
            <span>注入片段数 top_k</span>
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
          className="px-3 py-1 text-xs bg-primary text-text-inverse rounded-radius-sm hover:bg-primary-hover"
        >
          保存
        </button>
        {saved && (
          <span data-testid="attachment-rag-saved" className="text-xs text-green-500">
            已保存
          </span>
        )}
      </div>
    </section>
  );
}
