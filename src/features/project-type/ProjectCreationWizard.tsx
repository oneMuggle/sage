/**
 * 项目创建向导 (2026-09-25)
 *
 * 项目类型分类系统 - Phase 9.4.1
 * 完整的项目创建流程：
 * 1. 目录选择（调用原生文件选择器）
 * 2. 自动类型检测预览
 * 3. 类型选择（可覆盖检测结果）
 * 4. 确认创建（注册项目 + 设置类型）
 */

import { useState, useCallback } from 'react';
import {
  FolderOpen,
  Code,
  BookOpen,
  Briefcase,
  User,
  Sparkles,
  ArrowRight,
  ArrowLeft,
  Check,
  Loader2,
} from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '../../shared/ui/Dialog/Dialog';
import { Button } from '../../shared/ui/Button';
import { Input } from '../../shared/ui/Input';
import { Badge } from '../../shared/ui/Badge';
import { TypeDetectionPreview } from './TypeDetectionPreview';
import { projectApi, type ProjectType, type ProjectTypeDetectionResult } from '../../shared/api';

export interface ProjectCreationWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 创建成功后的回调，返回新创建的项目 ID */
  onCreated: (projectId: string) => void;
}

type WizardStep = 'directory' | 'type' | 'confirm';

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
    icon: <Code className="h-5 w-5" />,
    color: 'text-blue-500',
  },
  {
    value: 'research',
    label: '科研项目',
    description: '学术研究、论文写作。文献管理，实验记录，学术写作规范。',
    icon: <BookOpen className="h-5 w-5" />,
    color: 'text-purple-500',
  },
  {
    value: 'business',
    label: '事务项目',
    description: '商业文档、报告撰写。模板约束，审批流程，格式规范。',
    icon: <Briefcase className="h-5 w-5" />,
    color: 'text-green-500',
  },
  {
    value: 'personal',
    label: '个人项目',
    description: '个人笔记、日记、学习。灵活组织，隐私保护。',
    icon: <User className="h-5 w-5" />,
    color: 'text-orange-500',
  },
];

const STEP_LABELS: Record<WizardStep, string> = {
  directory: '选择目录',
  type: '选择类型',
  confirm: '确认创建',
};

const STEPS: WizardStep[] = ['directory', 'type', 'confirm'];

