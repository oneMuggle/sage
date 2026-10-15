/**
 * 约束编辑器 (2026-09-25; Phase P26 四形态规则内容模板与全局触发快捷按钮 2026-10-13)
 *
 * 项目类型分类系统 - Phase 4.4
 * 创建/编辑约束的 Dialog
 */

import { useState, useEffect } from 'react';

import { projectApi, type ProjectConstraint, type ProjectType } from '../../shared/api';
import { Button } from '../../shared/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '../../shared/ui/Dialog/Dialog';
import { Input } from '../../shared/ui/Input';
import { Textarea } from '../../shared/ui/Textarea';

import { getArchetypeBlueprint } from './archetypeBlueprints';

const CATEGORY_PRESETS: Record<ProjectType, string[]> = {
  coding: ['code_style', 'git_commit', 'testing', 'architecture'],
  business: ['document_format', 'tone', 'review_process', 'compliance'],
  research: ['academic_writing', 'citation_style', 'data_integrity', 'reproducibility'],
  personal: ['note_organization', 'knowledge_linking', 'action_extraction'],
};

const CATEGORY_LABELS: Record<string, string> = {
  code_style: '代码风格',
  git_commit: '提交规范',
  testing: '测试门禁',
  architecture: '架构边界',
  document_format: '公文版式',
  tone: '行文语调',
  review_process: '审校流程',
  compliance: '法务合规',
  academic_writing: '学术写作',
  citation_style: '文献引证',
  data_integrity: '数据真实性',
  reproducibility: '实验可复现',
  note_organization: '卡片组织',
  knowledge_linking: '双链索引',
  action_extraction: '行动提炼',
};

const CONTENT_PRESETS: Record<
  ProjectType,
  Array<{ label: string; category: string; content: string; priority: number }>
> = {
  coding: [
    {
      label: 'TypeScript 严格类型',
      category: 'code_style',
      content: '禁止新增裸 any 类型，所有公共导出函数必须声明显式返回类型与入参契约。',
      priority: 8,
    },
    {
      label: '异常显式捕获',
      category: 'architecture',
      content: '严禁静默吞没异常（except Exception: pass），必须捕获具体异常元组并记录上下文。',
      priority: 9,
    },
  ],
  business: [
    {
      label: '金额双写与主体核验',
      category: 'compliance',
      content: '所有合同与请示金额须同时标注人民币大写与阿拉伯数字，并核验签约主体全称一致性。',
      priority: 9,
    },
    {
      label: 'GB/T 9704 层级序号',
      category: 'document_format',
      content: '正文结构严格遵循“一、（一）、1.、（1）”四级标题序号规范，严禁跨级混用。',
      priority: 8,
    },
  ],
  research: [
    {
      label: '零虚构文献引用',
      category: 'citation_style',
      content: '严禁捏造未在 references/ 或受控资料库中核实的文献条目、DOI 或实验基线数据。',
      priority: 10,
    },
    {
      label: '实验随机种子留痕',
      category: 'reproducibility',
      content: '所有定量实验与消融对比必须固定并记录随机种子、超参数配置与评估脚本路径。',
      priority: 8,
    },
  ],
  personal: [
    {
      label: '卡片双向链接',
      category: 'knowledge_linking',
      content: '沉淀长期笔记时优先建立 [[概念卡片]] 双向索引并提炼 3 条以内核心结论。',
      priority: 7,
    },
    {
      label: '待办行动项闭环',
      category: 'action_extraction',
      content: '每次周记或复盘末尾提炼可执行的下一步行动项（含截止日期与验收标准）。',
      priority: 7,
    },
  ],
};

export interface ConstraintEditorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  projectType?: ProjectType | null;
  constraint: ProjectConstraint | null; // null = create mode
  onSave: () => void;
}

