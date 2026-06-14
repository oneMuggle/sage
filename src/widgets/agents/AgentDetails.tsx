import type { AgentProfile } from '../../shared/api/api';

interface AgentDetailsProps {
  agent: AgentProfile;
}

export function AgentDetails({ agent }: AgentDetailsProps) {
  return (
    <div className="space-y-4">
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
