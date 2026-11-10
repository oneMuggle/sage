/**
 * 项目资料面板 — 入库、勾选与列表。
 *
 * 语义检索属于进阶能力，默认折叠在「语义检索」折叠区中，
 * 使资料页首屏只保留「添加资料 + 资料列表」这一条主线。
 */

import { Copy, Eye, FilePlus2, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { projectApi } from '../../shared/api';
import type { ProjectMaterial, ProjectType } from '../../shared/api/projectApiTypes';
import { Button } from '../../shared/ui/Button';

import { SemanticSearchPanel } from './SemanticSearchPanel';

export interface StudioMaterialsTabPanelProps {
  projectId: string;
  projectPath: string;
  projectType?: ProjectType;
}

export function StudioMaterialsTabPanel({
  projectId,
  projectPath,
  projectType = 'coding',
}: StudioMaterialsTabPanelProps) {
  const [materials, setMaterials] = useState<ProjectMaterial[]>([]);
  const [discoverablePaths, setDiscoverablePaths] = useState<string[]>([]);
  const [filePathInput, setFilePathInput] = useState('');
  const [textSnippetInput, setTextSnippetInput] = useState('');
  const [addingFile, setAddingFile] = useState(false);
  const [addingSnippet, setAddingSnippet] = useState(false);
  const [previewMaterialId, setPreviewMaterialId] = useState<string | null>(null);
  const [copiedMaterials, setCopiedMaterials] = useState(false);

  const handleCopyMaterialsMarkdown = async () => {
    const enabledItems = materials.filter((m) => m.enabled !== false);
    const lines = [
      `# 项目资料摘要 (${projectPath})`,
      '',
      ...enabledItems.map((m, i) => `### ${i + 1}. ${m.id}\n${m.content}`),
    ];
    try {
      await navigator.clipboard?.writeText(lines.join('\n\n'));
      setCopiedMaterials(true);
      setTimeout(() => setCopiedMaterials(false), 2000);
    } catch {
      // ignore in test env
    }
  };

  const loadMaterials = useCallback(async () => {
    if (!projectId) return;
    if (typeof projectApi?.listMaterials === 'function') {
      try {
        const list = await projectApi.listMaterials(projectId);
        setMaterials(Array.isArray(list) ? list : []);
      } catch {
        setMaterials([]);
      }
    }
    if (typeof projectApi?.getWorkspaceOverview === 'function') {
      try {
        const ov = await projectApi.getWorkspaceOverview(projectId);
        const paths = Array.from(
          new Set([
            ...(ov.officeDeliverables ?? []).map((f) => f.relativePath),
            ...(ov.researchArtifacts ?? []).map((f) => f.relativePath),
          ]),
        ).slice(0, 6);
        setDiscoverablePaths(paths);
      } catch {
        setDiscoverablePaths([]);
      }
    }
  }, [projectId]);

  useEffect(() => {
    void loadMaterials();
  }, [loadMaterials]);

  const handleAddFromFile = async (targetPath?: string) => {
    const rel = (targetPath ?? filePathInput).trim();
    if (!rel || addingFile || typeof projectApi?.addMaterialFromFile !== 'function') return;
    setAddingFile(true);
    try {
      await projectApi.addMaterialFromFile(projectId, rel);
      if (!targetPath) setFilePathInput('');
      await loadMaterials();
    } catch {
      // ignore in test/offline mode
    } finally {
      setAddingFile(false);
    }
  };

  const handleAddSnippet = async () => {
    const text = textSnippetInput.trim();
    if (!text || addingSnippet || typeof projectApi?.addMaterial !== 'function') return;
    setAddingSnippet(true);
    try {
      await projectApi.addMaterial(projectId, { content: text });
      setTextSnippetInput('');
      await loadMaterials();
    } catch {
      // ignore in test/offline mode
    } finally {
      setAddingSnippet(false);
    }
  };

  const handleToggleEnabled = async (m: ProjectMaterial) => {
    if (typeof projectApi?.updateMaterial !== 'function') return;
    try {
      await projectApi.updateMaterial(projectId, m.id, { enabled: m.enabled === false });
      await loadMaterials();
    } catch {
      // ignore
    }
  };

  const handleBatchToggle = async (enabled: boolean) => {
    if (typeof projectApi?.updateMaterial !== 'function' || materials.length === 0) return;
    try {
      for (const m of materials) {
        if ((m.enabled !== false) !== enabled) {
          await projectApi.updateMaterial(projectId, m.id, { enabled });
        }
      }
      await loadMaterials();
    } catch {
      // ignore
    }
  };

  const handleDelete = async (materialId: string) => {
    if (typeof projectApi?.removeMaterial !== 'function') return;
    try {
      await projectApi.removeMaterial(projectId, materialId);
      await loadMaterials();
    } catch {
      // ignore
    }
  };

  const handleReindexMaterial = async (materialId: string) => {
    if (typeof projectApi?.reindexMaterial !== 'function') return;
    try {
      await projectApi.reindexMaterial(projectId, materialId);
      await loadMaterials();
    } catch {
      // ignore
    }
  };

  return (
    <div className="space-y-3" data-testid="project-materials-studio-panel">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/20 p-3 text-xs text-muted-foreground">
        <div>
          项目资料库（绑定工作区 <code className="font-mono">{projectPath}</code>
          ）：支持提取工作区文件或直接录入文本片段，按需勾选是否参与本轮对话上下文。
        </div>
        {materials.length > 0 && (
          <div className="flex items-center gap-1.5 shrink-0">
            <button
              type="button"
              onClick={() => void handleCopyMaterialsMarkdown()}
              data-testid="studio-materials-copy-md-btn"
              className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
            >
              <Copy className="h-3 w-3 text-primary" />
              {copiedMaterials ? '已复制资料摘要' : '复制生效资料摘要'}
            </button>
            <button
              type="button"
              onClick={() => void handleBatchToggle(true)}
              data-testid="studio-materials-enable-all"
              className="rounded border border-border bg-background px-2 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
            >
              全选参与上下文
            </button>
            <button
              type="button"
              onClick={() => void handleBatchToggle(false)}
              data-testid="studio-materials-disable-all"
              className="rounded border border-border bg-background px-2 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
            >
              全部隔离
            </button>
          </div>
        )}
      </div>

      {discoverablePaths.length > 0 && (
        <div
          className="flex flex-wrap items-center gap-1.5"
          data-testid="studio-discoverable-files-bar"
        >
          <span className="text-ui-2xs text-muted-foreground">工作区发现可入库文件：</span>
          {discoverablePaths.map((relPath, idx) => (
            <button
              key={relPath}
              type="button"
              disabled={addingFile}
              onClick={() => void handleAddFromFile(relPath)}
              data-testid={`studio-discoverable-file-${idx}`}
              className="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/5 px-2 py-0.5 font-mono text-ui-2xs text-primary hover:bg-primary/10"
            >
              <Plus className="h-2.5 w-2.5" />
              {relPath}
            </button>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <input
          type="text"
          value={filePathInput}
          onChange={(e) => setFilePathInput(e.target.value)}
          placeholder="输入工作区相对路径一键提取入库（如 01_literature/references.bib 或 01_原始依据与佐证/合同.docx）"
          data-testid="studio-material-file-input"
          className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-xs font-mono"
        />
        <Button
          size="sm"
          onClick={() => void handleAddFromFile()}
          disabled={!filePathInput.trim() || addingFile}
          data-testid="studio-material-file-add"
        >
          <FilePlus2 className="mr-1 h-3.5 w-3.5" />
          从工作区文件入库
        </Button>
      </div>

      <div className="flex flex-wrap gap-2">
        <input
          type="text"
          value={textSnippetInput}
          onChange={(e) => setTextSnippetInput(e.target.value)}
          placeholder="或直接粘贴纯文本参考片段（如合同关键条款、文献核心摘要、会议纪要结论）..."
          data-testid="studio-material-text-input"
          className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-xs"
        />
        <Button
          size="sm"
          variant="secondary"
          onClick={() => void handleAddSnippet()}
          disabled={!textSnippetInput.trim() || addingSnippet}
          data-testid="studio-material-text-add"
        >
          <Plus className="mr-1 h-3.5 w-3.5" />
          添加文本资料
        </Button>
      </div>

      {materials.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
          当前项目暂无入库资料。可从工作区文件提取，或直接粘贴文本片段。
        </div>
      ) : (
        <div className="space-y-1.5" data-testid="studio-materials-list">
          {materials.map((m) => {
            const isEnabled = m.enabled !== false;
            const summaryLabel = (m.content || '').split('\n')[0]?.trim().slice(0, 80) || m.id;
            const isPreviewOpen = previewMaterialId === m.id;
            return (
              <div
                key={m.id}
                className="rounded-md border border-border bg-card px-3 py-2 text-xs space-y-1.5"
              >
                <div className="flex items-center justify-between gap-2">
                  <label className="flex items-center gap-2 min-w-0 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={isEnabled}
                      onChange={() => void handleToggleEnabled(m)}
                      data-testid={`studio-material-toggle-${m.id}`}
                      className="h-3.5 w-3.5 rounded border-border"
                    />
                    <span className="truncate font-medium text-foreground">{summaryLabel}</span>
                    <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-ui-2xs text-muted-foreground">
                      {m.status === 'ready' ? '已建立索引' : '待索引'}
                    </span>
                  </label>
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      type="button"
                      onClick={() => void handleReindexMaterial(m.id)}
                      data-testid={`studio-material-reindex-${m.id}`}
                      title="重建该资料的向量索引"
                      className="inline-flex items-center gap-1 rounded border border-border bg-muted/40 px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                    >
                      <RefreshCw className="h-2.5 w-2.5" />
                      重建索引
                    </button>
                    <button
                      type="button"
                      onClick={() => setPreviewMaterialId(isPreviewOpen ? null : m.id)}
                      data-testid={`studio-material-preview-toggle-${m.id}`}
                      className="inline-flex items-center gap-1 rounded border border-border bg-muted/40 px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                    >
                      <Eye className="h-2.5 w-2.5" />
                      {isPreviewOpen ? '收起' : '预览'}
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleDelete(m.id)}
                      aria-label={`移除资料：${summaryLabel}`}
                      data-testid={`studio-material-delete-${m.id}`}
                      className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
                {isPreviewOpen && (
                  <pre
                    data-testid={`studio-material-preview-body-${m.id}`}
                    className="max-h-32 overflow-y-auto whitespace-pre-wrap rounded border border-border/60 bg-muted/20 p-2 font-mono text-ui-2xs text-muted-foreground"
                  >
                    {m.content}
                  </pre>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* 语义检索属于进阶能力，默认折叠，避免资料页首屏信息过载 */}
      <details
        className="rounded-lg border border-border bg-card/50"
        data-testid="semantic-search-collapsible"
      >
        <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground">
          语义检索（按需展开）
        </summary>
        <div className="px-3 pb-3">
          <SemanticSearchPanel projectId={projectId} projectType={projectType} />
        </div>
      </details>
    </div>
  );
}
