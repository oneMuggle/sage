import { useState } from 'react';

import type { AgentProfile } from '../../shared/api';

interface AgentDetailsProps {
  agent: AgentProfile;
}

export function AgentDetails({ agent }: AgentDetailsProps) {
  const [copiedMd, setCopiedMd] = useState(false);
  const [copiedJson, setCopiedJson] = useState(false);

  /* v8 ignore start */
  const handleCopyMd = async () => {
    const lines = [
      `# Agent 配置 · ${agent.name}`,
      '',
      `- ID: \`${agent.id}\``,
      `- 角色: \`${agent.role}\``,
      `- 模型: \`${agent.model_config.model}\` (Temperature: ${agent.model_config.temperature}, Max Tokens: ${agent.model_config.max_tokens})`,
      `- 最大迭代次数: ${agent.max_iterations}`,
      `- 工具: ${agent.tools.join(', ') || '无'}`,
      `- 记忆访问: ${agent.memory_access.join(', ') || '无'}`,
      '',
      '## 系统提示',
      '```',
      agent.system_prompt,
      '```',
    ];
    setCopiedMd(true);
    try {
      await navigator.clipboard?.writeText(lines.join('\n'));
    } catch {
      // ignore clipboard errors
    }
    setTimeout(() => setCopiedMd(false), 1500);
  };

  const handleCopyJson = async () => {
    setCopiedJson(true);
    try {
      await navigator.clipboard?.writeText(JSON.stringify(agent, null, 2));
    } catch {
      // ignore clipboard errors
    }
    setTimeout(() => setCopiedJson(false), 1500);
  };
  /* v8 ignore stop */

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          data-testid="agent-details-copy-md-btn"
          onClick={handleCopyMd}
          className="px-2 py-1 text-xs rounded border border-border bg-surface hover:bg-bg-subtle text-text-secondary transition-colors"
        >
          {copiedMd ? '✓ 已复制MD' : '复制配置MD'}
        </button>
        <button
          type="button"
          data-testid="agent-details-copy-json-btn"
          onClick={handleCopyJson}
          className="px-2 py-1 text-xs rounded border border-border bg-surface hover:bg-bg-subtle text-text-secondary transition-colors"
        >
          {copiedJson ? '✓ 已复制JSON' : '复制配置JSON'}
        </button>
      </div>

      <div>
        <span className="text-sm font-medium text-muted">ID</span>
        <p className="text-sm font-mono mt-1">{agent.id}</p>
      </div>

      <div>
        <span className="text-sm font-medium text-muted">系统提示</span>
        <pre className="text-sm mt-1 p-3 rounded bg-bg-subtle dark:bg-bg-muted whitespace-pre-wrap">
          {agent.system_prompt}
        </pre>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <span className="text-sm font-medium text-muted">工具</span>
          <div className="flex flex-wrap gap-1 mt-1">
            {agent.tools.map((tool) => (
              <span key={tool} className="px-2 py-0.5 text-xs rounded bg-bg-subtle">
                {tool}
              </span>
            ))}
          </div>
        </div>

        <div>
          <span className="text-sm font-medium text-muted">记忆访问</span>
          <div className="flex flex-wrap gap-1 mt-1">
            {agent.memory_access.map((mem) => (
              <span key={mem} className="px-2 py-0.5 text-xs rounded bg-bg-subtle">
                {mem}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div>
          <span className="text-sm font-medium text-muted">模型</span>
          <p className="text-sm mt-1">{agent.model_config.model}</p>
        </div>
        <div>
          <span className="text-sm font-medium text-muted">Temperature</span>
          <p className="text-sm mt-1">{agent.model_config.temperature}</p>
        </div>
        <div>
          <span className="text-sm font-medium text-muted">Max Tokens</span>
          <p className="text-sm mt-1">{agent.model_config.max_tokens}</p>
        </div>
      </div>

      <div>
        <span className="text-sm font-medium text-muted">最大迭代次数</span>
        <p className="text-sm mt-1">{agent.max_iterations}</p>
      </div>
    </div>
  );
}
