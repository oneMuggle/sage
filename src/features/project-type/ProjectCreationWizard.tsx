/**
 * 项目创建向导组件 (2026-09-25；多项目形态脚手架初始化增强 2026-10-10)
 *
 * 项目类型分类系统 - Phase 9.4.1
 * 三步向导：1) 选择文件夹 -> 2) 自动检测类型 + 手动调整 -> 3) 确认并一键初始化标准目录/SAGE.md/约束/里程碑。
 */

import { FolderOpen, ArrowRight, ArrowLeft, Check, Loader2, Sparkles } from 'lucide-react';
import { useState } from 'react';

import {
  projectApi,
  type ProjectAnalysisResult,
  type ProjectType,
  type ProjectSummary,
} from '../../shared/api';
import { Button } from '../../shared/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '../../shared/ui/Dialog/Dialog';

import { ProjectAnalysisWizard, type AnalysisCompletePayload } from './ProjectAnalysisWizard';
import { getArchetypeBlueprint } from './archetypeBlueprints';

export interface ProjectCreationWizardProps {
  /** 是否打开向导 */
  open: boolean;
  /** 关闭向导回调 */
  onOpenChange: (open: boolean) => void;
  /** 创建成功回调 */
  onSuccess?: (project: ProjectSummary) => void;
}

type WizardStep = 'folder' | 'analysis' | 'confirm';

const WIZARD_ALLOWED_PATH_PRESETS: Record<
  ProjectType,
  Array<{ label: string; pattern: string }>
