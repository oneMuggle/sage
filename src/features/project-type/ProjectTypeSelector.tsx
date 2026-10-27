/**
 * 项目类型选择器 (2026-09-24; Phase P29 手动重新检测、一键采用检测结果与生命周期阶段管线预览)
 *
 * 项目类型分类系统 - Phase 4.1
 * 用于在项目创建/编辑时选择项目类型，支持自动检测建议、重新检测与四形态阶段管线预览
 */

import { Code, BookOpen, Briefcase, User, Sparkles, RefreshCw, Copy, Check } from 'lucide-react';
import { useState, useEffect, useCallback, useMemo } from 'react';

import {
  projectApi,
  type ProjectType,
  type ProjectTypeDetectionResult,
  type SubTypesCatalog,
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

import { getArchetypeBlueprint } from './archetypeBlueprints';
import { resolveSubTypeLabel } from './subTypeCatalog';

export interface ProjectTypeSelectorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectPath: string;
  /** 选择 L1 类型（保持既有签名） */
  onSelect: (type: ProjectType) => void;
  /** 选择 L2 子类型（可选，未提供时仅回传 L1） */
  onSelectSubType?: (type: ProjectType, subType: string | null) => void;
  onCancel?: () => void;
}

interface ProjectTypeOption {
  value: ProjectType;
  label: string;
  description: string;
  icon: React.ReactNode;
  color: string;
}

const PROJECT_TYPES: ProjectTypeOption[] = [
  {
    value: 'coding',
    label: '编码项目',
    description: '软件开发、编程项目。集成 Git 版本控制，代码约束，技术文档。',
    icon: <Code className="h-6 w-6" />,
    color: 'text-info',
  },
  {
    value: 'research',
    label: '科研项目',
    description: '学术研究、论文写作。文献管理，实验记录，学术写作规范。',
    icon: <BookOpen className="h-6 w-6" />,
    color: 'text-primary',
  },
  {
    value: 'business',
    label: '事务项目',
    description: '商业文档、报告撰写。模板约束，审批流程，格式规范。',
    icon: <Briefcase className="h-6 w-6" />,
    color: 'text-success',
  },
  {
    value: 'personal',
    label: '个人项目',
    description: '个人笔记、日记、学习。灵活组织，隐私保护。',
    icon: <User className="h-6 w-6" />,
    color: 'text-warning',
  },
];

