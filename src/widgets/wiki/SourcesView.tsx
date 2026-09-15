// Sources View - 源文件管理视图
import { FolderPlus, Upload } from 'lucide-react';
import { useEffect, useState } from 'react';

import { resolveEndpoint } from '../../entities/setting/types';
import { mockSourcesTree } from '../../entities/wiki/mock-data';
import { useWikiStore } from '../../entities/wiki/store';
import { useSettings } from '../../features/manage-settings/useSettings';
import { useWikiIngest } from '../../features/wiki/useWikiIngest';
import { wikiIngestStream } from '../../shared/api-client/wiki';

import { SourcesTree } from './SourcesTree';
import { WikiIngestProgress } from './WikiIngestProgress';

export function SourcesView() {
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [ingestId, setIngestId] = useState<string | null>(null);
  const project = useWikiStore((s) => s.project);

  // PR-3 Task 4: `useWikiIngest(ingestId)` is the existing hook that
  // subscribes to `wiki-ingest-{id}-progress` and exposes
  // {progress, done, error}. Setting `ingestId` triggers the listener;
  // clearing it (via `reset`) hides the bar. We feed the hook output
  // straight into <WikiIngestProgress> for the live STAGE_LABELS bar.
  const ingest = useWikiIngest(ingestId);

  // PR-3 follow-up: auto-dismiss the progress bar 4s after a terminal
  // state (done / error). User can still see the final state for a moment
  // before the bar disappears; new ingests reset the timer.
  useEffect(() => {
    if (!ingest.done && !ingest.error) return;
    const t = setTimeout(() => setIngestId(null), 4000);
    return () => clearTimeout(t);
  }, [ingest.done, ingest.error]);

  // PR-3 Task 4: replace the previous `alert(\`模拟导入: ${path}\`)` mock
  // with a real stream invocation. `wikiIngestStream` is invoke-only — it
  // returns the server-allocated streamId immediately; the backend relay
  // publishes `sage:event:wiki-ingest-{streamId}-progress` events which
  // the existing `useWikiIngest` hook subscribes to.
  //
  // LLM config is resolved from `useSettings()` (same pattern as
  // WikiChat.tsx). If the user hasn't configured a chat endpoint +
  // chatModel, the import button is disabled and the user sees no
  // progress event. This is the same gate WikiChat uses for send.
  const settings = useSettings();
  const ingestEndpoint = settings ? resolveEndpoint(settings.settings.modelSelections.chatModel, settings.settings.endpoints) : undefined;
  const ingestModelId = settings?.settings.modelSelections.chatModel.modelId ?? '';

  const handleIngest = async (path: string) => {
    if (!project) {
      // Reset hook state so the user can retry after opening a project.
      ingest.reset();
      return;
    }
    if (!ingestEndpoint || !ingestModelId) {
      // No LLM endpoint configured — silently no-op (button should also
      // be disabled, but this is a defensive guard).
      return;
    }
    try {
      const { streamId } = await wikiIngestStream({
        sourceFile: path,
        projectPath: project.path,
        llmBaseUrl: ingestEndpoint.baseUrl,
        llmApiKey: ingestEndpoint.apiKey,
        llmModel: ingestModelId,
        // Reuse the chat endpoint as the embed endpoint (MVP).
        embedBaseUrl: ingestEndpoint.baseUrl,
        embedApiKey: ingestEndpoint.apiKey,
        embedModel: ingestModelId,  // same model used for both chat + embed (MVP)
      });
      setIngestId(streamId);
    } catch {
      // Invoke-only failure (IPC dispatch error). Swallow silently —
      // the main process IPC layer logs this kind of error, and the
      // user sees no progress UI change (the failed stream never
      // produced a streamId so `useWikiIngest` stays idle).
    }
  };

  const handleDelete = (path: string) => {
    if (confirm(`确定删除 ${path}?`)) {
      // 模拟删除操作
      alert(`模拟删除: ${path}`);
    }
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3 bg-surface">
        <div>
          <h2 className="text-lg font-semibold text-text">来源文件</h2>
          <p className="text-xs text-muted mt-0.5">管理原始资料文档，支持导入到 Wiki</p>
        </div>
        <div className="flex items-center gap-2">
          <button className="flex items-center gap-2 px-3 py-1.5 text-xs rounded-radius-sm border border-border text-text hover:bg-bg-muted transition-colors">
            <FolderPlus className="h-3 w-3" />
            新建文件夹
          </button>
          <button className="flex items-center gap-2 px-4 py-2 bg-primary text-text-inverse rounded-md hover:bg-primary-hover transition-colors">
            <Upload className="h-4 w-4" />
            导入文件
          </button>
        </div>
      </div>

      {/* PR-3 Task 4: render live ingest progress when a stream is active.
          Component reads `progress`, `done`, `error` and renders the
          STAGE_LABELS-driven bar; collapses to null when none are set. */}
      {(ingest.progress || ingest.done || ingest.error) && (
        <div className="border-b border-border px-4 py-3 bg-surface" data-testid="ingest-progress">
          <WikiIngestProgress progress={ingest.progress} done={ingest.done} error={ingest.error} />
        </div>
      )}

      {/* Content */}
      <div className="flex flex-1 overflow-hidden">
        {/* File tree */}
        <div className="w-72 border-r border-border overflow-y-auto bg-surface">
          <div className="px-3 py-2 border-b border-border">
            <span className="text-xs font-semibold text-text uppercase tracking-wide">
              raw/sources
            </span>
          </div>
          <SourcesTree
            nodes={mockSourcesTree}
            onFileClick={setSelectedFile}
            onIngest={handleIngest}
            onDelete={handleDelete}
          />
        </div>

        {/* Preview/Info panel */}
        <div className="flex-1 overflow-y-auto">
          {selectedFile ? (
            <div className="p-6">
              <h3 className="text-base font-semibold text-text mb-2">
                {selectedFile.split('/').pop()}
              </h3>
              <p className="text-xs text-muted mb-4">{selectedFile}</p>

              <div className="rounded-lg border border-border bg-surface p-4 mb-4">
                <h4 className="text-sm font-medium text-text mb-2">文件信息</h4>
                <dl className="space-y-1 text-xs">
                  <div className="flex justify-between">
                    <dt className="text-muted">路径:</dt>
                    <dd className="text-text">{selectedFile}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-muted">大小:</dt>
                    <dd className="text-text">2.3 MB</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-muted">修改时间:</dt>
                    <dd className="text-text">2024-01-20 14:30</dd>
                  </div>
                </dl>
              </div>

              <div className="rounded-lg border border-border bg-surface p-4">
                <h4 className="text-sm font-medium text-text mb-2">预览</h4>
                <p className="text-xs text-muted italic">（文件预览功能待实现）</p>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-muted">
              <FolderPlus className="h-12 w-12 mb-2 opacity-30" />
              <p className="text-sm">选择左侧文件查看详情</p>
              <p className="text-xs mt-1">或导入新文件到 Wiki</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
