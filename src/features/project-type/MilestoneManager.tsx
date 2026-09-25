/**
 * 里程碑管理器 (2026-09-25)
 *
 * 项目类型分类系统 - Phase 4.5
 * 里程碑的 CRUD 界面：列表、创建、编辑、删除、状态更新
 */

import { Plus, Edit2, Trash2, Target, CheckCircle2, Clock, AlertCircle } from 'lucide-react';
import { useState, useEffect } from 'react';

import { projectApi, type ProjectMilestone } from '../../shared/api';
import { Badge } from '../../shared/ui/Badge';
import { Button } from '../../shared/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '../../shared/ui/Card';

import { MilestoneEditor } from './MilestoneEditor';

export interface MilestoneManagerProps {
  projectId: string;
}

export function MilestoneManager({ projectId }: MilestoneManagerProps) {
  const [milestones, setMilestones] = useState<ProjectMilestone[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingMilestone, setEditingMilestone] = useState<ProjectMilestone | null>(null);

  const fetchMilestones = async () => {
    try {
      setLoading(true);
      const list = await projectApi.listMilestones(projectId);
      setMilestones(list.sort((a, b) => a.sortOrder - b.sortOrder));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '获取里程碑失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMilestones();
  }, [projectId]);

  const handleCreate = () => {
    setEditingMilestone(null);
    setEditorOpen(true);
  };

  const handleEdit = (milestone: ProjectMilestone) => {
    setEditingMilestone(milestone);
    setEditorOpen(true);
  };

  const handleDelete = async (milestoneId: string) => {
    if (!confirm('确定要删除此里程碑吗？')) return;
    try {
      await projectApi.deleteMilestone(milestoneId);
      await fetchMilestones();
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除里程碑失败');
    }
  };

  const handleStatusChange = async (milestoneId: string, status: string) => {
    try {
      await projectApi.updateMilestone(milestoneId, { status });
      await fetchMilestones();
    } catch (err) {
      setError(err instanceof Error ? err.message : '更新状态失败');
    }
  };

  const handleEditorSave = async () => {
    setEditorOpen(false);
    await fetchMilestones();
  };

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Target className="h-5 w-5" />
            里程碑管理
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
              <Target className="h-5 w-5" />
              里程碑管理
            </CardTitle>
            <Button size="sm" onClick={handleCreate}>
              <Plus className="mr-2 h-4 w-4" />
              新建里程碑
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {error && (
            <div className="mb-4 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
              <AlertCircle className="h-4 w-4" />
              {error}
            </div>
          )}

          {milestones.length === 0 ? (
            <div className="py-8 text-center">
              <Target className="mx-auto h-12 w-12 text-muted-foreground/50" />
              <p className="mt-4 text-sm text-muted-foreground">暂无里程碑</p>
              <p className="mt-1 text-xs text-muted-foreground">创建里程碑以跟踪项目进度</p>
            </div>
          ) : (
            <div className="space-y-3">
              {milestones.map((milestone) => (
                <div
                  key={milestone.id}
                  className="flex items-start justify-between rounded-lg border p-3"
                >
                  <div className="flex-1 space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{milestone.title}</span>
                      <StatusBadge status={milestone.status} />
                      {milestone.stage && <Badge variant="outline">{milestone.stage}</Badge>}
                    </div>
                    {milestone.description && (
                      <p className="text-sm text-muted-foreground">{milestone.description}</p>
                    )}
                    {milestone.dueDate && (
                      <p className="text-xs text-muted-foreground">截止日期: {milestone.dueDate}</p>
                    )}
                    {/* 状态切换按钮 */}
                    <div className="flex gap-1 pt-2">
                      {milestone.status !== 'pending' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleStatusChange(milestone.id, 'pending')}
                        >
                          待开始
                        </Button>
                      )}
                      {milestone.status !== 'in_progress' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleStatusChange(milestone.id, 'in_progress')}
                        >
                          进行中
                        </Button>
                      )}
                      {milestone.status !== 'completed' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleStatusChange(milestone.id, 'completed')}
                        >
                          完成
                        </Button>
                      )}
                      {milestone.status !== 'blocked' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleStatusChange(milestone.id, 'blocked')}
                        >
                          阻塞
                        </Button>
                      )}
                    </div>
                  </div>
                  <div className="flex gap-1">
                    <Button variant="ghost" size="sm" onClick={() => handleEdit(milestone)}>
                      <Edit2 className="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => handleDelete(milestone.id)}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <MilestoneEditor
        open={editorOpen}
        onOpenChange={setEditorOpen}
        projectId={projectId}
        milestone={editingMilestone}
        onSave={handleEditorSave}
      />
    </>
  );
}

function StatusBadge({ status }: { status: string }) {
  const config: Record<
    string,
    {
      icon: React.ReactNode;
      label: string;
      variant: 'default' | 'secondary' | 'destructive' | 'outline';
    }
  > = {
    pending: {
      icon: <Clock className="h-3 w-3" />,
      label: '待开始',
      variant: 'secondary',
    },
    in_progress: {
      icon: <Clock className="h-3 w-3" />,
      label: '进行中',
      variant: 'default',
    },
    completed: {
      icon: <CheckCircle2 className="h-3 w-3" />,
      label: '已完成',
      variant: 'default',
    },
    blocked: {
      icon: <AlertCircle className="h-3 w-3" />,
      label: '阻塞',
      variant: 'destructive',
    },
  };

  const { icon, label, variant } = config[status] || config.pending;

  return (
    <Badge variant={variant}>
      <span className="flex items-center gap-1">
        {icon}
        {label}
      </span>
    </Badge>
  );
}
