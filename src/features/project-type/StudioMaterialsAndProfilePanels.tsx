/**
 * Phase P9: 多态项目工作台 L4 受控资料与语料库标签页 + L3 项目记忆画像标签页 (2026-10-10)
 */

import { FilePlus2, Plus, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { projectApi } from '../../shared/api';
import type { ProjectMaterial } from '../../shared/api/projectApiTypes';
import type { ProjectProfileEntry } from '../../shared/api/types';
import { Button } from '../../shared/ui/Button';

export interface StudioMaterialsTabPanelProps {
  projectId: string;
  projectPath: string;
}

export function StudioMaterialsTabPanel({
  projectId,
  projectPath,
}: StudioMaterialsTabPanelProps) {
  const [materials, setMaterials] = useState<ProjectMaterial[]>([]);
  const [filePathInput, setFilePathInput] = useState('');
  const [addingFile, setAddingFile] = useState(false);

  const loadMaterials = useCallback(async () => {
    if (!projectId || typeof projectApi?.listMaterials !== 'function') return;
    try {
      const list = await projectApi.listMaterials(projectId);
      setMaterials(Array.isArray(list) ? list : []);
    } catch {
      setMaterials([]);
    }
  }, [projectId]);

  useEffect(() => {
    void loadMaterials();
  }, [loadMaterials]);

  const handleAddFromFile = async () => {
    const rel = filePathInput.trim();
    if (!rel || addingFile || typeof projectApi?.addMaterialFromFile !== 'function') return;
    setAddingFile(true);
    try {
      await projectApi.addMaterialFromFile(projectId, rel);
      setFilePathInput('');
      await loadMaterials();
    } catch {
      // ignore in test/offline mode
    } finally {
      setAddingFile(false);
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

  const handleDelete = async (materialId: string) => {
    if (typeof projectApi?.removeMaterial !== 'function') return;
    try {
      await projectApi.removeMaterial(projectId, materialId);
      await loadMaterials();
    } catch {
      // ignore
    }
  };

  return (
    <div className="space-y-3" data-testid="project-materials-studio-panel">
      <div className="rounded-lg border border-border bg-muted/20 p-3 text-xs text-muted-foreground">
        L4 授信隔离资料与文献语料池（绑定工作区 <code className="font-mono">{projectPath}</code>
        ）：支持一键将工作区内的 <code className="font-mono">.bib / .tex / .docx / .xlsx / .md</code>{' '}
        文件提取入库并按需勾选参与本轮对话上下文（Source-Grounded Toggle）。
      </div>

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

      {materials.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
          当前项目暂无入库受控资料
        </div>
      ) : (
        <div className="space-y-1.5" data-testid="studio-materials-list">
          {materials.map((m) => {
            const isEnabled = m.enabled !== false;
            const summaryLabel = (m.content || '').split('\n')[0]?.trim().slice(0, 80) || m.id;
            return (
              <div
                key={m.id}
                className="flex items-center justify-between gap-2 rounded-md border border-border bg-card px-3 py-2 text-xs"
              >
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
                    {m.status === 'ready' ? '已索引 Wiki' : '待索引'}
                  </span>
                </label>
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
            );
          })}
        </div>
      )}
    </div>
  );
}

export interface StudioProfileTabPanelProps {
  projectPath: string;
  profileEntries: ProjectProfileEntry[];
  profileCategory: string;
  onCategoryChange: (cat: string) => void;
  profileDraft: string;
  onDraftChange: (val: string) => void;
  savingProfile: boolean;
  onAddEntry: () => Promise<void> | void;
  onDeleteEntry: (entryId: string) => Promise<void> | void;
}

export function StudioProfileTabPanel({
  projectPath,
  profileEntries,
  profileCategory,
  onCategoryChange,
  profileDraft,
  onDraftChange,
  savingProfile,
  onAddEntry,
  onDeleteEntry,
}: StudioProfileTabPanelProps) {
  return (
    <div className="space-y-3" data-testid="project-profile-studio-panel">
      <div className="rounded-lg border border-border bg-muted/20 p-3 text-xs text-muted-foreground">
        项目级冻结记忆画像（<code className="font-mono">MEMORY.md</code> · 绑定路径{' '}
        <code className="font-mono">{projectPath}</code>
        ），仅在当前项目会话中注入系统提示词，保障跨项目语境隔离与 Prefix Cache 命中率。
      </div>
      <div className="flex flex-wrap gap-2">
        <select
          value={profileCategory}
          onChange={(e) => onCategoryChange(e.target.value)}
          aria-label="选择画像类别"
          data-testid="studio-profile-category"
          className="rounded-md border border-input bg-background px-2.5 py-1.5 text-xs text-foreground"
        >
          <option value="convention">约定 (convention)</option>
          <option value="architecture">架构/方法论 (architecture)</option>
          <option value="decision">决策/审校口径 (decision)</option>
          <option value="goal">核心目标/研究问题 (goal)</option>
          <option value="note">阶段发现/备注 (note)</option>
        </select>
        <input
          type="text"
          value={profileDraft}
          onChange={(e) => onDraftChange(e.target.value)}
          placeholder="输入要长期固化到本项目的约定、决策或核心目标..."
          data-testid="studio-profile-input"
          className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-xs"
        />
        <Button
          size="sm"
          onClick={() => void onAddEntry()}
          disabled={!profileDraft.trim() || savingProfile}
          data-testid="studio-profile-add-btn"
        >
          <Plus className="mr-1 h-3.5 w-3.5" />
          添加画像条目
        </Button>
      </div>
      {profileEntries.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
          当前项目暂无冻结画像条目
        </div>
      ) : (
        <div className="space-y-1.5" data-testid="studio-profile-list">
          {profileEntries.map((entry) => (
            <div
              key={entry.id}
              className="flex items-center justify-between gap-2 rounded-md border border-border bg-card px-3 py-2 text-xs"
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-ui-2xs font-medium text-primary">
                  {entry.category}
                </span>
                <span className="truncate text-foreground">{entry.content}</span>
              </div>
              <button
                type="button"
                onClick={() => void onDeleteEntry(entry.id)}
                aria-label={`删除画像条目：${entry.content}`}
                data-testid={`studio-profile-delete-${entry.id}`}
                className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
