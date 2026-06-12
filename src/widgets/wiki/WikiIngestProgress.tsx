// WikiIngestProgress - 显示 ingest 进度 UI
import { CheckCircle2, Loader2, XCircle } from 'lucide-react';

import type { IngestProgress } from '../../features/wiki/useWikiIngest';

interface Props {
  progress: IngestProgress | null;
  done: boolean;
  error: string | null;
}

const STAGE_LABELS: Record<string, string> = {
  started: '开始导入',
  copy_source: '复制源文件',
  step1_analyze: 'LLM 分析(Step 1)',
  step2_write: 'LLM 写作(Step 2)',
  embedding: '嵌入 + 写向量库',
  completed: '导入完成',
  unknown: '处理中',
};

export function WikiIngestProgress({ progress, done, error }: Props) {
  if (error) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
        <XCircle className="h-4 w-4" />
        <span>导入失败: {error}</span>
      </div>
    );
  }
  if (done) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-green-500/30 bg-green-500/10 px-3 py-2 text-xs text-green-400">
        <CheckCircle2 className="h-4 w-4" />
        <span>{progress?.message ?? '导入完成'}</span>
      </div>
    );
  }
  if (!progress) {
    return null;
  }
  const stageLabel = STAGE_LABELS[progress.stage] ?? STAGE_LABELS.unknown;
  return (
    <div className="flex flex-col gap-1 rounded-md border border-border bg-surface/95 px-3 py-2 text-xs">
      <div className="flex items-center gap-2">
        <Loader2 className="h-4 w-4 animate-spin text-primary" />
        <span className="font-medium">{stageLabel}</span>
        {progress.message && <span className="text-muted">— {progress.message}</span>}
      </div>
      <div className="h-1.5 w-full rounded-full bg-bg-muted overflow-hidden">
        <div
          className="h-full bg-primary transition-all duration-300"
          style={{ width: `${progress.percent}%` }}
        />
      </div>
      <div className="text-muted text-[10px]">{progress.percent}%</div>
    </div>
  );
}
