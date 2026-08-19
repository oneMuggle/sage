/**
 * EvolutionPanel - 进化系统面板 (PR-C §5.1 后)
 *
 * §5.1 把 5 个 evolution 任务接到 lifespan 自动 cron 后,不再需要手动
 * 触发 / 实时状态面板。本组件只展示:后台接管说明 + 最近 N 条 logs
 * (复用 get_evolution_logs)。
 */
import React, { useEffect, useState } from 'react';

import { invoke } from '../../shared/api/desktopInvoke';

interface EvolutionLog {
  id: string;
  evolution_type: string;
  description: string;
  status: string;
  created_at: number;
  completed_at?: number | null;
}

const TASK_DISPLAY: Record<string, string> = {
  daily_summary: '每日摘要',
  memory_pruning: '记忆修剪',
  preference_learning: '偏好学习',
  importance_reevaluation: '重要性重评估',
  memory_consolidation: '记忆合并',
};

export const EvolutionPanel: React.FC = () => {
  const [logs, setLogs] = useState<EvolutionLog[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchLogs = async () => {
    try {
      const result = await invoke<EvolutionLog[]>('get_evolution_logs', {
        limit: 10,
        offset: 0,
      });
      setLogs(result);
    } catch (error) {
      console.error('获取进化日志失败:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
    const interval = setInterval(fetchLogs, 60_000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="text-muted">加载中...</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-text">进化系统</h2>
        <p className="text-sm text-muted mt-1">
          已由后台自动调度(SchedulerService cron 触发),无需手动操作。
          5 个任务:每日摘要 / 记忆修剪 / 偏好学习 / 重要性重评估 / 记忆合并。
        </p>
      </div>

      <div>
        <h3 className="text-sm font-medium text-text-secondary mb-3">最近执行记录</h3>
        {logs.length === 0 ? (
          <div className="text-center py-8 text-muted">暂无进化日志</div>
        ) : (
          <ul className="space-y-2">
            {logs.map((log) => (
              <li
                key={log.id}
                className="bg-surface rounded-lg shadow p-3 border border-border text-sm"
              >
                <div className="flex justify-between">
                  <span className="font-medium text-text">
                    {TASK_DISPLAY[log.evolution_type] || log.evolution_type}
                  </span>
                  <span
                    className={
                      log.status === 'completed'
                        ? 'text-success'
                        : log.status === 'failed'
                          ? 'text-danger'
                          : 'text-muted'
                    }
                  >
                    {log.status}
                  </span>
                </div>
                <p className="text-xs text-muted mt-1">{log.description}</p>
                <p className="text-xs text-muted mt-1">
                  {new Date(log.created_at).toLocaleString('zh-CN')}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
};

export default EvolutionPanel;