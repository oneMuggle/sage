/**
 * EvolutionPanel - 进化状态面板
 * 显示进化系统状态、任务调度信息和手动触发按钮
 */
import { invoke } from '@tauri-apps/api/core';
import React, { useEffect, useState } from 'react';

// 任务状态类型
interface TaskStatus {
  name: string;
  schedule: string;
  last_run: string | null;
  next_run: string | null;
  running: boolean;
}

// 任务配置
const TASK_CONFIG = {
  daily_summary: { name: '每日摘要', description: '生成每日对话摘要' },
  memory_pruning: { name: '记忆修剪', description: '清理低价值记忆' },
  preference_learning: { name: '偏好学习', description: '从反馈中学习用户偏好' },
  importance_reevaluation: { name: '重要性重评估', description: '重评估记忆重要性' },
};

export const EvolutionPanel: React.FC = () => {
  const [tasks, setTasks] = useState<TaskStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState<string | null>(null);

  // 获取进化状态
  const fetchStatus = async () => {
    try {
      const status = await invoke<TaskStatus[]>('get_evolution_status');
      setTasks(status);
    } catch (error) {
      console.error('获取进化状态失败:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
    // 每分钟刷新一次
    const interval = setInterval(fetchStatus, 60000);
    return () => clearInterval(interval);
  }, []);

  // 手动触发任务
  const handleTrigger = async (taskName: string) => {
    setTriggering(taskName);
    try {
      await invoke('trigger_evolution', { taskName });
      // 刷新状态
      await fetchStatus();
    } catch (error) {
      console.error('触发任务失败:', error);
    } finally {
      setTriggering(null);
    }
  };

  // 格式化时间
  const formatTime = (timeStr: string | null): string => {
    if (!timeStr) return '从未';
    try {
      const date = new Date(timeStr);
      return date.toLocaleString('zh-CN');
    } catch {
      return timeStr;
    }
  };

  // 获取调度时间描述
  const getScheduleText = (schedule: string): string => {
    if (schedule === 'daily') return '每天';
    if (schedule === 'weekly') return '每周';
    if (schedule === 'hourly') return '每小时';
    return schedule;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="text-muted">加载中...</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* 标题和状态 */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-text">进化系统</h2>
          <p className="text-sm text-muted mt-1">
            调度器状态: {tasks.some((t) => t.running) ? '运行中' : '已停止'}
          </p>
        </div>
      </div>

      {/* 任务列表 */}
      <div className="space-y-4">
        {tasks.map((task) => {
          const config = TASK_CONFIG[task.name as keyof typeof TASK_CONFIG];
          return (
            <div key={task.name} className="bg-surface rounded-lg shadow p-4 border border-border">
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <h3 className="font-medium text-text">{config?.name || task.name}</h3>
                    <span className="text-xs px-2 py-0.5 bg-bg-subtle text-text-secondary rounded">
                      {getScheduleText(task.schedule)}
                    </span>
                  </div>
                  <p className="text-sm text-muted mt-1">{config?.description || ''}</p>

                  {/* 时间信息 */}
                  <div className="mt-3 grid grid-cols-2 gap-4 text-xs">
                    <div>
                      <span className="text-muted">上次执行:</span>
                      <span className="ml-1 text-text-secondary">{formatTime(task.last_run)}</span>
                    </div>
                    <div>
                      <span className="text-muted">下次执行:</span>
                      <span className="ml-1 text-text-secondary">{formatTime(task.next_run)}</span>
                    </div>
                  </div>
                </div>

                {/* 手动触发按钮 */}
                <button
                  onClick={() => handleTrigger(task.name)}
                  disabled={triggering === task.name}
                  className={`ml-4 px-3 py-1.5 text-sm rounded transition-colors ${
                    triggering === task.name
                      ? 'bg-bg-subtle text-muted cursor-not-allowed'
                      : 'bg-primary/10 text-primary hover:bg-primary/20'
                  }`}
                >
                  {triggering === task.name ? '触发中...' : '立即执行'}
                </button>
              </div>
            </div>
          );
        })}

        {tasks.length === 0 && <div className="text-center py-8 text-muted">暂无进化任务</div>}
      </div>
    </div>
  );
};

export default EvolutionPanel;
