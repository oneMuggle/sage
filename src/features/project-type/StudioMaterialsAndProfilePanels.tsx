/**
 * Phase P9 & P10: 多态项目工作台 L1 项目总纲 (SAGE.md) + L4 受控资料库 + L3 项目记忆画像 + L5 只读白名单面板
 */

import { CheckCircle2, FilePlus2, FileText, FolderLock, Plus, Sparkles, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { projectApi } from '../../shared/api';
import type {
  ProjectCharter,
  ProjectMaterial,
  ProjectType,
} from '../../shared/api/projectApiTypes';
import type { ProjectProfileEntry } from '../../shared/api/types';
import { Button } from '../../shared/ui/Button';

const ARCHETYPE_INSTRUCTIONS_PRESETS: Record<ProjectType, string> = {
  coding:
    '严格遵循仓库分层架构边界，禁止跨层逆向导入；修改核心逻辑后主动运行单元测试、TypeScript 类型检查与 lint 验证。',
  business:
    '所有公文与合同条款草拟或审阅须核对甲乙方简称、金额大小写及权责对等性；引用条款须注明依据来源，严禁主观臆造。',
  research:
    '所有学术论述与文献对比必须严格基于已入库文献或实验记录，严禁捏造任何参考文献、作者、年份或 DOI；无据可查处须标注 [待补充文献支撑]。',
  personal:
    '以高信息密度卡片盒 (Zettelkasten) 风格整理笔记，自动提炼双链概念标签与可执行下一步行动项 (Next Actions)。',
};

export interface StudioCharterTabPanelProps {
  projectId: string;
  projectPath: string;
  projectType?: ProjectType;
  initialDescription?: string | null;
  initialInstructions?: string | null;
  onMetadataUpdated?: (patch: {
    description: string | null;
    instructions: string | null;
  }) => void;
}

export function StudioCharterTabPanel({
  projectId,
  projectPath,
  projectType = 'coding',
  initialDescription,
  initialInstructions,
  onMetadataUpdated,
}: StudioCharterTabPanelProps) {
  const [charter, setCharter] = useState<ProjectCharter | null>(null);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [savedHint, setSavedHint] = useState<string | null>(null);

  const [descriptionDraft, setDescriptionDraft] = useState(initialDescription ?? '');
  const [instructionsDraft, setInstructionsDraft] = useState(initialInstructions ?? '');
  const [savingMeta, setSavingMeta] = useState(false);
  const [metaSavedHint, setMetaSavedHint] = useState<string | null>(null);

  useEffect(() => {
    setDescriptionDraft(initialDescription ?? '');
    setInstructionsDraft(initialInstructions ?? '');
  }, [projectId, initialDescription, initialInstructions]);

  const loadCharter = useCallback(async () => {
    if (!projectId || typeof projectApi?.getCharter !== 'function') return;
    try {
      const res = await projectApi.getCharter(projectId);
      setCharter(res);
      setDraft(res.content || res.recommendedTemplate || '');
    } catch {
      setCharter(null);
    }
  }, [projectId]);

  useEffect(() => {
    void loadCharter();
  }, [loadCharter]);

  const handleFillTemplate = () => {
    if (charter?.recommendedTemplate) {
      setDraft(charter.recommendedTemplate);
      setSavedHint(null);
    }
  };

  const handleSave = async () => {
    if (saving || typeof projectApi?.updateCharter !== 'function') return;
    setSaving(true);
    try {
      const updated = await projectApi.updateCharter(projectId, draft);
      setCharter(updated);
      setDraft(updated.content);
      setSavedHint(`已保存 SAGE.md（${updated.charCount} 字符）`);
    } catch {
      // ignore in test/offline mode
    } finally {
      setSaving(false);
    }
  };

  const handleFillInstructionsPreset = () => {
    const preset =
      ARCHETYPE_INSTRUCTIONS_PRESETS[projectType] ?? ARCHETYPE_INSTRUCTIONS_PRESETS.coding;
    setInstructionsDraft(preset);
    setMetaSavedHint(null);
  };

  const handleSaveMetadata = async () => {
    if (savingMeta || typeof projectApi?.update !== 'function') return;
    setSavingMeta(true);
    try {
      const desc = descriptionDraft.trim() || null;
      const inst = instructionsDraft.trim() || null;
      await projectApi.update(projectId, {
        description: desc,
        instructions: inst,
      });
      onMetadataUpdated?.({ description: desc, instructions: inst });
      setMetaSavedHint('已保存 L2 目标与系统指令');
    } catch {
      // ignore in test/offline mode
    } finally {
      setSavingMeta(false);
    }
  };

  return (
    <div className="space-y-4" data-testid="project-charter-studio-panel">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/20 p-3 text-xs">
          <div className="space-y-0.5">
            <div className="flex items-center gap-1.5 font-medium text-foreground">
              <FileText className="h-3.5 w-3.5 text-primary" />
              <span>
                L1 项目本地规范总纲（<code className="font-mono">{projectPath}/SAGE.md</code>）
              </span>
              <span
                className={`rounded px-1.5 py-0.5 text-ui-2xs ${
                  charter?.exists
                    ? 'bg-emerald-500/10 text-emerald-600'
                    : 'bg-amber-500/10 text-amber-600'
                }`}
              >
                {charter?.exists ? `已生效 · ${charter.charCount} 字符` : '待创建'}
              </span>
            </div>
            <p className="text-muted-foreground">
              作为五层上下文注入体系的第 1 层（最高优先级），用于定义代码工程规范、一般档案封面元数据或科研课题总纲与符号表。
            </p>
          </div>
          <div className="flex items-center gap-2">
            {savedHint && (
              <span
                className="inline-flex items-center gap-1 text-ui-2xs font-medium text-emerald-600"
                data-testid="studio-charter-saved-hint"
              >
                <CheckCircle2 className="h-3 w-3" />
                {savedHint}
              </span>
            )}
            <Button
              size="sm"
              variant="secondary"
              onClick={handleFillTemplate}
              data-testid="studio-charter-fill-template"
            >
              <Sparkles className="mr-1 h-3.5 w-3.5 text-primary" />
              填入推荐模板
            </Button>
            <Button
              size="sm"
              onClick={() => void handleSave()}
              disabled={saving}
              data-testid="studio-charter-save-btn"
            >
              {saving ? '保存中...' : '保存 SAGE.md'}
            </Button>
          </div>
        </div>

        <textarea
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            setSavedHint(null);
          }}
          rows={8}
          placeholder="# 项目总纲 (SAGE.md)..."
          data-testid="studio-charter-textarea"
          className="w-full rounded-lg border border-input bg-background p-3 font-mono text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>

      {/* L2 项目目标与显式系统指令编辑区 */}
      <div
        className="rounded-lg border border-border bg-muted/15 p-3 space-y-2.5 text-xs"
        data-testid="studio-l2-metadata-section"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="font-medium text-foreground">
              L2 项目目标与高优系统指令（Description & System Instructions）
            </div>
            <p className="text-ui-2xs text-muted-foreground">
              注入五层上下文管线第 2 层，优先级高于全局风格偏好，适合定义本项目的角色定位、审校红线或答复体裁。
            </p>
          </div>
          <div className="flex items-center gap-2">
            {metaSavedHint && (
              <span
                className="inline-flex items-center gap-1 text-ui-2xs font-medium text-emerald-600"
                data-testid="studio-metadata-saved-hint"
              >
                <CheckCircle2 className="h-3 w-3" />
                {metaSavedHint}
              </span>
            )}
            <Button
              size="sm"
              variant="secondary"
              onClick={handleFillInstructionsPreset}
              data-testid="studio-instructions-fill-preset"
            >
              <Sparkles className="mr-1 h-3.5 w-3.5 text-primary" />
              填入形态推荐指令
            </Button>
            <Button
              size="sm"
              onClick={() => void handleSaveMetadata()}
              disabled={savingMeta}
              data-testid="studio-metadata-save-btn"
            >
              {savingMeta ? '保存中...' : '保存目标与指令'}
            </Button>
          </div>
        </div>

        <div className="grid gap-2 md:grid-cols-3">
          <div className="space-y-1">
            <label className="text-ui-2xs font-medium text-muted-foreground">
              项目目标 / 案卷摘要 (description)
            </label>
            <input
              type="text"
              value={descriptionDraft}
              onChange={(e) => {
                setDescriptionDraft(e.target.value);
                setMetaSavedHint(null);
              }}
              placeholder="简述本项目核心目标、案卷编号或课题方向..."
              data-testid="studio-description-input"
              className="w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-xs"
            />
          </div>
          <div className="space-y-1 md:col-span-2">
            <label className="text-ui-2xs font-medium text-muted-foreground">
              显式系统提示词指令 (instructions)
            </label>
            <textarea
              value={instructionsDraft}
              onChange={(e) => {
                setInstructionsDraft(e.target.value);
                setMetaSavedHint(null);
              }}
              rows={2}
              placeholder="输入注入每次会话的显式系统指令..."
              data-testid="studio-instructions-textarea"
              className="w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-xs"
            />
          </div>
        </div>
      </div>
    </div>
  );
}

