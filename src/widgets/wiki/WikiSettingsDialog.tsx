// WikiSettingsDialog - 项目级 Wiki 设置（任务路由模型 + 推理模式）
import { useEffect, useState } from 'react';

import { useWikiSettingsStore } from '../../entities/wiki/settings-store';
import { useWikiStore } from '../../entities/wiki/store';
import { DEFAULT_WIKI_SETTINGS } from '../../shared/types/wiki';
import type { ReasoningMode, WikiProjectSettings } from '../../shared/types/wiki';
import { Button } from '../../shared/ui/Button';
import { Input } from '../../shared/ui/Input';
import { Modal } from '../../shared/ui/Modal';

const REASONING_MODE_OPTIONS: { value: ReasoningMode; label: string }[] = [
  { value: 'auto', label: '自动' },
  { value: 'off', label: '关闭' },
  { value: 'low', label: '低' },
  { value: 'medium', label: '中' },
  { value: 'high', label: '高' },
  { value: 'max', label: '最大' },
];

type ModelKey = keyof WikiProjectSettings['task_routing'];
type ModeKey = keyof WikiProjectSettings['reasoning'];

const MODEL_FIELDS: { key: ModelKey; label: string }[] = [
  { key: 'chat_model', label: '对话模型' },
  { key: 'ingest_model', label: '入库模型' },
  { key: 'research_model', label: '研究模型' },
];

export interface WikiSettingsDialogProps {
  isOpen: boolean;
  onClose: () => void;
}

export function WikiSettingsDialog({ isOpen, onClose }: WikiSettingsDialogProps) {
  const project = useWikiStore((s) => s.project);
  const settings = useWikiSettingsStore((s) => s.settings);
  const isLoading = useWikiSettingsStore((s) => s.isLoading);
  const isSaving = useWikiSettingsStore((s) => s.isSaving);
  const error = useWikiSettingsStore((s) => s.error);
  const loadSettings = useWikiSettingsStore((s) => s.loadSettings);
  const saveSettings = useWikiSettingsStore((s) => s.saveSettings);

  const [draft, setDraft] = useState<WikiProjectSettings>(DEFAULT_WIKI_SETTINGS);

  // 打开时拉取项目设置
  useEffect(() => {
    if (!isOpen || !project) return;
    void loadSettings(project.path);
  }, [isOpen, project, loadSettings]);

  // 后端返回或保存成功后同步到本地草稿
  useEffect(() => {
    if (isOpen) setDraft(settings);
  }, [isOpen, settings]);

  if (!project) return null;

  const setModel = (key: ModelKey, value: string) =>
    setDraft((prev) => ({
      ...prev,
      task_routing: { ...prev.task_routing, [key]: value.trim() ? value.trim() : null },
    }));

  const setMode = (key: ModeKey, value: ReasoningMode) =>
    setDraft((prev) => ({
      ...prev,
      reasoning: { ...prev.reasoning, [key]: value },
    }));

  const handleSave = async () => {
    const ok = await saveSettings(project.path, draft);
    if (ok) onClose();
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="知识库设置"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button onClick={handleSave} disabled={isSaving || isLoading}>
            {isSaving ? '保存中...' : '保存'}
          </Button>
        </div>
      }
    >
      {isLoading ? (
        <div className="text-sm text-muted">加载中...</div>
      ) : (
        <div className="space-y-4">
          <p className="text-xs text-muted">
            模型留空表示使用全局默认模型；推理模式按任务类型分别生效。
          </p>

          {MODEL_FIELDS.map(({ key, label }) => (
            <div key={key} className="space-y-1">
              <label className="text-xs text-muted" htmlFor={`wiki-setting-${key}`}>
                {label}
              </label>
              <Input
                id={`wiki-setting-${key}`}
                value={draft.task_routing[key] ?? ''}
                placeholder="留空使用全局默认模型"
                onChange={(e) => setModel(key, e.target.value)}
              />
            </div>
          ))}

          <div className="grid grid-cols-2 gap-3">
            {(
              [
                { key: 'chat_mode', label: '对话推理模式' },
                { key: 'ingest_mode', label: '入库推理模式' },
              ] as { key: ModeKey; label: string }[]
            ).map(({ key, label }) => (
              <div key={key} className="space-y-1">
                <label className="text-xs text-muted" htmlFor={`wiki-setting-${key}`}>
                  {label}
                </label>
                <select
                  id={`wiki-setting-${key}`}
                  value={draft.reasoning[key]}
                  onChange={(e) => setMode(key, e.target.value as ReasoningMode)}
                  className="w-full rounded-lg border border-border bg-bg-subtle px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                >
                  {REASONING_MODE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>

          {error && <div className="text-xs text-error">{error}</div>}
        </div>
      )}
    </Modal>
  );
}