export function ConstraintEditor({
  open,
  onOpenChange,
  projectId,
  projectType,
  constraint,
  onSave,
}: ConstraintEditorProps) {
  const blueprint = getArchetypeBlueprint(projectType);
  const categoryPresets = CATEGORY_PRESETS[blueprint.type] ?? CATEGORY_PRESETS.coding;
  const contentPresets = CONTENT_PRESETS[blueprint.type] ?? CONTENT_PRESETS.coding;
  const [category, setCategory] = useState('');
  const [content, setContent] = useState('');
  const [triggerPattern, setTriggerPattern] = useState('');
  const [priority, setPriority] = useState(5);
  const [enabled, setEnabled] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 编辑模式时填充表单
  useEffect(() => {
    if (constraint) {
      setCategory(constraint.category);
      setContent(constraint.content);
      setTriggerPattern(constraint.triggerPattern || '');
      setPriority(constraint.priority);
      setEnabled(constraint.enabled);
    } else {
      // 创建模式重置表单
      setCategory('');
      setContent('');
      setTriggerPattern('');
      setPriority(5);
      setEnabled(true);
    }
    setError(null);
  }, [constraint, open]);

  const handleSave = async () => {
    if (!category.trim() || !content.trim()) {
      setError('类别和内容不能为空');
      return;
    }

    try {
      setSaving(true);
      setError(null);

      if (constraint) {
        // 更新
        await projectApi.updateConstraint(projectId, constraint.id, {
          category: category.trim(),
          content: content.trim(),
          triggerPattern: triggerPattern.trim() || undefined,
          priority,
          enabled,
        });
      } else {
        // 创建
        await projectApi.createConstraint(projectId, {
          category: category.trim(),
          content: content.trim(),
          triggerPattern: triggerPattern.trim() || undefined,
          priority,
        });
      }

      onSave();
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{constraint ? '编辑约束' : '新建约束'}</DialogTitle>
          <DialogDescription>
            约束用于规范项目工作流程，定义代码风格、文档格式、Git 提交规范等规则。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
              {error}
            </div>
          )}

          <div className="space-y-2">
            <label className="text-sm font-medium">类别 *</label>
            <Input
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              placeholder="例如: code-style, git-commit, writing-format"
            />
            <div
              className="flex flex-wrap items-center gap-1.5"
              data-testid="constraint-editor-category-presets"
            >
              <span className="text-xs text-muted-foreground">推荐类别：</span>
              {categoryPresets.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => setCategory(preset)}
                  className="rounded border border-border bg-muted/40 px-2 py-0.5 font-mono text-xs text-foreground hover:bg-muted"
                >
                  {CATEGORY_LABELS[preset] ? `${CATEGORY_LABELS[preset]} (${preset})` : preset}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">内容 *</label>
            <Textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="描述具体的约束规则..."
              rows={4}
            />
            <div
              className="flex flex-wrap items-center gap-1.5"
              data-testid="constraint-editor-content-presets"
            >
              <span className="text-xs text-muted-foreground">快速填入规则示例：</span>
              {contentPresets.map((tpl, idx) => (
                <button
                  key={tpl.label}
                  type="button"
                  data-testid={`constraint-content-preset-${idx}`}
                  onClick={() => {
                    setCategory(tpl.category);
                    setContent(tpl.content);
                    setPriority(tpl.priority);
                  }}
                  className="rounded border border-primary/30 bg-primary/5 px-2 py-0.5 text-xs text-primary hover:bg-primary/10"
                >
                  {tpl.label}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">触发条件</label>
            <Input
              value={triggerPattern}
              onChange={(e) => setTriggerPattern(e.target.value)}
              placeholder="glob 模式（如 src/**/*.ts）或 'always'"
            />
            <div
              className="flex flex-wrap items-center gap-1.5"
              data-testid="constraint-editor-glob-presets"
            >
              <span className="text-xs text-muted-foreground">目录触发预设：</span>
              <button
                type="button"
                data-testid="constraint-glob-always-btn"
                onClick={() => setTriggerPattern('always')}
                className="rounded border border-primary/30 bg-primary/5 px-2 py-0.5 font-mono text-xs text-primary hover:bg-primary/10"
              >
                always (全局)
              </button>
              {blueprint.directories.map((dir) => (
                <button
                  key={dir}
                  type="button"
                  onClick={() => setTriggerPattern(`${dir}/**`)}
                  className="rounded border border-border bg-muted/40 px-2 py-0.5 font-mono text-xs text-foreground hover:bg-muted"
                >
                  {dir}/**
                </button>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">留空表示 always（始终生效）</p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">优先级 (1-10)</label>
              <Input
                type="number"
                min={1}
                max={10}
                value={priority}
                onChange={(e) => setPriority(Number(e.target.value))}
              />
              <div
                className="flex flex-wrap items-center gap-1"
                data-testid="constraint-priority-presets"
              >
                {(
                  [
                    { val: 10, label: 'P10 铁律' },
                    { val: 8, label: 'P8 强规范' },
                    { val: 5, label: 'P5 常规' },
                    { val: 3, label: 'P3 建议' },
                  ] as const
                ).map((p) => (
                  <button
                    key={p.val}
                    type="button"
                    data-testid={`constraint-priority-preset-${p.val}`}
                    onClick={() => setPriority(p.val)}
                    className={`rounded border px-1.5 py-0.5 text-ui-2xs transition-colors ${
                      priority === p.val
                        ? 'border-primary bg-primary/10 text-primary font-medium'
                        : 'border-border bg-muted/40 text-muted-foreground hover:bg-muted'
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">状态</label>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="enabled"
                  checked={enabled}
                  onChange={(e) => setEnabled(e.target.checked)}
                  className="h-4 w-4"
                />
                <label htmlFor="enabled" className="text-sm">
                  {enabled ? '启用' : '禁用'}
                </label>
              </div>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? '保存中...' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