const ALLOWED_PATH_PRESETS: Record<ProjectType, Array<{ label: string; pattern: string }>> = {
  coding: [
    { label: '跨仓共享 SDK 目录', pattern: '../shared-sdk/**' },
    { label: '公共 API 契约规范库', pattern: '~/Documents/APISpecs/**' },
  ],
  business: [
    { label: '企业标准合同与公文范本库', pattern: '~/Documents/EnterpriseTemplates/**' },
    { label: '国家政策法规与行业标准库', pattern: '~/Documents/Regulations/**' },
  ],
  research: [
    { label: '全局 Zotero 文献 PDF 库', pattern: '~/Zotero/storage/**' },
    { label: '公共科研数据集只读目录', pattern: '~/Datasets/**' },
  ],
  personal: [
    { label: '网页剪藏归档库', pattern: '~/Documents/Clippings/**' },
    { label: '个人电子书与文献库', pattern: '~/Documents/Ebooks/**' },
  ],
};

export interface StudioAllowedPathsTabPanelProps {
  projectPath: string;
  projectType: ProjectType;
  allowedPaths: string[];
  newAllowedPath: string;
  onNewAllowedPathChange: (val: string) => void;
  savingPaths: boolean;
  onAddAllowedPath: () => Promise<void> | void;
  onQuickAddPresetPath: (pattern: string) => Promise<void> | void;
  onRemoveAllowedPath: (rule: string) => Promise<void> | void;
}

