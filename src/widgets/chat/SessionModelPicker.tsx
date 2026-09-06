// src/widgets/chat/SessionModelPicker.tsx
//
// U8 会话级模型切换（对标增强第二轮批次 B,G5 收尾）。
// 会话级覆盖优先于全局设置（后端 llm_factory 三级解析）;
// "跟随全局" 即清除覆盖。只切模型不改端点(端点恒取全局选择)。

import { Bot } from 'lucide-react';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { useSettings } from '../../features/manage-settings/useSettings';
import { sessionApi } from '../../shared/api/sessionApi';

interface SessionModelPickerProps {
  sessionId: string | null;
}

export function SessionModelPicker({ sessionId }: SessionModelPickerProps) {
  const { settings } = useSettings();
  const [override, setOverride] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);

  // 会话切换时拉取当前覆盖
  useEffect(() => {
    setLoaded(false);
    setOverride(null);
    if (!sessionId) return;
    let cancelled = false;
    sessionApi
      .getModelOverride(sessionId)
      .then((model) => {
        if (!cancelled) setOverride(model);
      })
      .catch(() => {
        /* 拉取失败按"未设置"处理 */
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // 候选项:全部端点的已发现模型(与设置页 ModelsTab 同一数据源)
  const options = settings.endpoints.flatMap((ep) =>
    ep.discoveredModels.map((m) => ({
      modelId: m.id,
      endpointName: ep.name,
    })),
  );

  const globalModelId = settings.modelSelections.chatModel.modelId;

  const handleChange = (value: string): void => {
    if (!sessionId || saving) return;
    setSaving(true);
    sessionApi
      .setModelOverride(sessionId, value)
      .then((applied) => {
        setOverride(applied);
        toast.success(value ? `本会话模型已切换为 ${value}` : '已恢复跟随全局模型');
      })
      .catch((e: unknown) => {
        toast.error(e instanceof Error ? e.message : '模型切换失败');
      })
      .finally(() => setSaving(false));
  };

  return (
    <div className="flex items-center gap-1.5" title="本会话使用的模型(会话级覆盖,仅影响当前对话)">
      <Bot className="w-3.5 h-3.5 text-text-secondary shrink-0" />
      <select
        aria-label="会话模型"
        data-testid="session-model-picker"
        value={override ?? ''}
        disabled={!sessionId || !loaded || saving}
        onChange={(e) => handleChange(e.target.value)}
        className="max-w-56 text-xs text-text-secondary bg-surface border border-border rounded-radius-sm px-1.5 py-1 outline-none hover:bg-bg-hover focus:border-primary disabled:opacity-50 truncate"
      >
        <option value="">
          跟随全局{globalModelId ? ` (${globalModelId})` : '（未设置）'}
        </option>
        {options.map((opt) => (
          <option key={`${opt.endpointName}/${opt.modelId}`} value={opt.modelId}>
            {opt.modelId} · {opt.endpointName}
          </option>
        ))}
      </select>
      {override && (
        <span className="text-[10px] text-amber-600 dark:text-amber-400 shrink-0">覆盖</span>
      )}
    </div>
  );
}
