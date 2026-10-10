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
  type ProjectType,
  type ProjectTypeDetectionResult,
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

import { TypeDetectionPreview } from './TypeDetectionPreview';
import { ARCHETYPE_BLUEPRINTS, getArchetypeBlueprint } from './archetypeBlueprints';

export interface ProjectCreationWizardProps {
  /** 是否打开向导 */
  open: boolean;
  /** 关闭向导回调 */
  onOpenChange: (open: boolean) => void;
  /** 创建成功回调 */
  onSuccess?: (project: ProjectSummary) => void;
}

type WizardStep = 'folder' | 'type' | 'confirm';

export function ProjectCreationWizard({
  open,
  onOpenChange,
  onSuccess,
}: ProjectCreationWizardProps) {
  const [step, setStep] = useState<WizardStep>('folder');
  const [folderPath, setFolderPath] = useState<string>('');
  const [detecting, setDetecting] = useState(false);
  const [detectionResult, setDetectionResult] = useState<ProjectTypeDetectionResult | null>(null);
  const [detectionError, setDetectionError] = useState<string | null>(null);
  const [selectedType, setSelectedType] = useState<ProjectType | null>(null);
  const [autoScaffold, setAutoScaffold] = useState<boolean>(true);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const resetWizard = () => {
    setStep('folder');
    setFolderPath('');
    setDetecting(false);
    setDetectionResult(null);
    setDetectionError(null);
    setSelectedType(null);
    setAutoScaffold(true);
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

  const handleNextToType = async () => {
    if (!folderPath) return;

    setStep('type');
    setDetecting(true);
    setDetectionError(null);

    try {
      const result = await projectApi.detectType(folderPath);
      setDetectionResult(result);
      if (result.confidence >= 0.7) {
        setSelectedType(result.detectedType);
      } else {
        setSelectedType('business');
      }
    } catch (err) {
      setDetectionError(err instanceof Error ? err.message : '检测失败');
      setSelectedType('business');
    } finally {
      setDetecting(false);
    }
  };

  const handleNextToConfirm = () => {
    setStep('confirm');
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
            {step === 'type' && '步骤 2/3：确认项目形态（代码工程 / 一般档案 / 科学研究 / 个人空间）'}
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

          {/* Step 2: 选择项目类型 */}
          {step === 'type' && (
            <div className="space-y-4">
              <TypeDetectionPreview
                result={detectionResult}
                loading={detecting}
                error={detectionError}
                selectedType={selectedType}
              />

              <div>
                <label className="mb-2 block text-sm font-medium">
                  选择项目形态（决定目录结构、VCS 快照模式与 AI 上下文护栏）
                </label>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {Object.values(ARCHETYPE_BLUEPRINTS).map((bp) => {
                    const active = (selectedType ?? detectionResult?.detectedType ?? 'business') === bp.type;
                    return (
                      <button
                        key={bp.type}
                        type="button"
                        disabled={detecting}
                        onClick={() => setSelectedType(bp.type)}
                        data-testid={`wizard-archetype-${bp.type}`}
                        className={`rounded-lg border p-3 text-left transition-colors ${
                          active
                            ? 'border-primary bg-primary/10 text-foreground'
                            : 'border-border bg-surface hover:bg-surface-hover text-muted-foreground'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-xs font-semibold text-foreground">{bp.label}</span>
                          <span className="rounded bg-background/80 px-1.5 py-0.5 text-2xs text-muted-foreground">
                            {bp.vcsLabel}
                          </span>
                        </div>
                        <p className="mt-1 text-2xs text-muted-foreground line-clamp-2">
                          {bp.positioning}
                        </p>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          )}

          {/* Step 3: 确认信息与组织脚手架 */}
          {step === 'confirm' && (
            <div className="space-y-4">
              <div className="rounded-lg border border-border bg-muted/30 p-4 space-y-2.5">
                <div>
                  <span className="text-xs font-medium text-muted-foreground">项目路径：</span>
                  <div className="mt-0.5 text-sm font-mono break-all">{folderPath}</div>
                </div>
                <div className="flex flex-wrap items-center gap-4">
                  <div>
                    <span className="text-xs font-medium text-muted-foreground">项目形态：</span>
                    <span className="ml-1 text-sm font-semibold text-foreground">
                      {blueprint.label} ({blueprint.type})
                    </span>
                  </div>
                  <div>
                    <span className="text-xs font-medium text-muted-foreground">版本控制：</span>
                    <span className="ml-1 text-xs text-foreground">{blueprint.vcsLabel}</span>
                  </div>
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
                      <span>一键初始化「{blueprint.label}」推荐组织结构（幂等、不覆盖已有文件）</span>
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
              <Button type="button" onClick={handleNextToType} disabled={!folderPath || detecting}>
                下一步
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </>
          )}

          {step === 'type' && (
            <>
              <Button
                type="button"
                variant="ghost"
                onClick={() => setStep('folder')}
                disabled={detecting}
              >
                <ArrowLeft className="mr-2 h-4 w-4" />
                上一步
              </Button>
              <Button type="button" onClick={handleNextToConfirm} disabled={detecting}>
                下一步
                <ArrowRight className="ml-2 h-4 w-4" />
              </Button>
            </>
          )}

          {step === 'confirm' && (
            <>
              <Button
                type="button"
                variant="ghost"
                onClick={() => setStep('type')}
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
