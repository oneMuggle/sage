/**
 * Phase P9 & P10: 多态项目工作台 L1 项目总纲 (SAGE.md) + L4 受控资料库 + L3 项目记忆画像 + L5 只读白名单面板
 */

import { Check, CheckCircle2, Copy, Eye, FilePlus2, FileText, FolderLock, History, Plus, Sparkles, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { projectApi } from '../../shared/api';
import type {
  ProjectCharter,
  ProjectMaterial,
  ProjectType,
} from '../../shared/api/projectApiTypes';
import { Button } from '../../shared/ui/Button';

import { SemanticSearchPanel } from './SemanticSearchPanel';

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
  onMetadataUpdated?: (patch: { description: string | null; instructions: string | null }) => void;
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
  const [copiedCharter, setCopiedCharter] = useState(false);

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

  const handleCopyCharterMarkdown = async () => {
    const lines = [
      `# L1 项目总纲 (${projectPath}/SAGE.md)`,
      '',
      draft || '（未填写）',
      '',
      '## L2 项目目标与高优系统指令',
      `- **项目目标**: ${descriptionDraft || '（未设置）'}`,
      `- **系统指令**: ${instructionsDraft || '（未设置）'}`,
    ];
    try {
      await navigator.clipboard?.writeText(lines.join('\n'));
      setCopiedCharter(true);
      setTimeout(() => setCopiedCharter(false), 2000);
    } catch {
      // ignore in test env
    }
  };

  const handleSave = async (withCheckpoint = false) => {
    if (saving || typeof projectApi?.updateCharter !== 'function') return;
    setSaving(true);
    try {
      const updated = await projectApi.updateCharter(projectId, draft);
      setCharter(updated);
      setDraft(updated.content);
      if (withCheckpoint && typeof projectApi?.createCheckpoint === 'function') {
        const cp = await projectApi.createCheckpoint(projectId, 'SAGE.md 规范更新快照');
        setSavedHint(`已保存 SAGE.md 并固化快照（${cp.id}）`);
      } else {
        setSavedHint(`已保存 SAGE.md（${updated.charCount} 字符）`);
      }
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
              作为五层上下文注入体系的第 1
              层（最高优先级），用于定义代码工程规范、一般档案封面元数据或科研课题总纲与符号表。
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
              onClick={() => void handleCopyCharterMarkdown()}
              data-testid="studio-charter-copy-md-btn"
            >
              <Copy className="mr-1 h-3.5 w-3.5 text-primary" />
              {copiedCharter ? '已复制宪章' : '复制宪章与指令'}
            </Button>
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
              variant="secondary"
              onClick={() => void handleSave(true)}
              disabled={saving}
              data-testid="studio-charter-checkpoint-btn"
            >
              <History className="mr-1 h-3.5 w-3.5 text-emerald-500" />
              保存并固化快照
            </Button>
            <Button
              size="sm"
              onClick={() => void handleSave(false)}
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
              注入五层上下文管线第 2
              层，优先级高于全局风格偏好，适合定义本项目的角色定位、审校红线或答复体裁。
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
  const [copiedPaths, setCopiedPaths] = useState(false);
  const presets = ALLOWED_PATH_PRESETS[projectType] ?? ALLOWED_PATH_PRESETS.coding;

  const handleCopyAllowedPaths = async () => {
    const lines = [
      `# L5 跨目录只读白名单 (${projectPath})`,
      '',
      ...allowedPaths.map((p) => `- \`${p}\``),
    ];
    try {
      await navigator.clipboard?.writeText(lines.join('\n'));
      setCopiedPaths(true);
      setTimeout(() => setCopiedPaths(false), 2000);
    } catch {
      // ignore in test env
    }
  };

  return (
    <div className="space-y-3" data-testid="project-allowed-paths-panel">
      <div className="rounded-lg border border-border bg-muted/20 p-3 text-xs text-muted-foreground space-y-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="font-medium text-foreground">
            读写非对称安全边界（Workspace Write + Allowed Paths Read-Only）
          </div>
          {allowedPaths.length > 0 && (
            <button
              type="button"
              onClick={() => void handleCopyAllowedPaths()}
              data-testid="allowed-paths-copy-md-btn"
              className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-0.5 text-ui-2xs font-medium text-foreground hover:bg-muted"
            >
              {copiedPaths ? (
                <>
                  <Check className="h-3 w-3 text-emerald-500" />
                  已复制白名单
                </>
              ) : (
                <>
                  <Copy className="h-3 w-3 text-primary" />
                  复制白名单配置
                </>
              )}
            </button>
          )}
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

export function StudioMaterialsTabPanel({ projectId, projectPath }: StudioMaterialsTabPanelProps) {
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
      `# L4 生效受控资料摘要 (${projectPath})`,
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

  return (
    <div className="space-y-3" data-testid="project-materials-studio-panel">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/20 p-3 text-xs text-muted-foreground">
        <div>
          L4 授信隔离资料与文献语料池（绑定工作区 <code className="font-mono">{projectPath}</code>
          ）：支持工作区文件提取或纯文本条款/摘要入库，按需勾选参与本轮对话上下文（Source-Grounded Toggle）。
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
              className="rounded border border-border bg-background px-2 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted"
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
          当前项目暂无入库受控资料
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
                      {m.status === 'ready' ? '已索引 Wiki' : '待索引'}
                    </span>
                  </label>
                  <div className="flex items-center gap-1 shrink-0">
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

      {/* M4: 语义检索面板 (2026-10-12) */}
      <SemanticSearchPanel projectId={projectId} />
    </div>
  );
}

export { StudioProfileTabPanel, type StudioProfileTabPanelProps } from './StudioProfileTabPanel';
