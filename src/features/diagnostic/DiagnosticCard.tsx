import { useState } from 'react';

import { ExportButton } from './ExportButton';
import { useDiagnosticPreview } from './useDiagnosticPreview';

export function DiagnosticCard() {
  const { data, loading, error, refresh } = useDiagnosticPreview();
  const [includePrompts, setIncludePrompts] = useState(false);
  const [includeHostname, setIncludeHostname] = useState(false);

  return (
    <section
      className="rounded-lg border border-border bg-card p-4"
      data-testid="diagnostic-card"
    >
      <h2 className="text-lg font-semibold mb-3">LLM 诊断导出</h2>

      {loading && <div className="text-sm text-muted-foreground">加载中…</div>}

      {error && (
        <div className="text-sm text-red-600 mb-2">加载失败: {error.message}</div>
      )}

      {data && (
        <div className="space-y-3">
          <div className="text-sm">
            最近采集到的 LLM 调用: <strong>{data.count}</strong> 条
          </div>

          {data.oldestTs && data.newestTs && (
            <div className="text-sm text-muted-foreground">
              时间范围: {data.oldestTs} – {data.newestTs}
            </div>
          )}

          {data.sampleUrls.length > 0 && (
            <div className="text-sm text-muted-foreground">
              上游端点样本: {data.sampleUrls.slice(0, 3).join(' / ')}
            </div>
          )}

          <div className="space-y-1">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={includePrompts}
                onChange={(e) => setIncludePrompts(e.target.checked)}
                data-testid="checkbox-prompts"
              />
              包含原始 prompt 内容(可能含业务敏感信息)
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={includeHostname}
                onChange={(e) => setIncludeHostname(e.target.checked)}
                data-testid="checkbox-hostname"
              />
              包含本机主机名
            </label>
          </div>

          <div className="flex gap-2">
            <ExportButton includePrompts={includePrompts} includeHostname={includeHostname} />
            <button
              onClick={refresh}
              disabled={loading}
              className="px-3 py-1 rounded border"
            >
              刷新
            </button>
          </div>
        </div>
      )}

      <p className="text-xs text-muted-foreground mt-3">
        说明: 导出文件用于问题排查, 不会自动上传。即使默认脱敏, 请人工 review 后再外发。
      </p>
    </section>
  );
}
