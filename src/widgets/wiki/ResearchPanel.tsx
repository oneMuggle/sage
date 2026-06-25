// Research Panel - 深度研究面板
import { Globe, Loader2, Save, Send, Trash2 } from 'lucide-react';
import { useState } from 'react';

import { mockResearchTasks } from '../../entities/wiki/mock-data';
import { useResearchStore } from '../../entities/wiki/research-store';

import { MarkdownPreview } from './MarkdownPreview';

export function ResearchPanel() {
  const tasks = useResearchStore((s) => s.tasks);
  const setTasks = useResearchStore((s) => s.setTasks);
  const addTask = useResearchStore((s) => s.addTask);
  const removeTask = useResearchStore((s) => s.removeTask);
  const [input, setInput] = useState('');

  // 初始化模拟数据
  const handleLoadMockData = () => {
    setTasks(mockResearchTasks);
  };

  // 模拟开始研究
  const handleStartResearch = () => {
    if (!input.trim()) return;

    const newTask = {
      id: `research-${Date.now()}`,
      topic: input.trim(),
      status: 'searching' as const,
      webResults: [],
      synthesis: '',
    };

    addTask(newTask);
    setInput('');
  };

  // 模拟保存
  const handleSave = (taskId: string) => {
    alert(`模拟保存研究结果到 Wiki: ${taskId}`);
  };

  // 模拟删除
  const handleRemove = (taskId: string) => {
    if (confirm('确定删除此研究任务?')) {
      removeTask(taskId);
    }
  };

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b border-border px-3 py-2 bg-surface">
        <div className="flex items-center gap-2 mb-2">
          <Globe className="h-3.5 w-3.5 text-primary" />
          <span className="text-xs font-semibold text-text uppercase tracking-wide">深度研究</span>
        </div>
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleStartResearch();
              }
            }}
            placeholder="输入研究主题..."
            className="flex-1 rounded-md border border-border bg-bg-muted px-2 py-1.5 text-xs placeholder:text-muted focus:outline-none focus:ring-2 focus:ring-primary/20 text-text"
          />
          <button
            onClick={handleStartResearch}
            disabled={!input.trim()}
            className="px-2 py-1.5 bg-primary text-text-inverse rounded-md hover:bg-primary-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Send className="h-3 w-3" />
          </button>
        </div>
        {tasks.length === 0 && (
          <button
            onClick={handleLoadMockData}
            className="mt-2 text-xs text-primary hover:text-primary-hover"
          >
            加载示例研究
          </button>
        )}
      </div>

      {/* Tasks list */}
      <div className="flex-1 overflow-y-auto">
        {tasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-muted p-4">
            <Globe className="h-8 w-8 mb-2 opacity-30" />
            <p className="text-xs">输入研究主题开始</p>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {tasks.map((task) => (
              <div key={task.id} className="p-3">
                {/* Task header */}
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-text truncate">{task.topic}</span>
                      {task.status === 'searching' || task.status === 'synthesizing' ? (
                        <Loader2 className="h-3 w-3 text-blue-500 animate-spin flex-shrink-0" />
                      ) : task.status === 'done' ? (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-500/10 text-green-500">
                          完成
                        </span>
                      ) : task.status === 'error' ? (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/10 text-red-500">
                          失败
                        </span>
                      ) : (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-yellow-500/10 text-yellow-500">
                          队列中
                        </span>
                      )}
                    </div>
                    {task.savedPath && (
                      <p className="text-xs text-primary mt-1 truncate">已保存: {task.savedPath}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-1 flex-shrink-0">
                    {task.status === 'done' && !task.savedPath && (
                      <button
                        onClick={() => handleSave(task.id)}
                        className="p-1 text-muted hover:text-primary transition-colors"
                        title="保存到 Wiki"
                      >
                        <Save className="h-3.5 w-3.5" />
                      </button>
                    )}
                    <button
                      onClick={() => handleRemove(task.id)}
                      className="p-1 text-muted hover:text-red-500 transition-colors"
                      title="删除"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>

                {/* Web results */}
                {task.webResults.length > 0 && (
                  <div className="mb-2">
                    <p className="text-[10px] text-muted uppercase tracking-wide mb-1">
                      来源 ({task.webResults.length})
                    </p>
                    <div className="space-y-1">
                      {task.webResults.map((result, i) => (
                        <a
                          key={i}
                          href={result.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="block text-xs text-primary hover:underline truncate"
                        >
                          {result.title}
                        </a>
                      ))}
                    </div>
                  </div>
                )}

                {/* Synthesis */}
                {task.synthesis && (
                  <div className="mt-2 p-2 rounded bg-bg-muted max-h-40 overflow-y-auto">
                    <MarkdownPreview content={task.synthesis} />
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
