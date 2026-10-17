/**
 * 自主目标列表页
 *
 * 展示所有目标（GoalCard 列表）+ 状态过滤 + 创建按钮。
 * 点击卡片导航到目标详情页。
 */
import { Plus, Loader2 } from 'lucide-react';
import { useEffect, useState } from 'react';

import { useGoalStore } from '../../entities/autonomous-goals/goalStore';
import type { GoalStatus } from '../../entities/autonomous-goals/types';
import { PageHeader } from '../../shared/ui';
import { Button } from '../../shared/ui/Button';
import { GoalCard } from '../../widgets/autonomous-goals/GoalCard';

import { CreateGoalModal } from './CreateGoalModal';

const STATUS_OPTIONS: { value: GoalStatus | null; label: string }[] = [
  { value: null, label: '全部' },
  { value: 'pending', label: '等待中' },
  { value: 'running', label: '运行中' },
  { value: 'paused', label: '已暂停' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
];

export function GoalListPage() {
  const goals = useGoalStore((s) => s.goals);
  const total = useGoalStore((s) => s.total);
  const loading = useGoalStore((s) => s.loading);
  const error = useGoalStore((s) => s.error);
  const load = useGoalStore((s) => s.load);
  const statusFilter = useGoalStore((s) => s.statusFilter);
  const setStatusFilter = useGoalStore((s) => s.setStatusFilter);
  const clearError = useGoalStore((s) => s.clearError);

  const [showCreate, setShowCreate] = useState(false);

  useEffect(() => {
    void load();
  }, [load]);

  const handleFilterChange = (status: GoalStatus | null) => {
    setStatusFilter(status);
    void load(status ?? undefined);
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <PageHeader
        title="自主目标"
        actions={
          <Button variant="primary" size="sm" onClick={() => setShowCreate(true)}>
            <Plus className="w-4 h-4 mr-1" />
            新建目标
          </Button>
        }
      />

      <div className="flex-1 overflow-y-auto p-6 max-w-4xl mx-auto w-full">
        {/* Status filter tabs */}
        <div className="flex items-center gap-1 mb-4 overflow-x-auto">
          {STATUS_OPTIONS.map((opt) => (
            <button
              key={opt.label}
              onClick={() => handleFilterChange(opt.value)}
              className={[
                'px-3 py-1.5 text-sm rounded-full whitespace-nowrap transition-colors',
                statusFilter === opt.value
                  ? 'bg-primary text-text-inverse'
                  : 'text-text-muted hover:bg-bg-hover',
              ].join(' ')}
            >
              {opt.label}
            </button>
          ))}
          <span className="ml-auto text-ui-xs text-text-muted">共 {total} 个目标</span>
        </div>

        {/* Error */}
        {error && (
          <div
            className="mb-4 px-3 py-2 bg-destructive/10 text-destructive text-sm rounded flex items-center justify-between"
            role="alert"
          >
            <span>{error}</span>
            <button onClick={clearError} className="text-ui-xs underline hover:no-underline">
              关闭
            </button>
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div
            className="flex items-center gap-2 text-text-muted text-sm py-8 justify-center"
            role="status"
          >
            <Loader2 className="w-4 h-4 animate-spin" />
            加载中...
          </div>
        )}

        {/* Empty state */}
        {!loading && goals.length === 0 && (
          <div className="text-center py-16">
            <p className="text-text-muted mb-4">
              {statusFilter ? '没有匹配的目标' : '还没有创建自主目标'}
            </p>
            <Button variant="primary" onClick={() => setShowCreate(true)}>
              <Plus className="w-4 h-4 mr-1" />
              创建第一个目标
            </Button>
          </div>
        )}

        {/* Goal list */}
        {!loading && goals.length > 0 && (
          <div className="grid gap-3">
            {goals.map((goal) => (
              <GoalCard key={goal.id} goal={goal} />
            ))}
          </div>
        )}
      </div>

      {/* Create modal */}
      <CreateGoalModal isOpen={showCreate} onClose={() => setShowCreate(false)} />
    </div>
  );
}
