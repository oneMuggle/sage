/**
 * 项目类型选择器 (2026-09-24)
 *
 * 项目类型分类系统 - Phase 4.1
 * 用于在项目创建/编辑时选择项目类型，支持自动检测建议
 */

import { Code, BookOpen, Briefcase, User, Sparkles } from 'lucide-react';
import { useState, useEffect } from 'react';

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
    color: 'text-blue-500',
  },
  {
    value: 'research',
    label: '科研项目',
    description: '学术研究、论文写作。文献管理，实验记录，学术写作规范。',
    icon: <BookOpen className="h-6 w-6" />,
    color: 'text-purple-500',
  },
  {
    value: 'business',
    label: '事务项目',
    description: '商业文档、报告撰写。模板约束，审批流程，格式规范。',
    icon: <Briefcase className="h-6 w-6" />,
    color: 'text-green-500',
  },
  {
    value: 'personal',
    label: '个人项目',
    description: '个人笔记、日记、学习。灵活组织，隐私保护。',
    icon: <User className="h-6 w-6" />,
    color: 'text-orange-500',
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

  // 自动检测项目类型
  useEffect(() => {
    if (!open || !projectPath) return;

    setDetecting(true);
    projectApi
      .detectType(projectPath)
      .then((result) => {
        setDetection(result);
        // 置信度高时自动选择
        if (result.confidence >= 0.7) {
          setSelectedType(result.detectedType);
        }
      })
      .catch(() => {
        // 检测失败时不阻塞用户
      })
      .finally(() => {
        setDetecting(false);
      });
  }, [open, projectPath]);

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
            <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 dark:border-blue-800 dark:bg-blue-950">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-blue-500" />
                <span className="text-sm font-medium text-blue-900 dark:text-blue-100">
                  自动检测结果：
                  {PROJECT_TYPES.find((t) => t.value === detection.detectedType)?.label}
                </span>
                <span className="text-xs text-blue-600 dark:text-blue-400">
                  (置信度 {Math.round(detection.confidence * 100)}%)
                </span>
              </div>
              {detection.signals.length > 0 && (
                <div className="mt-2 text-xs text-blue-700 dark:text-blue-300">
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
