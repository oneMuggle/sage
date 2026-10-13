/**
 * 项目类型选择器 (2026-09-24; Phase P29 手动重新检测、一键采用检测结果与生命周期阶段管线预览)
 *
 * 项目类型分类系统 - Phase 4.1
 * 用于在项目创建/编辑时选择项目类型，支持自动检测建议、重新检测与四形态阶段管线预览
 */

import { Code, BookOpen, Briefcase, User, Sparkles, RefreshCw } from 'lucide-react';
import { useState, useEffect, useCallback } from 'react';

import { projectApi, type ProjectType, type ProjectTypeDetectionResult } from '../../shared/api';
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

export interface ProjectTypeSelectorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectPath: string;
  onSelect: (type: ProjectType) => void;
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
  onCancel,
}: ProjectTypeSelectorProps) {
  const [selectedType, setSelectedType] = useState<ProjectType | null>(null);
  const [detection, setDetection] = useState<ProjectTypeDetectionResult | null>(null);
  const [detecting, setDetecting] = useState(false);

  const runDetection = useCallback(async () => {
    if (!projectPath || typeof projectApi?.detectType !== 'function') return;
    setDetecting(true);
    try {
      const result = await projectApi.detectType(projectPath);
      setDetection(result);
      if (result.confidence >= 0.7) {
        setSelectedType(result.detectedType);
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

  const handleSelect = () => {
    if (selectedType) {
      onSelect(selectedType);
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
          <DialogTitle>选择项目类型</DialogTitle>
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
                      onClick={() => setSelectedType(detection.detectedType)}
                      className="rounded border border-primary/40 bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary hover:bg-primary/20"
                    >
                      采用检测结果
                    </button>
                  )}
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
              {detection.signals.length > 0 && (
                <div className="mt-2 text-xs text-text-secondary">
                  检测依据：{detection.signals.slice(0, 3).join('、')}
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
                  onClick={() => setSelectedType(type.value)}
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