export function ProjectCreationWizard({
  open,
  onOpenChange,
  onCreated,
}: ProjectCreationWizardProps) {
  const [step, setStep] = useState<WizardStep>('directory');
  const [directoryPath, setDirectoryPath] = useState('');
  const [selectedType, setSelectedType] = useState<ProjectType | null>(null);
  const [detectionResult, setDetectionResult] = useState<ProjectTypeDetectionResult | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [detectError, setDetectError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const resetState = useCallback(() => {
    setStep('directory');
    setDirectoryPath('');
    setSelectedType(null);
    setDetectionResult(null);
    setDetecting(false);
    setDetectError(null);
    setCreating(false);
    setCreateError(null);
  }, []);

  const handleOpenChange = (newOpen: boolean) => {
    if (!newOpen) resetState();
    onOpenChange(newOpen);
  };

  const handleBrowse = async () => {
    const api = (
      window as unknown as {
        electronAPI?: {
          selectDirectory: (opts: { intent: string }) => Promise<string | null>;
        };
      }
    ).electronAPI;
    if (!api?.selectDirectory) return;

    try {
      const picked = await api.selectDirectory({ intent: 'open' });
      if (picked) {
        setDirectoryPath(picked);
        // 选择目录后自动检测类型
        setDetecting(true);
        setDetectError(null);
        try {
          const result = await projectApi.detectType(picked);
          setDetectionResult(result);
          if (result.confidence >= 0.7) {
            setSelectedType(result.detectedType);
          }
        } catch {
          // 检测失败不阻塞流程
        } finally {
          setDetecting(false);
        }
      }
    } catch {
      // 用户取消或选择器失败
    }
  };

  const handleNext = () => {
    const currentIdx = STEPS.indexOf(step);
    if (currentIdx < STEPS.length - 1) {
      setStep(STEPS[currentIdx + 1]);
    }
  };

  const handleBack = () => {
    const currentIdx = STEPS.indexOf(step);
    if (currentIdx > 0) {
      setStep(STEPS[currentIdx - 1]);
    }
  };

  const handleCreate = async () => {
    if (!directoryPath) return;

    try {
      setCreating(true);
      setCreateError(null);

      const project = await projectApi.register(directoryPath, {
        projectType: selectedType ?? undefined,
      });

      onCreated(project.id);
      handleOpenChange(false);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : '创建项目失败');
    } finally {
      setCreating(false);
    }
  };

  const canProceed = () => {
    switch (step) {
      case 'directory':
        return directoryPath.length > 0;
      case 'type':
        return selectedType !== null;
      case 'confirm':
        return true;
    }
  };

  const selectedTypeOption = PROJECT_TYPES.find((t) => t.value === selectedType);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>创建新项目</DialogTitle>
          <DialogDescription>
            选择项目目录和类型，系统将自动配置相应的约束和工具。
          </DialogDescription>
        </DialogHeader>

        {/* 步骤指示器 */}
        <div className="flex items-center gap-2 border-b pb-3">
          {STEPS.map((s, idx) => {
            const isCurrent = s === step;
            const isDone = STEPS.indexOf(step) > idx;
            return (
              <div key={s} className="flex items-center gap-2">
                <div
                  className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-medium ${
                    isCurrent
                      ? 'bg-primary text-primary-foreground'
                      : isDone
                        ? 'bg-green-500 text-white'
                        : 'bg-muted text-muted-foreground'
                  }`}
                >
                  {isDone ? <Check className="h-3 w-3" /> : idx + 1}
                </div>
                <span
                  className={`text-sm ${isCurrent ? 'font-medium text-foreground' : 'text-muted-foreground'}`}
                >
                  {STEP_LABELS[s]}
                </span>
                {idx < STEPS.length - 1 && (
                  <ArrowRight className="mx-1 h-3 w-3 text-muted-foreground" />
                )}
              </div>
            );
          })}
        </div>

        {/* Step 1: 目录选择 */}
        {step === 'directory' && (
          <div className="space-y-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">项目目录</label>
              <div className="flex gap-2">
                <Input
                  value={directoryPath}
                  onChange={(e) => setDirectoryPath(e.target.value)}
                  placeholder="/path/to/your/project"
                  className="flex-1"
                />
                <Button variant="secondary" onClick={handleBrowse}>
                  <FolderOpen className="mr-2 h-4 w-4" />
                  浏览
                </Button>
              </div>
            </div>

            {/* 检测预览 */}
            {directoryPath && (
              <TypeDetectionPreview
                result={detectionResult}
                loading={detecting}
                error={detectError}
                selectedType={selectedType}
              />
            )}
          </div>
        )}

        {/* Step 2: 类型选择 */}
        {step === 'type' && (
          <div className="space-y-4">
            {/* 检测预览 */}
            <TypeDetectionPreview
              result={detectionResult}
              loading={detecting}
              error={detectError}
              selectedType={selectedType}
            />

            {/* 类型选项 */}
            <div className="grid grid-cols-2 gap-3">
              {PROJECT_TYPES.map((type) => {
                const isSelected = selectedType === type.value;
                const isDetected = detectionResult?.detectedType === type.value;

                return (
                  <button
                    key={type.value}
                    type="button"
                    onClick={() => setSelectedType(type.value)}
                    className={`relative flex flex-col items-start gap-2 rounded-lg border-2 p-4 text-left transition-all ${
                      isSelected
                        ? 'border-primary bg-primary/5 shadow-sm'
                        : 'border-border hover:border-primary/50 hover:bg-accent'
                    }`}
                  >
                    {isDetected && (
                      <div className="absolute right-2 top-2">
                        <Sparkles className="h-3 w-3 text-blue-500" />
                      </div>
                    )}
                    <div className={type.color}>{type.icon}</div>
                    <div className="font-medium">{type.label}</div>
                    <div className="text-xs text-muted-foreground">{type.description}</div>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* Step 3: 确认 */}
        {step === 'confirm' && (
          <div className="space-y-4">
            {createError && (
              <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
                {createError}
              </div>
            )}

            <div className="space-y-3 rounded-lg border p-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">项目目录</span>
                <span className="text-sm font-medium">{directoryPath}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">项目类型</span>
                {selectedTypeOption ? (
                  <Badge>
                    <span className={`mr-1 ${selectedTypeOption.color}`}>
                      {selectedTypeOption.icon}
                    </span>
                    {selectedTypeOption.label}
                  </Badge>
                ) : (
                  <span className="text-sm text-muted-foreground">未指定（使用自动检测）</span>
                )}
              </div>
              {detectionResult && (
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">检测结果</span>
                  <span className="text-sm">
                    {PROJECT_TYPES.find((t) => t.value === detectionResult.detectedType)?.label}
                    <span className="ml-1 text-xs text-muted-foreground">
                      ({Math.round(detectionResult.confidence * 100)}%)
                    </span>
                  </span>
                </div>
              )}
            </div>

            <p className="text-xs text-muted-foreground">
              创建后可在设置中随时更改项目类型和约束。
            </p>
          </div>
        )}

        <DialogFooter>
          {step !== 'directory' && (
            <Button variant="ghost" onClick={handleBack}>
              <ArrowLeft className="mr-2 h-4 w-4" />
              上一步
            </Button>
          )}
          <div className="flex-1" />
          {step !== 'confirm' ? (
            <Button onClick={handleNext} disabled={!canProceed()}>
              下一步
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          ) : (
            <Button onClick={handleCreate} disabled={creating}>
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
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
