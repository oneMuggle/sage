/**
 * EvolutionLog - 进化日志列表
 * 显示进化任务的执行历史记录
 */
import React, { useEffect, useState } from 'react';
import { invoke } from '@tauri-apps/api/tauri';

// 进化日志类型
interface EvolutionLog {
  id: string;
  evolution_type: string;
  description: string;
  before_state: string | null;
  after_state: string | null;
  trigger_type: string;
  trigger_condition: string | null;
  status: string;
  error_message: string | null;
  tokens_used: number | null;
  created_at: number;
  completed_at: number | null;
}

// 日志类型配置
const LOG_TYPE_CONFIG: Record<string, { name: string; color: string }> = {
  daily_summary: { name: '每日摘要', color: 'bg-blue-100 text-blue-700' },
  memory_pruning: { name: '记忆修剪', color: 'bg-green-100 text-green-700' },
  preference_learning: { name: '偏好学习', color: 'bg-purple-100 text-purple-700' },
  importance_reevaluation: { name: '重要性重评估', color: 'bg-orange-100 text-orange-700' },
};

export const EvolutionLog: React.FC = () => {
  const [logs, setLogs] = useState<EvolutionLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(0);
  const pageSize = 20;

  // 获取进化日志
  const fetchLogs = async (offset: number = 0) => {
    try {
      const result = await invoke<EvolutionLog[]>('get_evolution_logs', {
        limit: pageSize,
        offset: offset,
      });
      if (offset === 0) {
        setLogs(result);
      } else {
        setLogs(prev => [...prev, ...result]);
      }
    } catch (error) {
      console.error('获取进化日志失败:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs(page * pageSize);
  }, [page]);

  // 加载更多
  const handleLoadMore = () => {
    setPage(prev => prev + 1);
  };

  // 格式化时间戳
  const formatTime = (timestamp: number): string => {
    try {
      const date = new Date(timestamp * 1000);
      return date.toLocaleString('zh-CN');
    } catch {
      return String(timestamp);
    }
  };

  // 获取状态显示
  const getStatusDisplay = (status: string) => {
    switch (status) {
      case 'success':
        return { text: '成功', className: 'text-green-600 bg-green-50' };
      case 'failed':
        return { text: '失败', className: 'text-red-600 bg-red-50' };
      case 'pending':
        return { text: '等待中', className: 'text-yellow-600 bg-yellow-50' };
      case 'running':
        return { text: '执行中', className: 'text-blue-600 bg-blue-50' };
      default:
        return { text: status, className: 'text-gray-600 bg-gray-50' };
    }
  };

  // 获取触发类型显示
  const getTriggerTypeDisplay = (triggerType: string) => {
    switch (triggerType) {
      case 'scheduled':
        return '定时';
      case 'manual':
        return '手动';
      case 'threshold':
        return '阈值触发';
      default:
        return triggerType;
    }
  };

  if (loading && logs.length === 0) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="text-gray-500">加载中...</div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium text-gray-900">进化日志</h3>
        <button
          onClick={() => {
            setPage(0);
            fetchLogs(0);
          }}
          className="text-sm text-blue-600 hover:text-blue-800"
        >
          刷新
        </button>
      </div>

      {/* 日志列表 */}
      <div className="space-y-3">
        {logs.map((log) => {
          const typeConfig = LOG_TYPE_CONFIG[log.evolution_type] || {
            name: log.evolution_type,
            color: 'bg-gray-100 text-gray-700',
          };
          const statusDisplay = getStatusDisplay(log.status);

          return (
            <div
              key={log.id}
              className="bg-white rounded-lg shadow-sm p-4 border border-gray-200"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    {/* 类型标签 */}
                    <span className={`text-xs px-2 py-0.5 rounded ${typeConfig.color}`}>
                      {typeConfig.name}
                    </span>
                    {/* 触发类型 */}
                    <span className="text-xs px-2 py-0.5 bg-gray-100 text-gray-600 rounded">
                      {getTriggerTypeDisplay(log.trigger_type)}
                    </span>
                    {/* 状态标签 */}
                    <span className={`text-xs px-2 py-0.5 rounded ${statusDisplay.className}`}>
                      {statusDisplay.text}
                    </span>
                  </div>

                  {/* 描述 */}
                  <p className="text-sm text-gray-700 mt-2">{log.description}</p>

                  {/* 错误信息 */}
                  {log.error_message && (
                    <p className="text-sm text-red-600 mt-1">
                      错误: {log.error_message}
                    </p>
                  )}

                  {/* 时间信息 */}
                  <div className="mt-2 flex items-center gap-4 text-xs text-gray-400">
                    <span>创建: {formatTime(log.created_at)}</span>
                    {log.completed_at && (
                      <span>完成: {formatTime(log.completed_at)}</span>
                    )}
                    {log.tokens_used && (
                      <span>消耗 Token: {log.tokens_used}</span>
                    )}
                  </div>

                  {/* 状态变化 */}
                  {(log.before_state || log.after_state) && (
                    <div className="mt-2 text-xs text-gray-500">
                      {log.before_state && (
                        <div className="line-through opacity-50">
                          前: {log.before_state}
                        </div>
                      )}
                      {log.after_state && (
                        <div className="text-green-600">
                          后: {log.after_state}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          );
        })}

        {logs.length === 0 && (
          <div className="text-center py-8 text-gray-500">
            暂无进化日志
          </div>
        )}
      </div>

      {/* 加载更多 */}
      {logs.length >= pageSize && (
        <div className="text-center">
          <button
            onClick={handleLoadMore}
            disabled={loading}
            className="px-4 py-2 text-sm text-blue-600 hover:text-blue-800 disabled:opacity-50"
          >
            {loading ? '加载中...' : '加载更多'}
          </button>
        </div>
      )}
    </div>
  );
};

export default EvolutionLog;