export function StudioAllowedPathsTabPanel({
  projectPath,
  projectType,
  allowedPaths,
  newAllowedPath,
  onNewAllowedPathChange,
  savingPaths,
  onAddAllowedPath,
  onQuickAddPresetPath,
  onRemoveAllowedPath,
}: StudioAllowedPathsTabPanelProps) {
  const presets = ALLOWED_PATH_PRESETS[projectType] ?? ALLOWED_PATH_PRESETS.coding;

  return (
    <div className="space-y-3" data-testid="project-allowed-paths-panel">
      <div className="rounded-lg border border-border bg-muted/20 p-3 text-xs text-muted-foreground space-y-1">
        <div className="font-medium text-foreground">
          读写非对称安全边界（Workspace Write + Allowed Paths Read-Only）
        </div>
        <p>
          • 主工作区目录（<code className="font-mono">{projectPath}</code>
          ）：允许 AI 读写文件与生成交付物。
        </p>
        <p>
          • 跨目录只读白名单（<code className="font-mono">allowed_paths</code>
          ）：适合挂载一般档案的「企业合同/公文范本库」、科研项目的「Zotero
          文献库或外部大型数据集」、代码项目的「共享 SDK 仓库」，仅允许只读检索，严禁写入篡改。
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-1.5" data-testid="allowed-paths-presets-bar">
        <span className="inline-flex items-center gap-1 text-ui-2xs text-muted-foreground">
          <FolderLock className="h-3 w-3 text-primary" />
          当前形态推荐只读挂载：
        </span>
        {presets.map((preset, idx) => {
          const alreadyAdded = allowedPaths.includes(preset.pattern);
          return (
            <button
              key={preset.pattern}
              type="button"
              disabled={alreadyAdded || savingPaths}
              onClick={() => void onQuickAddPresetPath(preset.pattern)}
              data-testid={`allowed-path-preset-${idx}`}
              className="inline-flex items-center gap-1 rounded border border-primary/30 bg-primary/5 px-2 py-0.5 text-ui-2xs text-primary hover:bg-primary/10 disabled:opacity-50"
            >
              <Plus className="h-2.5 w-2.5" />
              {preset.label} ({preset.pattern})
            </button>
          );
        })}
      </div>

      <div className="flex gap-2">
        <input
          type="text"
          value={newAllowedPath}
          onChange={(e) => onNewAllowedPathChange(e.target.value)}
          placeholder="输入外部只读参考目录路径或通配规则（如 D:/Templates/** 或 ~/Zotero/storage/**）"
          className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-xs font-mono"
        />
        <Button
          size="sm"
          onClick={() => void onAddAllowedPath()}
          disabled={!newAllowedPath.trim() || savingPaths}
        >
          <Plus className="mr-1 h-3.5 w-3.5" />
          添加只读路径
        </Button>
      </div>

      {allowedPaths.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
          暂未配置额外只读路径（当前仅允许访问项目主目录 {projectPath}）
        </div>
      ) : (
        <div className="space-y-1.5">
          {allowedPaths.map((rule) => (
            <div
              key={rule}
              className="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-xs"
            >
              <span className="font-mono text-foreground">{rule}</span>
              <button
                type="button"
                onClick={() => void onRemoveAllowedPath(rule)}
                disabled={savingPaths}
                className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                aria-label={`移除只读路径：${rule}`}
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
