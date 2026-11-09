/**
 * Task 4.1: 记忆库页首"如何使用"提示。
 *
 * 首次进入记忆库时展开，告诉用户四层记忆各是什么、右上角按钮做什么、
 * 以及来源追踪 / 质量可视化 / 批量清理三个能力的入口。用户点关闭后
 * 写 localStorage 标记，后续不再自动展示。
 */
import { ChevronDown, ChevronRight, X } from 'lucide-react';
import { useState } from 'react';

export const MEMORY_HINT_DISMISSED_KEY = 'sage:memory:hint-dismissed';

const MEMORY_LAYERS: Array<{ label: string; desc: string }> = [
  { label: '情景记忆', desc: '某次对话里发生过的具体事件，带来源会话可回溯。' },
  { label: '语义记忆', desc: '从多次对话中沉淀的稳定事实与知识。' },
  { label: '工作记忆', desc: '当前会话内的短期上下文，会话结束即淡出。' },
  { label: '会话摘要', desc: '为长对话生成的压缩摘要，方便回看要点。' },
];

const TOOLBAR_HINTS: Array<{ label: string; desc: string }> = [
  { label: '新建记忆', desc: '手动写入一条记忆，立即生效。' },
  { label: '导出', desc: '把全部记忆导出为 JSON 备份。' },
];

const FEATURE_HINTS: Array<{ label: string; desc: string }> = [
  { label: '来源追踪', desc: '每条记忆标注来自哪个会话与相对时间，可一键跳回。' },
  { label: '质量可视化', desc: '颜色条显示记忆质量分级，低质量条目一目了然。' },
  { label: '批量清理', desc: '一次选中多条低质量记忆统一删除。' },
];

function readDismissed(): boolean {
  try {
    return localStorage.getItem(MEMORY_HINT_DISMISSED_KEY) === '1';
  } catch {
    return false;
  }
}

export function MemoryUsageHint() {
  const [dismissed, setDismissed] = useState(readDismissed);
  const [expanded, setExpanded] = useState(true);

  if (dismissed) return null;

  const handleDismiss = () => {
    try {
      localStorage.setItem(MEMORY_HINT_DISMISSED_KEY, '1');
    } catch {
      // localStorage 不可用时本次仍隐藏，只是下次会再出现
    }
    setDismissed(true);
  };

  return (
    <div
      data-testid="memory-usage-hint"
      className="mb-4 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3"
    >
      <div className="flex items-start justify-between gap-3">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="flex items-center gap-1.5 text-sm font-medium text-text hover:text-primary transition-colors"
        >
          {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          如何使用记忆库
        </button>
        <button
          type="button"
          onClick={handleDismiss}
          aria-label="关闭提示"
          title="关闭后不再自动显示"
          className="text-text-tertiary hover:text-text transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {expanded && (
        <div className="mt-3 grid gap-4 text-xs text-text-secondary md:grid-cols-3">
          <section>
            <h4 className="mb-1.5 text-xs font-semibold text-text">四层记忆</h4>
            <ul className="space-y-1">
              {MEMORY_LAYERS.map((item) => (
                <li key={item.label}>
                  <span className="font-medium text-text">{item.label}</span>：{item.desc}
                </li>
              ))}
            </ul>
          </section>
          <section>
            <h4 className="mb-1.5 text-xs font-semibold text-text">页面操作</h4>
            <ul className="space-y-1">
              {TOOLBAR_HINTS.map((item) => (
                <li key={item.label}>
                  <span className="font-medium text-text">{item.label}</span>：{item.desc}
                </li>
              ))}
              <li>
                <span className="font-medium text-text">👍 / 👎</span>
                ：标记记忆是否准确，帮助后续质量评分。
              </li>
            </ul>
          </section>
          <section>
            <h4 className="mb-1.5 text-xs font-semibold text-text">新能力</h4>
            <ul className="space-y-1">
              {FEATURE_HINTS.map((item) => (
                <li key={item.label}>
                  <span className="font-medium text-text">{item.label}</span>：{item.desc}
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </div>
  );
}
