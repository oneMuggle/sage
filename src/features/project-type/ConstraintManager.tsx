/**
 * 约束管理器 (2026-09-25；多项目形态细分规则包增强 2026-10-10)
 *
 * 项目类型分类系统 - Phase 4.4
 * 完整的约束 CRUD + 默认综合模板导入 + 细分领域预设规则包一键应用
 */

import { Plus, Trash2, Edit2, Download, Sparkles } from 'lucide-react';
import { useState, useEffect, useCallback } from 'react';

import { projectApi, type ProjectConstraint, type ProjectType } from '../../shared/api';
import { Button } from '../../shared/ui/Button';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';

import { ConstraintEditor } from './ConstraintEditor';
import { ArchetypeBlueprintMeta, getArchetypeBlueprint } from './archetypeBlueprints';

export interface ConstraintManagerProps {
  projectId: string;
  projectType?: ProjectType | null;
  className?: string;
}

export function ConstraintManager({ projectId, projectType, className }: ConstraintManagerProps) {
  const [constraints, setConstraints] = useState<ProjectConstraint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [editingConstraint, setEditingConstraint] = useState<ProjectConstraint | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [importingKey, setImportingKey] = useState<string | null>(null);

  const blueprint: ArchetypeBlueprintMeta = getArchetypeBlueprint(projectType);

  const loadConstraints = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await projectApi.listConstraints(projectId);
      setConstraints(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载约束失败');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void loadConstraints();
  }, [loadConstraints]);

  const handleToggleEnabled = async (constraint: ProjectConstraint) => {
    try {
      const updated = await projectApi.updateConstraint(projectId, constraint.id, {
        enabled: !constraint.enabled,
      });
      setConstraints((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
    } catch (err) {
      alert(err instanceof Error ? err.message : '更新失败');
    }
  };

  const handleDelete = async (constraint: ProjectConstraint) => {
    const ok = await confirmDialog({
      title: '删除约束',
      message: `确定删除约束「${constraint.category}」吗？`,
      danger: true,
    });
    if (!ok) return;
    try {
      await projectApi.deleteConstraint(projectId, constraint.id);
      setConstraints((prev) => prev.filter((c) => c.id !== constraint.id));
    } catch (err) {
      alert(err instanceof Error ? err.message : '删除失败');
    }
  };

  const handleImportTemplate = async () => {
    if (!projectType) {
      alert('请先设置项目类型');
      return;
    }
    try {
      setImportingKey(projectType);
      const imported = await projectApi.importConstraints(projectId, projectType);
      setConstraints((prev) => { const map = new Map(prev.map((item) => [item.id, item])); for (const item of imported) map.set(item.id, item); return Array.from(map.values()); });
    } catch (err) {
      alert(err instanceof Error ? err.message : '导入模板失败');
    } finally {
      setImportingKey(null);
    }
  };

  const handleApplySubTemplate = async (templateKey: string) => {
    try {
      setImportingKey(templateKey);
      const imported = await projectApi.importConstraints(projectId, templateKey);
      setConstraints((prev) => { const map = new Map(prev.map((item) => [item.id, item])); for (const item of imported) map.set(item.id, item); return Array.from(map.values()); });
    } catch (err) {
      alert(err instanceof Error ? err.message : '应用预设失败');
    } finally {
      setImportingKey(null);
    }
  };

  const handleCreate = () => {
    setEditingConstraint(null);
    setEditorOpen(true);
  };

  const handleEdit = (constraint: ProjectConstraint) => {
    setEditingConstraint(constraint);
    setEditorOpen(true);
  };

  const handleSave = async () => {
    await loadConstraints();
    setEditorOpen(false);
  };

  const categories = ['all', ...Array.from(new Set(constraints.map((c) => c.category)))];
  const filteredConstraints =
    selectedCategory === 'all'
      ? constraints
      : constraints.filter((c) => c.category === selectedCategory);

  return (
    <div className={`space-y-4 ${className ?? ''}`}>
      {/* 顶部操作栏 */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setSelectedCategory(cat)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                selectedCategory === cat
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground hover:bg-muted/80'
              }`}
            >
              {cat === 'all' ? '全部' : cat}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          {projectType && (
            <Button
              variant="secondary"
              size="sm"
              onClick={handleImportTemplate}
              disabled={importingKey !== null}
            >
              <Download className="mr-1.5 h-4 w-4" />
              导入模板
            </Button>
          )}
          <Button size="sm" onClick={handleCreate}>
            <Plus className="mr-1.5 h-4 w-4" />
            新建约束
          </Button>
        </div>
      </div>

      {/* 细分领域预设规则包（按项目形态动态推荐） */}
      {blueprint.subTemplates.length > 0 && (
        <div
          className="rounded-lg border border-border/70 bg-muted/20 p-3"
          data-testid="constraint-preset-packs"
        >
          <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <Sparkles className="h-3.5 w-3.5 text-primary" />
            <span>{blueprint.label} · 细分规范预设包（点击一键追加）：</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {blueprint.subTemplates.map((tpl) => (
              <button
                key={tpl.key}
                type="button"
                onClick={() => void handleApplySubTemplate(tpl.key)}
                disabled={importingKey !== null}
                title={tpl.description}
                className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:border-primary/50 hover:bg-primary/5 disabled:opacity-50"
              >
                <span>+ 预设：{tpl.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* 加载/错误状态 */}
      {loading && <div className="text-sm text-muted-foreground">加载中...</div>}
      {error && <div className="text-sm text-destructive">{error}</div>}

      {/* 约束列表 */}
      {!loading && !error && (
        <div className="space-y-2">
          {filteredConstraints.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
              暂无约束规则，点击「新建约束」或「导入默认模板」开始配置
            </div>
          ) : (
            filteredConstraints.map((constraint) => (
              <div
                key={constraint.id}
                className="flex items-start gap-3 rounded-lg border border-border bg-card p-4"
              >
                <input
                  type="checkbox"
                  checked={constraint.enabled}
                  onChange={() => void handleToggleEnabled(constraint)}
                  className="mt-1 h-4 w-4 rounded border-border"
                  aria-label={`启用约束：${constraint.category}`}
                />

                <div className="flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                      {constraint.category}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      优先级: {constraint.priority}
                    </span>
                    <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
                      触发: {constraint.triggerPattern || 'always'}
                    </span>
                  </div>
                  <p className="text-sm text-foreground">{constraint.content}</p>
                </div>

                <div className="flex items-center gap-1">
                  <button
                    onClick={() => handleEdit(constraint)}
                    className="rounded p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                    title="编辑"
                    aria-label={`编辑约束：${constraint.category}`}
                  >
                    <Edit2 className="h-4 w-4" />
                  </button>
                  <button
                    onClick={() => void handleDelete(constraint)}
                    className="rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                    title="删除"
                    aria-label={`删除约束：${constraint.category}`}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* 编辑器 Dialog */}
      <ConstraintEditor
        open={editorOpen}
        onOpenChange={setEditorOpen}
        projectId={projectId}
        constraint={editingConstraint}
        onSave={handleSave}
      />
    </div>
  );
}
