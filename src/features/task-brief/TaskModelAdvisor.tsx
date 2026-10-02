import { useEffect, useState } from 'react';

import { listModels } from '../../entities/model-catalog/api';
import type { CandidateModel } from '../../entities/model-catalog/types';
import { useI18n } from '../../shared/lib/i18n';
import { useSettings } from '../manage-settings/useSettings';

import { modelTaskFit } from './modelTaskFit';

export function TaskModelAdvisor({
  needsTools,
  onChoose,
}: {
  needsTools: boolean;
  onChoose: (id: string) => void;
}) {
  const { settings } = useSettings();
  const { locale } = useI18n();
  const en = locale === 'en';
  const endpointId = settings.modelSelections.chatModel.endpointId;
  const [models, setModels] = useState<CandidateModel[]>([]);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    setModels([]);
    setError(false);
    onChoose('');
    if (!endpointId) return;
    listModels({ endpointId, limit: 100, offset: 0 })
      .then((data) => {
        if (active) setModels(data.items);
      })
      .catch(() => {
        if (active) setError(true);
      });
    return () => {
      active = false;
    };
    // Parent's setter is stable; endpoint changes invalidate the previous selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpointId]);
  return (
    <details className="mt-3 border-t border-ui-border pt-2">
      <summary className="text-ui-base cursor-pointer">
        {en ? 'Model capabilities and cost scope' : '模型能力与成本范围'}
      </summary>
      <p className="text-ui-sm text-text-secondary mt-1">
        {en
          ? 'Catalog metadata is not a live capability test. No provider is switched automatically. Daily limits are configured in Settings; this selector is not a per-task hard spending cap.'
          : '目录元数据不等于实时能力测试，不会自动切换服务商。每日限额在设置中配置；此入口不是单任务硬限额。'}
      </p>
      <select
        data-testid="task-model-advisor"
        defaultValue=""
        onChange={(event) => onChoose(event.target.value)}
        className="w-full mt-2 rounded border border-ui-border bg-ui-surface p-2 text-ui-base"
      >
        <option value="">{en ? 'Use configured chat model' : '使用已配置的对话模型'}</option>
        {models.map((model) => {
          const fit = modelTaskFit(model, needsTools);
          return (
            <option
              key={`${model.model_key.provider}:${model.model_key.model_id}`}
              value={model.model_key.model_id}
              disabled={!fit.eligible}
            >
              {model.model_key.model_id} · {fit.tools} ·{' '}
              {fit.knownPrice
                ? `${model.price.input_per_million}/${model.price.output_per_million} USD/M`
                : en
                  ? 'price unknown'
                  : '价格未知'}
            </option>
          );
        })}
      </select>
      {error && (
        <p role="status" className="text-ui-sm text-warning">
          {en
            ? 'Model metadata unavailable; the configured model remains selected.'
            : '模型元数据不可用，仍使用已配置模型。'}
        </p>
      )}
      <div className="flex gap-3 text-ui-sm mt-2">
        <a className="underline" href="#/model-catalog">
          {en ? 'Inspect model metadata' : '查看模型目录'}
        </a>
        <a className="underline" href="#/settings">
          {en ? 'Review budgets and safety' : '查看预算与安全设置'}
        </a>
      </div>
    </details>
  );
}