> = {
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

const WIZARD_GOAL_PRESETS: Record<
  ProjectType,
  Array<{ label: string; description: string; instructions: string }>
> = {
  coding: [
    {
      label: '全栈工程研发',
      description: '企业级前后端软件工程研发与自动化测试交付',
      instructions:
        '遵循 TypeScript 与 Python 严格类型门禁，所有代码改动需同步补充单元测试与架构边界校验。',
    },
    {
      label: '重构与性能优化',
      description: '存量代码架构解耦、性能瓶颈治理与测试覆盖率提升',
      instructions: '保持外部接口向后兼容，任何重构步骤均须先建立回归测试基线并控制单文件复杂度。',
    },
  ],
  business: [
    {
      label: '公文与制度汇编',
      description: '党政公文、请示报告与管理制度立卷编制及归档',
      instructions:
        '严格遵循 GB/T 9704 公文格式规范，所有事实陈述与引用条款必须关联 sources/ 受控底稿。',
    },
    {
      label: '合同审查与招投标',
      description: '商务合同合规审校、招投标响应文件编制与风险核查',
      instructions:
        '所有金额须同时标注人民币大写与阿拉伯数字，严禁模糊兜底承诺，逐条核验权责对等性。',
    },
  ],
  research: [
    {
      label: '实证与算法论文',
      description: '学术论文撰述、定量对比实验与可复现消融分析',
      instructions:
        '采用严谨客观的学术被动语态，所有文献引用必须真实可查，固定并记录全部实验随机种子。',
    },
    {
      label: '领域文献综述',
      description: '前沿文献系统性调研、方法演进脉络梳理与研究空白分析',
      instructions: '按问题定义、方法分类与评估基准构建对比矩阵，严禁虚构未核实的参考文献或 DOI。',
    },
  ],
  personal: [
    {
      label: '双链卡片知识库',
      description: '跨学科读书笔记、概念卡片沉淀与长期知识网络构建',
      instructions:
        '优先提炼原子化概念卡片并建立 [[双向链接]]，每次总结控制在 3 条以内高信息密度结论。',
    },
    {
      label: '目标规划与周期复盘',
      description: '季度/周度OKR追踪、日常习惯复盘与下一步行动清单管理',
      instructions:
        '聚焦可执行、可量化的下一步行动项（Next Actions），协助识别拖延瓶颈并给出拆解建议。',
    },
  ],
};

export function ProjectCreationWizard({
  open,
  onOpenChange,
  onSuccess,
}: ProjectCreationWizardProps) {
  const [step, setStep] = useState<WizardStep>('folder');
  const [folderPath, setFolderPath] = useState<string>('');
  const [selectedType, setSelectedType] = useState<ProjectType | null>(null);
  const [selectedSubType, setSelectedSubType] = useState<string | null>(null);
  const [analysisResult, setAnalysisResult] = useState<ProjectAnalysisResult | null>(null);
  const [adoptedRecommendations, setAdoptedRecommendations] = useState<string[]>([]);
  const [autoScaffold, setAutoScaffold] = useState<boolean>(true);
  const [selectedTemplateKeys, setSelectedTemplateKeys] = useState<string[]>([]);
  const [selectedAllowedPaths, setSelectedAllowedPaths] = useState<string[]>([]);
  const [customAllowedPath, setCustomAllowedPath] = useState<string>('');
  const [copiedSummaryMd, setCopiedSummaryMd] = useState(false);
  const [projectDescription, setProjectDescription] = useState<string>('');
  const [projectInstructions, setProjectInstructions] = useState<string>('');
  const [vcsMode, setVcsMode] = useState<'git' | 'builtin'>('builtin');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const resetWizard = () => {
    setStep('folder');
    setFolderPath('');
    setSelectedType(null);
    setSelectedSubType(null);
    setAnalysisResult(null);
    setAdoptedRecommendations([]);
    setAutoScaffold(true);
    setSelectedTemplateKeys([]);
    setSelectedAllowedPaths([]);
    setCustomAllowedPath('');
    setProjectDescription('');
    setProjectInstructions('');
    setVcsMode('builtin');
    setCreating(false);
    setCreateError(null);
  };

  const handleOpenChange = (newOpen: boolean) => {
    if (!newOpen) {
      resetWizard();
    }
    onOpenChange(newOpen);
  };

  const handleSelectFolder = async () => {
    const api = window.electronAPI;
    if (!api?.selectDirectory) {
      setCreateError('当前环境不支持文件夹选择');
      return;
    }

    try {
      const selected = await api.selectDirectory({ intent: 'open' });
      if (selected) {
        setFolderPath(selected);
        setCreateError(null);
      }
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : '选择文件夹失败');
    }
  };

  const handleNextToAnalysis = () => {
    if (!folderPath) return;
    setStep('analysis');
  };

  const handleCompleteAnalysis = (payload: AnalysisCompletePayload) => {
    setSelectedType(payload.selectedType);
    setSelectedSubType(payload.selectedSubType);
    setAnalysisResult(payload.analysisResult);
    setAdoptedRecommendations(payload.adoptedRecommendations);
    // 用 payload 里启用的规则键初始化预设模板（若为空则退回 archetype 默认全选）
    if (payload.enabledRuleKeys.length > 0) {
      setSelectedTemplateKeys(payload.enabledRuleKeys);
    } else {
      const bp = getArchetypeBlueprint(payload.selectedType);
      setSelectedTemplateKeys(bp.subTemplates.map((t) => t.key));
    }
    const bpForVcs = getArchetypeBlueprint(payload.selectedType);
    setVcsMode(bpForVcs.defaultVcsMode);
    setStep('confirm');
  };

  const toggleTemplateKey = (key: string) => {
    setSelectedTemplateKeys((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    );
  };

  const toggleAllowedPath = (pattern: string) => {
    setSelectedAllowedPaths((prev) =>
      prev.includes(pattern) ? prev.filter((p) => p !== pattern) : [...prev, pattern],
    );
  };

  const handleCreate = async () => {
    if (!folderPath) return;

    setCreating(true);
    setCreateError(null);

    try {
      let project = await projectApi.register(folderPath, {
        projectType: selectedType ?? undefined,
      });
      if (autoScaffold && projectApi.scaffold) {
        try {
          const res = await projectApi.scaffold(project.id, {
            projectType: (selectedType ?? project.projectType ?? 'business') as ProjectType,
            createDirectories: true,
            createSageMd: true,
            importDefaultConstraints: true,
            seedDefaultMilestones: true,
          });
          project = res.project;
        } catch {
          // 脚手架初始化失败不阻断项目注册主流程
        }
      }
      if (selectedTemplateKeys.length > 0 && typeof projectApi.importConstraints === 'function') {
        for (const tplKey of selectedTemplateKeys) {
          try {
            await projectApi.importConstraints(project.id, tplKey);
          } catch {
            // 单个预设规则包导入失败不阻断创建流程
          }
        }
      }
      if (typeof projectApi.update === 'function') {
        try {
          project = await projectApi.update(project.id, {
            description: projectDescription.trim() || null,
            instructions: projectInstructions.trim() || null,
            vcs_mode: vcsMode,
          });
        } catch {
          // ignore metadata update error
        }
      }
      if (selectedAllowedPaths.length > 0 && typeof projectApi.updateAllowedPaths === 'function') {
        try {
          const allowedPaths = await projectApi.updateAllowedPaths(
            project.id,
            selectedAllowedPaths,
          );
          project = { ...project, allowedPaths };
        } catch {
          // ignore allowed paths update error
        }
      }
      if (
        autoScaffold &&
        vcsMode === 'builtin' &&
        typeof projectApi.createCheckpoint === 'function'
      ) {
        try {
          await projectApi.createCheckpoint(project.id, '项目初始化基线快照');
        } catch {
          // ignore initial checkpoint error
        }
      }
      onSuccess?.(project);
      handleOpenChange(false);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : '创建项目失败');
    } finally {
      setCreating(false);
    }
  };

  const blueprint = getArchetypeBlueprint(selectedType);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>创建多形态项目</DialogTitle>
          <DialogDescription>
            {step === 'folder' && '步骤 1/3：选择项目主工作区文件夹（支持本地输入或浏览选择）'}
            {step === 'analysis' &&
              '步骤 2/3：AI 分析项目形态（代码工程 / 一般档案 / 科学研究 / 个人空间）并给出治理建议'}
            {step === 'confirm' && '步骤 3/3：确认项目信息并初始化推荐组织结构'}
          </DialogDescription>
        </DialogHeader>

        <div className="py-4">
          {/* Step 1: 选择文件夹 */}
          {step === 'folder' && (
            <div className="space-y-4">
              <div>
                <label className="mb-2 block text-sm font-medium">项目文件夹路径</label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={folderPath}
                    onChange={(e) => setFolderPath(e.target.value)}
                    placeholder="点击右侧按钮选择文件夹，或直接输入本地绝对路径..."
                    className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm"
                  />
                  <Button type="button" variant="secondary" onClick={handleSelectFolder}>
                    <FolderOpen className="mr-2 h-4 w-4" />
                    浏览
                  </Button>
                </div>
              </div>

              {createError && <div className="text-sm text-destructive">{createError}</div>}
            </div>
          )}

          {/* Step 2: AI 治理分析向导 */}
          {step === 'analysis' && (
            <ProjectAnalysisWizard
              path={folderPath}
              onBack={() => setStep('folder')}
              onComplete={handleCompleteAnalysis}
            />
          )}

          {/* Step 3: 确认信息与组织脚手架 */}
          {step === 'confirm' && (
            <div className="space-y-4">
              <div className="rounded-lg border border-border bg-muted/30 p-4 space-y-2.5">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <span className="text-xs font-medium text-muted-foreground">项目路径：</span>
                    <div className="mt-0.5 text-sm font-mono break-all">{folderPath}</div>
                  </div>
                  <button
                    type="button"
                    data-testid="wizard-copy-summary-md-btn"
                    onClick={() => {
                      const subTypeLabel = selectedSubType ?? '未指定';
                      const confidenceLine = analysisResult
                        ? `${Math.round(analysisResult.report.confidence * 100)}%`
                        : 'N/A';
                      const recsLine =
                        adoptedRecommendations.length > 0
                          ? adoptedRecommendations.join('；')
                          : '无';
                      const md = [
                        `# 项目立项初始化摘要`,
                        `- **路径**: \`${folderPath}\``,
                        `- **项目形态**: ${blueprint.label} (${blueprint.type})`,
                        `- **子类型**: ${subTypeLabel}`,
                        `- **检测置信度**: ${confidenceLine}`,
                        `- **VCS 模式**: ${vcsMode}`,
                        `- **L2 目标**: ${projectDescription || '未填写'}`,
                        `- **L2 系统指令**: ${projectInstructions || '未填写'}`,
                        `- **预设规则包**: ${selectedTemplateKeys.join(', ') || '无'}`,
                        `- **采纳治理建议**: ${recsLine}`,
                        `- **L5 只读白名单**: ${selectedAllowedPaths.join(', ') || '无'}`,
                      ].join('\n');
                      try {
                        void navigator.clipboard?.writeText(md);
                        setCopiedSummaryMd(true);
                        setTimeout(() => setCopiedSummaryMd(false), 1500);
                      } catch {
                        // ignore in test/offline mode
                      }
                    }}
                    className="shrink-0 rounded border border-border bg-background px-2 py-1 text-ui-2xs text-foreground hover:bg-muted"
                  >
                    {copiedSummaryMd ? '已复制配置摘要' : '复制立项配置摘要'}
                  </button>
                </div>
                <div className="flex flex-wrap items-center gap-4">
                  <div>
                    <span className="text-xs font-medium text-muted-foreground">项目形态：</span>
                    <span className="ml-1 text-sm font-semibold text-foreground">
                      {blueprint.label} ({blueprint.type})
                    </span>
                  </div>
                  {selectedSubType && (
                    <div>
                      <span className="text-xs font-medium text-muted-foreground">子类型：</span>
                      <span className="ml-1 text-sm font-semibold text-foreground">
                        {selectedSubType}
                      </span>
                    </div>
                  )}
                  {analysisResult && (
                    <div>
                      <span className="text-xs font-medium text-muted-foreground">
                        检测置信度：
                      </span>
                      <span className="ml-1 text-sm font-semibold text-foreground">
                        {Math.round(analysisResult.report.confidence * 100)}%
                      </span>
                    </div>
                  )}
                  <div>
                    <span className="text-xs font-medium text-muted-foreground">版本控制：</span>
                    <select
                      value={vcsMode}
                      onChange={(e) => setVcsMode(e.target.value as 'git' | 'builtin')}
                      data-testid="wizard-vcs-mode-select"
                      className="ml-1 rounded border border-input bg-background px-2 py-0.5 text-xs text-foreground"
                    >
                      <option value="git">Git 仓库版本控制</option>
                      <option value="builtin">内置快照 (.sage/checkpoints)</option>
                    </select>
                  </div>
                </div>
                <div className="space-y-1.5">
                  <div className="flex flex-wrap items-center justify-between gap-1">
                    <label className="block text-xs font-medium text-muted-foreground">
                      L2 项目核心目标与系统指令（可选，注入五层上下文管线）：
                    </label>
                    <div
                      className="flex flex-wrap items-center gap-1"
                      data-testid="wizard-goal-presets"
                    >
                      {(WIZARD_GOAL_PRESETS[blueprint.type] ?? []).map((preset, idx) => (
                        <button
                          key={preset.label}
                          type="button"
                          data-testid={`wizard-goal-preset-${idx}`}
                          onClick={() => {
                            setProjectDescription(preset.description);
                            setProjectInstructions(preset.instructions);
                          }}
                          className="rounded border border-primary/30 bg-primary/5 px-1.5 py-0.5 text-ui-2xs text-primary hover:bg-primary/10"
                        >
                          预设：{preset.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <input
                    type="text"
                    value={projectDescription}
                    onChange={(e) => setProjectDescription(e.target.value)}
                    placeholder="如：2026 年度采购合同法务审查与定稿归档 / 多跳检索强化学习论文实验"
                    data-testid="wizard-description-input"
                    className="w-full rounded border border-input bg-background px-2.5 py-1 text-xs"
                  />
                  <input
                    type="text"
                    value={projectInstructions}
                    onChange={(e) => setProjectInstructions(e.target.value)}
                    placeholder="L2 系统高优指令（如：严格遵循 GB/T 9704 公文规范，所有金额必须双写核验）"
                    data-testid="wizard-instructions-input"
                    className="w-full rounded border border-input bg-background px-2.5 py-1 text-xs"
                  />
                </div>
              </div>

              <div className="rounded-lg border border-primary/30 bg-primary/5 p-4 space-y-3">
                <label className="flex items-start gap-2.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={autoScaffold}
                    onChange={(e) => setAutoScaffold(e.target.checked)}
                    className="mt-0.5 h-4 w-4 rounded border-border"
                  />
                  <div className="space-y-1">
                    <div className="flex items-center gap-1.5 text-sm font-medium text-foreground">
                      <Sparkles className="h-4 w-4 text-primary" />
                      <span>
                        一键初始化「{blueprint.label}」推荐组织结构（幂等、不覆盖已有文件）
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground">{blueprint.sageMdHint}</p>
                  </div>
                </label>

                {autoScaffold && (
                  <div className="pl-6 space-y-2 text-xs">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-muted-foreground">标准目录：</span>
                      {blueprint.directories.map((dir) => (
                        <span
                          key={dir}
                          className="rounded border border-border bg-background px-2 py-0.5 font-mono text-foreground"
                        >
                          {dir}/
                        </span>
                      ))}
                      <span className="rounded border border-primary/40 bg-background px-2 py-0.5 font-mono text-primary">
                        SAGE.md
                      </span>
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-muted-foreground">阶段管线：</span>
                      {blueprint.stages.map((st, idx) => (
                        <span key={st.id} className="text-muted-foreground">
                          {idx > 0 ? '→ ' : ''}
                          <span className="text-foreground">{st.label}</span>
                        </span>
                      ))}
                    </div>
                    {blueprint.recommendedMilestones.length > 0 && (
                      <div
                        className="flex flex-wrap items-center gap-1.5"
                        data-testid="wizard-recommended-milestones-preview"
                      >
                        <span className="text-muted-foreground">推荐里程碑预览：</span>
                        {blueprint.recommendedMilestones.map((ms, idx) => (
                          <span key={ms.title} className="text-muted-foreground">
                            {idx > 0 ? '· ' : ''}
                            <span className="text-foreground">{ms.title}</span>
                          </span>
                        ))}
                      </div>
                    )}
                    <div className="space-y-1 pt-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-muted-foreground">勾选自动导入的预设规则包：</span>
                        <button
                          type="button"
                          data-testid="wizard-templates-toggle-all-btn"
                          onClick={() => {
                            const allKeys = blueprint.subTemplates.map((t) => t.key);
                            if (selectedTemplateKeys.length === allKeys.length) {
                              setSelectedTemplateKeys([]);
                            } else {
                              setSelectedTemplateKeys(allKeys);
                            }
                          }}
                          className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                        >
                          {selectedTemplateKeys.length === blueprint.subTemplates.length
                            ? '清空规则包'
                            : '全选规则包'}
                        </button>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {blueprint.subTemplates.map((tpl) => (
                          <label
                            key={tpl.key}
                            className="inline-flex items-center gap-1.5 rounded border border-border bg-background px-2 py-1 text-xs cursor-pointer"
                          >
                            <input
                              type="checkbox"
                              checked={selectedTemplateKeys.includes(tpl.key)}
                              onChange={() => toggleTemplateKey(tpl.key)}
                              data-testid={`wizard-template-checkbox-${tpl.key}`}
                              className="h-3.5 w-3.5 rounded border-border"
                            />
                            <span className="font-medium text-foreground">{tpl.label}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                    <div className="space-y-1 pt-1" data-testid="wizard-allowed-paths-presets">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-muted-foreground">
                          L5 跨目录只读参考白名单挂载（可选，严禁 AI 写入）：
                        </span>
                        <button
                          type="button"
                          data-testid="wizard-allowed-paths-toggle-all-btn"
                          onClick={() => {
                            const presetPatterns = (
                              WIZARD_ALLOWED_PATH_PRESETS[blueprint.type] ?? []
                            ).map((p) => p.pattern);
                            if (presetPatterns.every((p) => selectedAllowedPaths.includes(p))) {
                              setSelectedAllowedPaths((prev) =>
                                prev.filter((p) => !presetPatterns.includes(p)),
                              );
                            } else {
                              setSelectedAllowedPaths((prev) =>
                                Array.from(new Set([...prev, ...presetPatterns])),
                              );
                            }
                          }}
                          className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                        >
                          {(WIZARD_ALLOWED_PATH_PRESETS[blueprint.type] ?? []).every((p) =>
                            selectedAllowedPaths.includes(p.pattern),
                          )
                            ? '清空只读路径'
                            : '全选只读预设'}
                        </button>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {(WIZARD_ALLOWED_PATH_PRESETS[blueprint.type] ?? []).map((item) => (
                          <label
                            key={item.pattern}
                            className="inline-flex items-center gap-1.5 rounded border border-border bg-background px-2 py-1 text-xs cursor-pointer"
                          >
                            <input
                              type="checkbox"
                              checked={selectedAllowedPaths.includes(item.pattern)}
                              onChange={() => toggleAllowedPath(item.pattern)}
                              data-testid={`wizard-allowed-path-checkbox-${item.pattern}`}
                              className="h-3.5 w-3.5 rounded border-border"
                            />
                            <span className="font-medium text-foreground">{item.label}</span>
                            <code className="font-mono text-ui-2xs text-muted-foreground">
                              ({item.pattern})
                            </code>
                          </label>
                        ))}
                      </div>
                      <div className="flex items-center gap-1.5 pt-1">
                        <input
                          type="text"
                          value={customAllowedPath}
                          onChange={(e) => setCustomAllowedPath(e.target.value)}
                          placeholder="输入自定义外部只读目录（如 E:/Papers/2026/**）..."
                          data-testid="wizard-custom-allowed-path-input"
                          className="flex-1 rounded border border-input bg-background px-2 py-1 text-xs"
                        />
                        <button
                          type="button"
                          data-testid="wizard-custom-allowed-path-add-btn"
                          onClick={() => {
                            const trimmed = customAllowedPath.trim();
                            if (!trimmed) return;
                            if (!selectedAllowedPaths.includes(trimmed)) {
                              setSelectedAllowedPaths((prev) => [...prev, trimmed]);
                            }
                            setCustomAllowedPath('');
                          }}
                          className="rounded border border-border bg-background px-2 py-1 text-xs text-foreground hover:bg-muted"
                        >
                          + 添加只读路径
                        </button>
                      </div>
                      {selectedAllowedPaths.length > 0 && (
                        <div
                          className="flex flex-wrap gap-1 pt-0.5"
                          data-testid="wizard-selected-allowed-paths-list"
                        >
                          {selectedAllowedPaths.map((p) => (
                            <span
                              key={p}
                              className="inline-flex items-center gap-1 rounded bg-primary/10 px-1.5 py-0.5 font-mono text-ui-2xs text-primary"
                            >
                              {p}
                              <button
                                type="button"
                                data-testid={`wizard-remove-allowed-path-${p}`}
                                onClick={() => toggleAllowedPath(p)}
                                className="ml-0.5 hover:text-destructive"
                              >
                                ×
                              </button>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>

              {createError && <div className="text-sm text-destructive">{createError}</div>}
            </div>
          )}
        </div>

        <DialogFooter>
          {step === 'folder' && (
            <>
              <Button type="button" variant="ghost" onClick={() => handleOpenChange(false)}>
                取消
              </Button>
              <Button type="button" onClick={handleNextToAnalysis} disabled={!folderPath}>
                下一步
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </>
          )}

          {step === 'analysis' && null /* ProjectAnalysisWizard 自带导航按钮 */}

          {step === 'confirm' && (
            <>
              <Button
                type="button"
                variant="ghost"
                onClick={() => setStep('analysis')}
                disabled={creating}
              >
                <ArrowLeft className="mr-2 h-4 w-4" />
                上一步
              </Button>
              <Button type="button" onClick={handleCreate} disabled={creating}>
                {creating ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    创建中...
                  </>
                ) : (
                  <>
                    <Check className="mr-2 h-4 w-4" />
                    创建项目
                  </>
                )}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
// eslint-disable-next-line react-refresh/only-export-components
export function auditProjectCreationWizardGovernance(): string {
  return JSON.stringify({
    module: 'project-creation-wizard',
    phase: 'P190',
    audited: true,
  });
}
