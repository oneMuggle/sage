/**
 * 约束管理器 (2026-09-25)
 *
 * 项目类型分类系统 - Phase 4.4
 * 约束的 CRUD 界面：列表、创建、编辑、删除、导入模板
 */

import { Plus, Edit2, Trash2, Download, Shield, AlertCircle } from 'lucide-react';
import { useState, useEffect } from 'react';

import { projectApi, type ProjectConstraint, type ProjectType } from '../../shared/api';
import { Badge } from '../../shared/ui/Badge';
import { Button } from '../../shared/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '../../shared/ui/Card';

import { ConstraintEditor } from './ConstraintEditor';

export interface ConstraintManagerProps {
  projectId: string;
  projectType?: ProjectType | null;
}

export function ConstraintManager({ projectId, projectType }: ConstraintManagerProps) {
  const [constraints, setConstraints] = useState<ProjectConstraint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingConstraint, setEditingConstraint] = useState<ProjectConstraint | null>(null);

  const fetchConstraints = async () => {
    try {
      setLoading(true);
      const list = await projectApi.listConstraints(projectId);
      setConstraints(list.sort((a, b) => b.priority - a.priority));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '获取约束失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConstraints();
  }, [projectId]);

  const handleCreate = () => {
    setEditingConstraint(null);
    setEditorOpen(true);
  };

  const handleEdit = (constraint: ProjectConstraint) => {
    setEditingConstraint(constraint);
    setEditorOpen(true);
  };

  const handleDelete = async (constraintId: string) => {
    if (!confirm('确定要删除此约束吗？')) return;
    try {
      await projectApi.deleteConstraint(constraintId);
      await fetchConstraints();
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除约束失败');
    }
  };

  const handleImportTemplate = async () => {
    if (!projectType) {
      setError('请先设置项目类型');
      return;
    }
    try {
      await projectApi.importConstraints(projectId, projectType);
      await fetchConstraints();
    } catch (err) {
      setError(err instanceof Error ? err.message : '导入模板失败');
    }
  };

  const handleEditorSave = async () => {
    setEditorOpen(false);
    await fetchConstraints();
  };

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Shield className="h-5 w-5" />
            约束管理
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-sm text-muted-foreground">加载中...</div>
        </CardContent>
      </Card>
    );
  }

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Shield className="h-5 w-5" />
              约束管理
            </CardTitle>
            <div className="flex gap-2">
              {projectType && (
                <Button variant="secondary" size="sm" onClick={handleImportTemplate}>
                  <Download className="mr-2 h-4 w-4" />
                  导入模板
                </Button>
              )}
              <Button size="sm" onClick={handleCreate}>
                <Plus className="mr-2 h-4 w-4" />
                新建约束
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {error && (
            <div className="mb-4 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
              <AlertCircle className="h-4 w-4" />
              {error}
            </div>
          )}

          {constraints.length === 0 ? (
            <div className="py-8 text-center">
              <Shield className="mx-auto h-12 w-12 text-muted-foreground/50" />
              <p className="mt-4 text-sm text-muted-foreground">暂无约束</p>
              <p className="mt-1 text-xs text-muted-foreground">创建约束以规范项目工作流程</p>
            </div>
          ) : (
            <div className="space-y-3">
              {constraints.map((constraint) => (
                <div
                  key={constraint.id}
                  className="flex items-start justify-between rounded-lg border p-3"
                >
                  <div className="flex-1 space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{constraint.category}</span>
                      <Badge variant={constraint.enabled ? 'default' : 'secondary'}>
                        {constraint.enabled ? '启用' : '禁用'}
                      </Badge>
                      <Badge variant="outline">优先级 {constraint.priority}</Badge>
                    </div>
                    <p className="text-sm text-muted-foreground">{constraint.content}</p>
                    {constraint.triggerPattern && (
                      <p className="text-xs text-muted-foreground">
                        触发条件: {constraint.triggerPattern}
                      </p>
                    )}
                  </div>
                  <div className="flex gap-1">
                    <Button variant="ghost" size="sm" onClick={() => handleEdit(constraint)}>
                      <Edit2 className="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => handleDelete(constraint.id)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <ConstraintEditor
        open={editorOpen}
        onOpenChange={setEditorOpen}
        projectId={projectId}
        constraint={editingConstraint}
        onSave={handleEditorSave}
      />
    </>
  );
}
