/**
 * 多态项目工作台：项目总纲 (SAGE.md) + 项目描述与会话指令。
 *
 * 项目资料面板、外部目录白名单面板、项目记忆画像已拆分到独立文件，
 * 本文件只保留总纲与元数据，并通过 re-export 维持既有导入路径不变。
 */

import { CheckCircle2, Copy, FileText, History, Sparkles } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { projectApi } from '../../shared/api';
import type { ProjectCharter, ProjectType } from '../../shared/api/projectApiTypes';
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
}

/** 项目总纲（SAGE.md）编辑区 — 只负责总纲本身；描述与指令见 StudioMetadataPanel。 */
export function StudioCharterTabPanel({ projectId, projectPath }: StudioCharterTabPanelProps) {
  const [charter, setCharter] = useState<ProjectCharter | null>(null);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [savedHint, setSavedHint] = useState<string | null>(null);
  const [copiedCharter, setCopiedCharter] = useState(false);

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
    const lines = [`# 项目总纲 (${projectPath}/SAGE.md)`, '', draft || '（未填写）'];
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

  return (
    <div className="space-y-4" data-testid="project-charter-studio-panel">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/20 p-3 text-xs">
          <div className="space-y-0.5">
            <div className="flex items-center gap-1.5 font-medium text-foreground">
              <FileText className="h-3.5 w-3.5 text-primary" />
              <span>
                项目总纲（<code className="font-mono">{projectPath}/SAGE.md</code>）
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
              项目总纲是每次会话最重要的项目背景：写清这个项目的目标、约定与边界，AI 会优先遵守。
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
              {copiedCharter ? '已复制' : '复制项目总纲'}
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
    </div>
  );
}

export interface StudioMetadataPanelProps {
  projectId: string;
  projectType?: ProjectType;
  initialDescription?: string | null;
  initialInstructions?: string | null;
  onMetadataUpdated?: (patch: { description: string | null; instructions: string | null }) => void;
}

/** 项目描述与会话指令 — 每次会话自动带给 AI 的项目背景。 */
export function StudioMetadataPanel({
  projectId,
  projectType = 'coding',
  initialDescription,
  initialInstructions,
  onMetadataUpdated,
}: StudioMetadataPanelProps) {
  const [descriptionDraft, setDescriptionDraft] = useState(initialDescription ?? '');
  const [instructionsDraft, setInstructionsDraft] = useState(initialInstructions ?? '');
  const [savingMeta, setSavingMeta] = useState(false);
  const [metaSavedHint, setMetaSavedHint] = useState<string | null>(null);

  useEffect(() => {
    setDescriptionDraft(initialDescription ?? '');
    setInstructionsDraft(initialInstructions ?? '');
  }, [projectId, initialDescription, initialInstructions]);

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
      setMetaSavedHint('已保存');
    } catch {
      // ignore in test/offline mode
    } finally {
      setSavingMeta(false);
    }
  };

  return (
    <div className="space-y-4" data-testid="project-metadata-studio-panel">
      <div
        className="rounded-lg border border-border bg-muted/15 p-3 space-y-2.5 text-xs"
        data-testid="studio-l2-metadata-section"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="font-medium text-foreground">项目描述与会话指令</div>
            <p className="text-ui-2xs text-muted-foreground">
              每次会话自动带给 AI 的项目背景，适合写清本项目的角色定位、审校红线或答复体裁。
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
              填入推荐指令
            </Button>
            <Button
              size="sm"
              onClick={() => void handleSaveMetadata()}
              disabled={savingMeta}
              data-testid="studio-metadata-save-btn"
            >
              {savingMeta ? '保存中...' : '保存'}
            </Button>
          </div>
        </div>

        <div className="grid gap-2 md:grid-cols-3">
          <div className="space-y-1">
            <label className="text-ui-2xs font-medium text-muted-foreground">项目描述</label>
            <input
              type="text"
              value={descriptionDraft}
              onChange={(e) => {
                setDescriptionDraft(e.target.value);
                setMetaSavedHint(null);
              }}
              placeholder="一句话说明这个项目要做什么..."
              data-testid="studio-description-input"
              className="w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-xs"
            />
          </div>
          <div className="space-y-1 md:col-span-2">
            <label className="text-ui-2xs font-medium text-muted-foreground">会话指令</label>
            <textarea
              value={instructionsDraft}
              onChange={(e) => {
                setInstructionsDraft(e.target.value);
                setMetaSavedHint(null);
              }}
              rows={2}
              placeholder="每次会话都要遵守的约定..."
              data-testid="studio-instructions-textarea"
              className="w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-xs"
            />
          </div>
        </div>
      </div>
    </div>
  );
}

export { StudioProfileTabPanel, type StudioProfileTabPanelProps } from './StudioProfileTabPanel';
export {
  StudioAllowedPathsTabPanel,
  type StudioAllowedPathsTabPanelProps,
} from './StudioAllowedPathsTabPanel';
export {
  StudioMaterialsTabPanel,
  type StudioMaterialsTabPanelProps,
} from './StudioMaterialsTabPanel';