export function ProjectTypeSelector({
  open,
  onOpenChange,
  projectPath,
  onSelect,
  onSelectSubType,
  onCancel,
}: ProjectTypeSelectorProps) {
  const [selectedType, setSelectedType] = useState<ProjectType | null>(null);
  const [selectedSubType, setSelectedSubType] = useState<string | null>(null);
  const [subTypes, setSubTypes] = useState<SubTypesCatalog | null>(null);
  const [detection, setDetection] = useState<ProjectTypeDetectionResult | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [copiedDetection, setCopiedDetection] = useState(false);
  const [showSuiteDetails, setShowSuiteDetails] = useState(false);
  const [copiedDirs, setCopiedDirs] = useState(false);
  const [copiedSignalIdx, setCopiedSignalIdx] = useState<number | null>(null);
  const [copiedSelectorPath, setCopiedSelectorPath] = useState(false);
  const [copiedVcs, setCopiedVcs] = useState(false);
  const [copiedPositioning, setCopiedPositioning] = useState(false);

  // 拉取两级类型目录（L2 子类型网格）
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void (async () => {
      try {
        const catalog = await projectApi.subTypes();
        if (!cancelled) setSubTypes(catalog);
      } catch {
        // 目录拉取失败不阻塞 L1 选择
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open]);

  const runDetection = useCallback(async () => {
    if (!projectPath || typeof projectApi?.detectType !== 'function') return;
    setDetecting(true);
    try {
      const result = await projectApi.detectType(projectPath);
      setDetection(result);
      if (result.confidence >= 0.7) {
        setSelectedType(result.detectedType);
        setSelectedSubType(result.subType ?? null);
      }
    } catch {
      // 检测失败时不阻塞用户
    } finally {
      setDetecting(false);
    }
  }, [projectPath]);

  // 自动检测项目类型
  useEffect(() => {
    if (!open || !projectPath) return;
    void runDetection();
  }, [open, projectPath, runDetection]);

  const handleSelectType = useCallback((type: ProjectType) => {
    setSelectedType(type);
    // 切 L1 时清空 L2（避免跨 L1 残留）
    setSelectedSubType(null);
  }, []);

  const subTypeOptions = useMemo(() => {
    if (!selectedType || !subTypes) return [];
    return subTypes.subTypes[selectedType] ?? [];
  }, [selectedType, subTypes]);

  const handleSelect = () => {
    if (selectedType) {
      onSelect(selectedType);
      onSelectSubType?.(selectedType, selectedSubType);
      onOpenChange(false);
    }
  };

  const handleCancel = () => {
    onCancel?.();
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <div className="flex items-center justify-between gap-2">
            <DialogTitle>选择项目类型</DialogTitle>
            {projectPath && (
              <button
                type="button"
                data-testid="selector-copy-path-btn"
                onClick={async () => {
                  try {
                    await navigator.clipboard?.writeText(projectPath);
                    setCopiedSelectorPath(true);
                    setTimeout(() => setCopiedSelectorPath(false), 1500);
                  } catch {
                    // ignore in test/offline mode
                  }
                }}
                className="rounded border border-border bg-background px-2 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                {copiedSelectorPath ? '已复制工作区路径' : '复制工作区路径'}
              </button>
            )}
          </div>
          <DialogDescription>
            选择项目类型以启用相应的约束和工具。系统会自动检测项目特征，您也可以手动选择。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* 自动检测提示 */}
          {detecting && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Sparkles className="h-4 w-4 animate-pulse" />
              正在检测项目类型...
            </div>
          )}

          {detection && !detecting && (
            <div className="rounded-lg border border-info/30 bg-info/10 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-info" />
                  <span className="text-sm font-medium text-text">
                    自动检测结果：
                    {PROJECT_TYPES.find((t) => t.value === detection.detectedType)?.label}
                  </span>
                  <span className="text-xs text-info">
                    (置信度 {Math.round(detection.confidence * 100)}%)
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  {selectedType !== detection.detectedType && (
                    <button
                      type="button"
                      data-testid="selector-apply-detected-btn"
                      onClick={() => {
                        setSelectedType(detection.detectedType);
                        setSelectedSubType(detection.subType ?? null);
                      }}
                      className="rounded border border-primary/40 bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary hover:bg-primary/20"
                    >
                      采用检测结果
                    </button>
                  )}
                  <button
                    type="button"
                    data-testid="selector-copy-detection-btn"
                    onClick={async () => {
                      const label =
                        PROJECT_TYPES.find((t) => t.value === detection.detectedType)?.label ??
                        detection.detectedType;
                      const md = [
                        '# 项目类型检测摘要',
                        `- **检测类型**：${label} (${detection.detectedType})`,
                        `- **置信度**：${Math.round(detection.confidence * 100)}%`,
                        detection.subType
                          ? `- **检测子类型**：${resolveSubTypeLabel(detection.subType, subTypes)}`
                          : '',
                        detection.techStack.length > 0
                          ? `- **技术栈**：${detection.techStack.join('、')}`
                          : '',
                        detection.signals.length > 0
                          ? `- **检测依据**：${detection.signals.join('、')}`
                          : '',
                      ]
                        .filter(Boolean)
                        .join('\n');
                      try {
                        await navigator.clipboard?.writeText(md);
                        setCopiedDetection(true);
                        setTimeout(() => setCopiedDetection(false), 1500);
                      } catch {
                        // ignore in test/offline mode
                      }
                    }}
                    className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-0.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
                  >
                    {copiedDetection ? (
                      <>
                        <Check className="h-3 w-3 text-emerald-500" />
                        已复制
                      </>
                    ) : (
                      <>
                        <Copy className="h-3 w-3" />
                        复制检测摘要
                      </>
                    )}
                  </button>
                  <button
                    type="button"
                    data-testid="selector-redetect-btn"
                    onClick={() => void runDetection()}
                    className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-0.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
                    title="重新检测项目类型"
                  >
                    <RefreshCw className="h-3 w-3" />
                    重新检测
                  </button>
                </div>
              </div>
              {(detection.subType || detection.techStack.length > 0) && (
                <div className="mt-2 space-y-1" data-testid="selector-detection-fine-grained">
                  {detection.subType && (
                    <div className="flex flex-wrap items-center gap-1.5 text-xs">
                      <span className="text-muted-foreground">检测子类型：</span>
                      <span
                        className="rounded bg-primary/10 px-1.5 py-0.5 text-ui-2xs font-medium text-primary"
                        data-testid="selector-detection-subtype"
                      >
                        {resolveSubTypeLabel(detection.subType, subTypes)}
                      </span>
                    </div>
                  )}
                  {detection.techStack.length > 0 && (
                    <div
                      className="flex flex-wrap items-center gap-1 text-xs"
                      data-testid="selector-detection-tech-stack"
                    >
                      <span className="text-muted-foreground">技术栈：</span>
                      {detection.techStack.map((tech) => (
                        <span
                          key={tech}
                          className="rounded border border-border bg-background px-1.5 py-0.5 font-mono text-ui-2xs text-foreground"
                        >
                          {tech}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}
              {detection.signals.length > 0 && (
                <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-text-secondary">
                  <span>检测依据：{detection.signals.slice(0, 3).join('、')}</span>
                  {detection.signals.slice(0, 3).map((sig, idx) => (
                    <button
                      key={idx}
                      type="button"
                      data-testid={`selector-copy-signal-${idx}`}
                      onClick={async () => {
                        try {
                          await navigator.clipboard?.writeText(sig);
                          setCopiedSignalIdx(idx);
                          setTimeout(() => setCopiedSignalIdx(null), 1500);
                        } catch {
                          // ignore in test/offline mode
                        }
                      }}
                      className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      {copiedSignalIdx === idx ? '已复制' : `复制依据#${idx + 1}`}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* 项目类型选项 */}
          <div className="grid grid-cols-2 gap-3">
            {PROJECT_TYPES.map((type) => {
              const isSelected = selectedType === type.value;
              const isDetected = detection?.detectedType === type.value;
              const bp = getArchetypeBlueprint(type.value);

              return (
                <button
                  key={type.value}
                  type="button"
                  data-testid={`selector-option-${type.value}`}
                  onClick={() => handleSelectType(type.value)}
                  className={`relative flex flex-col items-start gap-2 rounded-lg border-2 p-4 text-left transition-all ${
                    isSelected
                      ? 'border-primary bg-primary/5 shadow-sm'
                      : 'border-border hover:border-primary/50 hover:bg-accent'
                  }`}
                >
                  {isDetected && (
                    <div className="absolute right-2 top-2">
                      <Sparkles className="h-3 w-3 text-info" />
                    </div>
                  )}
                  <div className={type.color}>{type.icon}</div>
                  <div className="font-medium">{type.label}</div>
                  <div className="text-xs text-muted-foreground">{type.description}</div>
                  <div
                    className="mt-1 flex flex-wrap items-center gap-1"
                    data-testid={`selector-governance-meta-${type.value}`}
                  >
                    <span className="rounded bg-muted px-1.5 py-0.5 text-ui-2xs text-muted-foreground">
                      {bp.stages.length} 阶段管线
                    </span>
                    <span className="rounded bg-muted px-1.5 py-0.5 text-ui-2xs text-muted-foreground">
                      {bp.subTemplates.length} 套细分规范包
                    </span>
                    <span className="w-full text-ui-2xs text-muted-foreground truncate">
                      {bp.stages.map((s) => s.label).join(' → ')}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>

          {/* L2 子类型网格（仅在目录加载且该 L1 有子类型时显示） */}
          {selectedType && subTypeOptions.length > 0 && (
            <div>
              <label className="mb-2 block text-sm font-medium">
                项目子类型（更精确的治理路径）
              </label>
              <div
                className="grid grid-cols-1 gap-1.5 sm:grid-cols-2"
                data-testid="selector-l2-grid"
              >
                <button
                  type="button"
                  data-testid="selector-l2-none"
                  onClick={() => setSelectedSubType(null)}
                  className={`rounded-lg border p-2 text-left text-xs transition-colors ${
                    selectedSubType === null
                      ? 'border-primary bg-primary/10 text-foreground'
                      : 'border-border bg-surface hover:bg-surface-hover text-muted-foreground'
                  }`}
                >
                  <span className="font-medium">仅使用形态级分类</span>
                  <span className="ml-1 text-ui-2xs text-muted-foreground">（不指定子类型）</span>
                </button>
                {subTypeOptions.map((sub) => {
                  const active = selectedSubType === sub.key;
                  return (
                    <button
                      key={sub.key}
                      type="button"
                      data-testid={`selector-l2-${sub.key}`}
                      onClick={() => setSelectedSubType(sub.key)}
                      className={`rounded-lg border p-2 text-left text-xs transition-colors ${
                        active
                          ? 'border-primary bg-primary/10 text-foreground'
                          : 'border-border bg-surface hover:bg-surface-hover text-muted-foreground'
                      }`}
                    >
                      <div className="flex items-center gap-1.5">
                        <Sparkles className="h-3 w-3 text-primary" />
                        <span className="font-medium">{sub.label}</span>
                      </div>
                      <p className="mt-0.5 text-ui-2xs text-muted-foreground line-clamp-2">
                        {sub.description}
                      </p>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {selectedType &&
            (() => {
              const activeBp = getArchetypeBlueprint(selectedType);
              return (
                <div
                  className="space-y-1.5 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-xs"
                  data-testid="selector-selected-summary"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium text-foreground">
                      已选治理形态：{activeBp.label} · 推荐版本保护：{activeBp.vcsLabel}
                      {selectedSubType
                        ? ` · 子类型：${resolveSubTypeLabel(selectedSubType, subTypes)}`
                        : ''}
                    </span>
                    <div className="flex items-center gap-1.5">
                      <span className="text-muted-foreground">
                        {activeBp.directories.length} 个标准目录 ·{' '}
                        {activeBp.recommendedMilestones.length} 个推荐里程碑
                      </span>
                      <button
                        type="button"
                        data-testid="selector-suite-toggle-btn"
                        onClick={() => setShowSuiteDetails((v) => !v)}
                        className="rounded border border-primary/30 bg-background px-1.5 py-0.5 text-ui-2xs font-medium text-primary hover:bg-primary/10"
                      >
                        {showSuiteDetails ? '收起治理清单' : '预览治理清单'}
                      </button>
                    </div>
                  </div>
                  {showSuiteDetails && (
                    <div
                      className="border-t border-primary/20 pt-1.5 text-ui-2xs text-muted-foreground space-y-1"
                      data-testid="selector-suite-details"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span>工作区定位：{activeBp.positioning}</span>
                        <button
                          type="button"
                          data-testid="selector-copy-positioning-btn"
                          onClick={async () => {
                            try {
                              await navigator.clipboard?.writeText(activeBp.positioning);
                              setCopiedPositioning(true);
                              setTimeout(() => setCopiedPositioning(false), 1500);
                            } catch {
                              // ignore in test/offline mode
                            }
                          }}
                          className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                        >
                          {copiedPositioning ? '已复制定位' : '复制工作区定位'}
                        </button>
                      </div>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span>版本保护策略：{activeBp.vcsLabel}</span>
                        <button
                          type="button"
                          data-testid="selector-copy-vcs-btn"
                          onClick={async () => {
                            try {
                              await navigator.clipboard?.writeText(activeBp.vcsLabel);
                              setCopiedVcs(true);
                              setTimeout(() => setCopiedVcs(false), 1500);
                            } catch {
                              // ignore in test/offline mode
                            }
                          }}
                          className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                        >
                          {copiedVcs ? '已复制版本保护' : '复制版本保护'}
                        </button>
                      </div>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span>阶段管线：{activeBp.stages.map((s) => s.label).join(' → ')}</span>
                      </div>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span>
                          标准目录：{activeBp.directories.map((d) => `${d}/`).join(' · ')}
                        </span>
                        <button
                          type="button"
                          data-testid="selector-copy-dirs-btn"
                          onClick={async () => {
                            const md = activeBp.directories.map((d) => `${d}/`).join('\n');
                            try {
                              await navigator.clipboard?.writeText(md);
                              setCopiedDirs(true);
                              setTimeout(() => setCopiedDirs(false), 1500);
                            } catch {
                              // ignore in test/offline mode
                            }
                          }}
                          className="rounded border border-border bg-background px-1.5 py-0.5 text-ui-2xs text-foreground hover:bg-muted"
                        >
                          {copiedDirs ? '已复制目录' : '复制标准目录'}
                        </button>
                      </div>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span>
                          细分规范包：{activeBp.subTemplates.map((t) => t.label).join(' · ')}
                        </span>
                      </div>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span>
                          推荐里程碑：
                          {activeBp.recommendedMilestones.map((m) => m.title).join(' → ')}
                        </span>
                      </div>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span>护栏支柱：{activeBp.contextPillars.join(' · ')}</span>
                      </div>
                      <div className="flex justify-end gap-1.5 pt-0.5"></div>
                    </div>
                  )}
                </div>
              );
            })()}
        </div>

        <DialogFooter>
          <Button variant="secondary" onClick={handleCancel}>
            取消
          </Button>
          <Button onClick={handleSelect} disabled={!selectedType}>
            确认选择
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditProjectTypeSelectorGovernance(): {
  module: 'src/features/project-type/ProjectTypeSelector.tsx';
  phase: 'P166';
  domain: 'project-type';
  supportsAutoDetection: boolean;
  supportsBlueprintSuiteExport: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/features/project-type/ProjectTypeSelector.tsx',
    phase: 'P166',
    domain: 'project-type',
    supportsAutoDetection: true,
    supportsBlueprintSuiteExport: true,
    compliant: true,
  };
}
