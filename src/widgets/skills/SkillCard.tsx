import React from 'react';

interface SkillCardProps {
  name: string;
  description: string;
  triggers: string[];
  enabled: boolean;
  usage_count: number;
  onToggle: (name: string, enabled: boolean) => void;
  // SKILL.md 适配层 (PR-8) 新增字段 — builtin 时不传
  source?: 'builtin' | 'skillmd';
  body?: string;
  version?: string;
  base_dir?: string;
}

const SkillCard: React.FC<SkillCardProps> = ({
  name,
  description,
  triggers,
  enabled,
  usage_count,
  onToggle,
  source = 'builtin',
  body,
  version,
  base_dir,
}) => {
  return (
    <div
      className={`bg-surface rounded-lg shadow-md p-4 border-2 transition-all ${
        enabled ? 'border-primary' : 'border-border opacity-75'
      }`}
    >
      <div className="flex items-start justify-between">
        <div className="flex-1">
          {/* 名称 + 来源 badge */}
          <div className="flex items-center gap-2">
            <h3 className="text-lg font-semibold text-text">{name}</h3>
            <span
              className={`px-2 py-0.5 text-xs rounded-full ${
                source === 'skillmd'
                  ? 'bg-accent text-text-inverse'
                  : 'bg-bg-subtle text-text-secondary'
              }`}
            >
              {source}
            </span>
            {version && (
              <span className="px-2 py-0.5 text-xs rounded-full bg-bg-subtle text-text-secondary">
                v{version}
              </span>
            )}
          </div>
          <p className="text-sm text-text-secondary mt-1">{description}</p>

          {/* 触发词 */}
          <div className="flex flex-wrap gap-1 mt-2">
            {triggers.map((trigger, index) => (
              <span
                key={index}
                className="px-2 py-0.5 bg-bg-subtle text-text-secondary text-xs rounded-full"
              >
                {trigger}
              </span>
            ))}
          </div>

          {/* 使用统计 */}
          <p className="text-xs text-muted mt-2">已使用 {usage_count} 次</p>

          {/* SKILL.md body 折叠区 (仅 SKILL.md 显示) */}
          {source === 'skillmd' && body && (
            <details className="mt-3 border-t border-border pt-2">
              <summary className="text-xs text-text-secondary cursor-pointer hover:text-text">
                查看提示词模板
              </summary>
              <pre className="mt-2 p-2 bg-bg-subtle rounded text-xs whitespace-pre-wrap text-text-secondary max-h-64 overflow-auto">
                {body}
              </pre>
              {base_dir && (
                <p className="text-xs text-muted mt-1 truncate" title={base_dir}>
                  路径: {base_dir}
                </p>
              )}
            </details>
          )}
        </div>

        {/* 开关 */}
        <label className="relative inline-flex items-center cursor-pointer ml-4">
          <input
            type="checkbox"
            className="sr-only peer"
            checked={enabled}
            onChange={(e) => onToggle(name, e.target.checked)}
          />
          <div
            className="w-11 h-6 bg-bg-subtle peer-focus:outline-none peer-focus:ring-4
                       peer-focus:ring-primary/30 rounded-full peer
                       peer-checked:after:translate-x-full peer-checked:after:border-text-inverse
                       after:content-[''] after:absolute after:top-[2px] after:left-[2px]
                       after:bg-text-inverse after:border-border after:border after:rounded-full
                       after:h-5 after:w-5 after:transition-all
                       peer-checked:bg-primary"
          ></div>
        </label>
      </div>
    </div>
  );
};

export default SkillCard;
