/**
 * DesignResourcesPanel — 素材：数据源绑定 + 图表嵌入。
 */
import { Database, FileSpreadsheet, Loader2, RefreshCw, Unlink } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { useDesignStore } from '../../entities/design/designStore';
import type { ChartSpec, ChartType } from '../../entities/design/types';
import { useI18n } from '../../shared/lib/i18n';

const CHART_TYPES: ChartType[] = ['bar', 'line', 'hbar', 'pie'];
const SOURCE_EXTS = ['xlsx', 'csv', 'json'];

interface DesignResourcesPanelProps {
  projectId: string;
}

function parseNumbers(text: string): number[] {
  return text
    .split(/[,，\s]+/)
    .map((part) => Number(part.trim()))
    .filter((value) => Number.isFinite(value));
}

function parseLabels(text: string): string[] {
  return text
    .split(/[,，]+/)
    .map((part) => part.trim())
    .filter(Boolean);
}

export function DesignResourcesPanel({ projectId }: DesignResourcesPanelProps) {
  const { t } = useI18n();
  const sourceBinding = useDesignStore((s) => s.sourceBinding);
  const loading = useDesignStore((s) => s.loadingProject);
  const bindSource = useDesignStore((s) => s.bindSource);
  const unbindSource = useDesignStore((s) => s.unbindSource);
  const refreshWithSource = useDesignStore((s) => s.refreshWithSource);
  const embedChart = useDesignStore((s) => s.embedChart);

  const [chartType, setChartType] = useState<ChartType>('bar');
  const [chartTitle, setChartTitle] = useState('');
  const [labelsText, setLabelsText] = useState('');
  const [seriesName, setSeriesName] = useState('');
  const [valuesText, setValuesText] = useState('');
  const [embedding, setEmbedding] = useState(false);

  const canPickFile =
    typeof window !== 'undefined' && Boolean(window.electronAPI?.selectFile);

  const handleBind = async () => {
    const picker = window.electronAPI?.selectFile;
    if (!picker) return;
    const path = await picker({
      title: t('design.resources.bind'),
      filters: [{ name: 'Data', extensions: SOURCE_EXTS }],
    });
    if (!path) return;
    await bindSource(projectId, path);
  };

  const values = parseNumbers(valuesText);
  const canEmbed = !embedding && seriesName.trim().length > 0 && values.length > 0;

  const handleEmbed = async () => {
    if (!canEmbed) return;
    const labels = parseLabels(labelsText);
    const chart: ChartSpec = {
      type: chartType,
      title: chartTitle.trim() || null,
      labels: labels.length ? labels : null,
      series: [
        {
          name: seriesName.trim(),
          ...(labels.length ? { x: labels } : {}),
          y: values,
        },
      ],
    };
    setEmbedding(true);
    try {
      const result = await embedChart(projectId, chart);
      if (result) {
        toast.success(
          t('design.resources.embedded').replace('{version}', String(result.version)),
        );
      }
    } finally {
      setEmbedding(false);
    }
  };

  return (
    <aside className="flex h-full min-h-0 flex-col rounded-lg border border-border bg-surface">
      <div className="border-b border-border px-3 py-2 text-ui-sm font-medium text-text">
        {t('design.resources.title')}
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-3 py-3 text-ui-xs">
        <section className="space-y-2">
          <div className="flex items-center gap-1 text-text-secondary">
            <Database className="h-3 w-3" />
            {t('design.resources.source')}
          </div>
          {sourceBinding ? (
            <div className="rounded-md border border-border px-2.5 py-2">
              <div className="truncate text-text">
                {sourceBinding.name || sourceBinding.file_path}
              </div>
              <div className="text-text-muted">{sourceBinding.kind}</div>
              <div className="mt-2 flex gap-2">
                <button
                  type="button"
                  className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 hover:bg-bg-hover disabled:opacity-40"
                  disabled={loading}
                  onClick={() => void refreshWithSource(projectId)}
                >
                  <RefreshCw className="h-3 w-3" />
                  {t('design.resources.refresh')}
                </button>
                <button
                  type="button"
                  className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 hover:bg-bg-hover"
                  onClick={() => void unbindSource(projectId)}
                >
                  <Unlink className="h-3 w-3" />
                  {t('design.resources.unbind')}
                </button>
              </div>
            </div>
          ) : (
            <p className="text-text-muted">{t('design.resources.sourceNone')}</p>
          )}
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40"
            disabled={!canPickFile}
            title={
              canPickFile ? t('design.resources.bind') : t('design.resources.filePickerUnavailable')
            }
            onClick={() => void handleBind()}
          >
            <FileSpreadsheet className="h-3 w-3" />
            {t('design.resources.bind')}
          </button>
        </section>

        <section className="space-y-2 border-t border-border pt-3">
          <div className="text-text-secondary">{t('design.resources.chart')}</div>
          <label className="block">
            <span className="text-text-muted">{t('design.resources.chartType')}</span>
            <select
              value={chartType}
              onChange={(event) => setChartType(event.target.value as ChartType)}
              className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1 outline-none focus:border-accent"
            >
              {CHART_TYPES.map((type) => (
                <option key={type} value={type}>
                  {t(`design.resources.chartType.${type}`)}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-text-muted">{t('design.resources.chartTitle')}</span>
            <input
              value={chartTitle}
              onChange={(event) => setChartTitle(event.target.value)}
              className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1 outline-none focus:border-accent"
            />
          </label>
          <label className="block">
            <span className="text-text-muted">{t('design.resources.labels')}</span>
            <input
              value={labelsText}
              onChange={(event) => setLabelsText(event.target.value)}
              placeholder="Q1, Q2, Q3, Q4"
              className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1 outline-none focus:border-accent"
            />
          </label>
          <label className="block">
            <span className="text-text-muted">{t('design.resources.seriesName')}</span>
            <input
              value={seriesName}
              onChange={(event) => setSeriesName(event.target.value)}
              className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1 outline-none focus:border-accent"
            />
          </label>
          <label className="block">
            <span className="text-text-muted">{t('design.resources.values')}</span>
            <input
              value={valuesText}
              onChange={(event) => setValuesText(event.target.value)}
              placeholder="10, 20, 30, 40"
              className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1 outline-none focus:border-accent"
            />
          </label>
          <button
            type="button"
            className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40"
            disabled={!canEmbed}
            onClick={() => void handleEmbed()}
          >
            {embedding && <Loader2 className="h-3 w-3 animate-spin" />}
            {t('design.resources.embed')}
          </button>
        </section>
      </div>
    </aside>
  );
}
