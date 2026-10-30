// Sources View - 源文件管理视图（真实后端数据）
import { RefreshCw, Upload } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import { resolveEndpoint } from '../../entities/setting/types';
import { useQueueStore } from '../../entities/wiki/queue-store';
import { useWikiStore } from '../../entities/wiki/store';
import { useSettings } from '../../features/manage-settings/useSettings';
import { useWikiIngest } from '../../features/wiki/useWikiIngest';
import {
  wikiDeleteSource,
  wikiImportSource,
  wikiIngestStream,
  wikiListDirectory,
  wikiReadFile,
} from '../../shared/api-client/wiki';
import type { FileNode } from '../../shared/types/wiki';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';

import { SourcesTree } from './SourcesTree';
import { WikiIngestProgress } from './WikiIngestProgress';

const TEXT_PREVIEW_EXTENSIONS = new Set(['md', 'markdown', 'txt']);

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function fileExtension(path: string): string {
  return path.split('.').pop()?.toLowerCase() ?? '';
}

export function SourcesView() {
  const [nodes, setNodes] = useState<FileNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [previewContent, setPreviewContent] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [ingestId, setIngestId] = useState<string | null>(null);
  const project = useWikiStore((s) => s.project);

  const ingest = useWikiIngest(ingestId);
  const settings = useSettings();

  useEffect(() => {
    if (!ingest.done && !ingest.error) return;
    const t = setTimeout(() => setIngestId(null), 4000);
    return () => clearTimeout(t);
  }, [ingest.done, ingest.error]);

  const loadSources = useCallback(async () => {
    if (!project?.path) {
      setNodes([]);
      return;
    }
    setLoading(true);
    try {
      const listing = await wikiListDirectory('raw/sources', project.path);
      setNodes(listing[0]?.children ?? []);
    } catch {
      // raw/sources 可能尚未创建：空态比报错更符合首次使用体验。
      setNodes([]);
    } finally {
      setLoading(false);
    }
  }, [project?.path]);

  useEffect(() => {
    void loadSources();
  }, [loadSources]);

  const handleIngest = async (path: string) => {
    if (!project) return;
    const endpoint = settings
      ? resolveEndpoint(settings.settings.modelSelections.chatModel, settings.settings.endpoints)
      : undefined;
    const modelId = settings?.settings.modelSelections.chatModel.modelId ?? '';
    if (!endpoint || !modelId) {
      toast.error('请先在设置中配置聊天模型');
      return;
    }
    try {
      const { streamId } = await wikiIngestStream({
        sourceFile: path,
        projectPath: project.path,
        llmBaseUrl: endpoint.baseUrl,
        llmApiKey: endpoint.apiKey,
        llmModel: modelId,
        embedBaseUrl: endpoint.baseUrl,
        embedApiKey: endpoint.apiKey,
        embedModel: modelId,
      });
      setIngestId(streamId);
    } catch (error) {
      toast.error(`导入失败: ${errorMessage(error)}`);
    }
  };

  const handleImport = async () => {
    if (!project) return;
    const picker = window.electronAPI?.selectFile;
    if (!picker) {
      toast.error('当前环境不支持文件选择器');
      return;
    }
    const picked = await picker({
      title: '选择要导入的文件',
      filters: [
        {
          name: '文档',
          extensions: ['md', 'markdown', 'txt', 'pdf', 'docx', 'pptx', 'xlsx', 'html', 'csv'],
        },
      ],
    });
    if (!picked) return;

    setImporting(true);
    try {
      const result = await wikiImportSource(picked, project.path);
      toast.success(`已导入 ${result.name}`);
      await loadSources();
      await handleIngest(result.relative_path);
    } catch (error) {
      toast.error(`导入失败: ${errorMessage(error)}`);
    } finally {
      setImporting(false);
    }
  };

  const handleSelectFile = async (path: string) => {
    setSelectedFile(path);
    setPreviewContent(null);
    if (!project?.path || !TEXT_PREVIEW_EXTENSIONS.has(fileExtension(path))) return;
    setPreviewLoading(true);
    try {
      setPreviewContent(await wikiReadFile(path, project.path));
    } catch (error) {
      toast.error(`预览失败: ${errorMessage(error)}`);
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleDelete = async (path: string) => {
    if (!project) return;
    const ok = await confirmDialog({
      title: '删除源文件',
      message: `确定删除 ${path}？关联的 Wiki 页面与向量也会被清理。`,
      danger: true,
    });
    if (!ok) return;
    try {
      await wikiDeleteSource(path, project.path);
      toast.success('源文件已删除');
      if (selectedFile === path) {
        setSelectedFile(null);
        setPreviewContent(null);
      }
      await loadSources();
    } catch (error) {
      toast.error(`删除失败: ${errorMessage(error)}`);
    }
  };

  const handleQueue = async (path: string) => {
    if (!project) return;
    const taskId = await useQueueStore.getState().addTask(project.path, path);
    if (taskId) {
      toast.success(`已加入队列（${taskId}）`);
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
          <button
            type="button"
            className="flex items-center gap-2 px-3 py-1.5 text-xs rounded-radius-sm border border-border text-text hover:bg-bg-muted transition-colors disabled:opacity-50"
            disabled={loading}
            onClick={() => void loadSources()}
          >
            <RefreshCw className={`h-3 w-3 ${loading ? 'animate-spin' : ''}`} />
            刷新
          </button>
          <button
            type="button"
            className="flex items-center gap-2 px-4 py-2 bg-primary text-text-inverse rounded-md hover:bg-primary-hover transition-colors disabled:opacity-50"
            disabled={!project || importing}
            onClick={() => void handleImport()}
          >
            <Upload className="h-4 w-4" />
            {importing ? '导入中…' : '导入文件'}
          </button>
        </div>
      </div>

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
          {loading && nodes.length === 0 ? (
            <p className="px-3 py-4 text-xs text-muted">加载中…</p>
          ) : nodes.length === 0 ? (
            <p className="px-3 py-4 text-xs text-muted">
              暂无来源文件。点击「导入文件」添加第一份资料。
            </p>
          ) : (
            <SourcesTree
              nodes={nodes}
              onFileClick={(path) => void handleSelectFile(path)}
              onIngest={(path) => void handleIngest(path)}
              onQueue={(path) => void handleQueue(path)}
              onDelete={(path) => void handleDelete(path)}
            />
          )}
        </div>

        {/* Preview/Info panel */}
        <div className="flex-1 overflow-y-auto">
          {selectedFile ? (
            <div className="p-6">
              <h3 className="text-base font-semibold text-text mb-2">
                {selectedFile.split('/').pop()}
              </h3>
              <p className="text-xs text-muted mb-4">{selectedFile}</p>

              <div className="rounded-lg border border-border bg-surface p-4">
                <h4 className="text-sm font-medium text-text mb-2">预览</h4>
                {previewLoading ? (
                  <p className="text-xs text-muted">读取中…</p>
                ) : previewContent !== null ? (
                  <pre className="whitespace-pre-wrap break-words text-xs text-text bg-bg-muted p-3 rounded max-h-[60vh] overflow-y-auto">
                    {previewContent}
                  </pre>
                ) : (
                  <p className="text-xs text-muted italic">该类型文件不支持文本预览</p>
                )}
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-muted">
              <Upload className="h-12 w-12 opacity-30 mb-2" />
              <p className="text-sm">选择左侧文件查看详情</p>
              <p className="text-xs mt-1">或导入新文件到 Wiki</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
