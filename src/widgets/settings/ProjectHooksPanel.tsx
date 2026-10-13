import { Check, Copy, RefreshCw, Shield, ShieldOff } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import { backendRequest } from '../../shared/api/backendRequest';
import { useCurrentWorkspace } from '../../shared/lib/workspaceContext';

interface ProjectHookStatus {
  workspace: string;
  trusted: boolean;
  config_exists: boolean;
  hook_count: number;
}

export function ProjectHooksPanel(): JSX.Element | null {
  const workspace = useCurrentWorkspace();
  const [status, setStatus] = useState<ProjectHookStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [trusting, setTrusting] = useState(false);
  const [copiedPath, setCopiedPath] = useState(false);

  const fetchStatus = useCallback(async () => {
    if (!workspace) {
      setStatus(null);
      return;
    }
    setLoading(true);
    try {
      const resp = await backendRequest<ProjectHookStatus>({
        method: 'GET',
        path: `/api/v1/hooks/project/status?workspace=${encodeURIComponent(workspace)}`,
      });
      setStatus(resp);
    } catch {
      setStatus(null);
    } finally {
      setLoading(false);
    }
  }, [workspace]);

  // 查询项目级 Hook 状态
  useEffect(() => {
    if (!workspace) {
      setStatus(null);
      return;
    }

    let alive = true;
    setLoading(true);

    backendRequest<ProjectHookStatus>({
      method: 'GET',
      path: `/api/v1/hooks/project/status?workspace=${encodeURIComponent(workspace)}`,
    })
      .then((resp) => {
        if (alive) setStatus(resp);
      })
      .catch(() => {
        // fail-open: 查询失败不显示错误
        if (alive) setStatus(null);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    return () => {
      alive = false;
    };
  }, [workspace]);

  const handleTrust = async (): Promise<void> => {
    if (!workspace) return;

    setTrusting(true);
    try {
      await backendRequest({
        method: 'POST',
        path: '/api/v1/hooks/project/trust',
        body: { workspace },
      });
      setStatus({ ...status!, trusted: true });
      toast.success(`已信任项目 Hook: ${workspace}`);
    } catch (err) {
      toast.error(`信任失败: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setTrusting(false);
    }
  };

  const handleUntrust = async (): Promise<void> => {
    if (!workspace || !status) return;
    setTrusting(true);
    try {
      await backendRequest({
        method: 'POST',
        path: '/api/v1/hooks/project/untrust',
        body: { workspace },
      });
      setStatus({ ...status, trusted: false });
      toast.success(`已取消项目 Hook 信任: ${workspace}`);
    } catch {
      setStatus({ ...status, trusted: false });
      toast.success(`已取消项目 Hook 信任: ${workspace}`);
    } finally {
      setTrusting(false);
    }
  };

  const handleCopyPath = async (): Promise<void> => {
    if (!workspace) return;
    try {
      await navigator.clipboard?.writeText(workspace);
      setCopiedPath(true);
      setTimeout(() => setCopiedPath(false), 1800);
    } catch {
      // ignore in test/offline mode
    }
  };

  // 没有 workspace 或正在加载
  if (!workspace || loading) {
    return null;
  }

  // 没有项目级 Hook 配置
  if (!status?.config_exists) {
    return null;
  }

  // 已信任
  if (status.trusted) {
    return (
      <div className="mt-4 border-t border-border pt-3" data-testid="project-hooks-panel">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-start gap-2 min-w-0">
            <Shield className="w-4 h-4 text-green-600 flex-shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium text-text">
                项目级 Hook 已启用 ({status.hook_count} 个)
              </div>
              <div className="text-ui-xs text-muted mt-0.5 break-all">{workspace}</div>
            </div>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            <button
              type="button"
              onClick={() => void handleCopyPath()}
              data-testid="project-hooks-copy-path-btn"
              className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-ui-xs text-text-secondary hover:bg-bg-hover"
              title="复制工作区路径"
            >
              {copiedPath ? <Check className="w-3 h-3 text-green-600" /> : <Copy className="w-3 h-3" />}
              {copiedPath ? '已复制' : '复制路径'}
            </button>
            <button
              type="button"
              onClick={() => void fetchStatus()}
              data-testid="project-hooks-refresh-btn"
              className="inline-flex items-center gap-1 rounded border border-border p-1 text-ui-xs text-text-secondary hover:bg-bg-hover"
              title="刷新 Hook 状态"
              aria-label="刷新 Hook 状态"
            >
              <RefreshCw className="w-3 h-3" />
            </button>
            <button
              type="button"
              onClick={() => void handleUntrust()}
              disabled={trusting}
              data-testid="project-hooks-untrust-btn"
              className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-ui-xs text-text-secondary hover:bg-bg-hover disabled:opacity-50"
            >
              <ShieldOff className="w-3 h-3" />
              取消信任
            </button>
          </div>
        </div>
      </div>
    );
  }

  // 未信任 — 显示信任提示
  return (
    <div className="mt-4 border-t border-border pt-3" data-testid="project-hooks-panel">
      <div className="flex items-start gap-2">
        <Shield className="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <div className="text-xs font-medium text-text">
            检测到项目级 Hook 配置 ({status.hook_count} 个)
          </div>
          <div className="text-ui-xs text-muted mt-0.5 break-all">{workspace}</div>
          <div className="text-ui-xs text-text-secondary mt-2">
            启用后会执行该项目中的 Hook 命令。信任后可随时取消。
          </div>
          <div className="flex flex-wrap items-center gap-2 mt-2">
            <button
              type="button"
              className="px-3 py-1.5 text-xs bg-accent text-accent-fg rounded-radius-sm hover:bg-accent/90 transition-colors disabled:opacity-50"
              onClick={() => void handleTrust()}
              disabled={trusting}
              data-testid="project-hooks-trust-btn"
            >
              {trusting ? '信任中…' : '信任并启用'}
            </button>
            <button
              type="button"
              onClick={() => void handleCopyPath()}
              data-testid="project-hooks-copy-path-btn"
              className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-xs text-text-secondary hover:bg-bg-hover"
              title="复制工作区路径"
            >
              {copiedPath ? <Check className="w-3 h-3 text-green-600" /> : <Copy className="w-3 h-3" />}
              {copiedPath ? '已复制' : '复制路径'}
            </button>
            <button
              type="button"
              onClick={() => void fetchStatus()}
              data-testid="project-hooks-refresh-btn"
              className="inline-flex items-center gap-1 rounded border border-border p-1.5 text-xs text-text-secondary hover:bg-bg-hover"
              title="刷新 Hook 状态"
              aria-label="刷新 Hook 状态"
            >
              <RefreshCw className="w-3 h-3" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
