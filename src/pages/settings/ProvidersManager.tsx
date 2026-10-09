/**
 * ProvidersManager — Settings UI for pluggable update providers.
 *
 * UI-P0-4 (2026-10-09):
 *   - Replaced 9 sequential window.prompt() calls with a controlled <Dialog> form
 *     (including <input type="password"> for access tokens).
 *   - Replaced 4 window.alert() calls with non-blocking sonner toast notifications.
 *   - Styled table and controls with semantic theme tokens.
 */
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import type { ProviderConfigSummary } from '../../shared/types/electron-api';
import { confirmDialog } from '../../shared/ui/ConfirmDialog/confirmService';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../shared/ui/Dialog/Dialog';

export function ProvidersManager(): JSX.Element {
  const [list, setList] = useState<ProviderConfigSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  // Controlled Add Provider modal state
  const [addOpen, setAddOpen] = useState(false);
  const [providerType, setProviderType] = useState<ProviderConfigSummary['type']>('github');
  const [displayName, setDisplayName] = useState('');
  const [owner, setOwner] = useState('');
  const [repo, setRepo] = useState('');
  const [token, setToken] = useState('');
  const [baseUrl, setBaseUrl] = useState('https://gitlab.com');
  const [projectId, setProjectId] = useState('');
  const [manifestUrl, setManifestUrl] = useState('');
  const [publicKey, setPublicKey] = useState('');

  const resetAddForm = () => {
    setProviderType('github');
    setDisplayName('');
    setOwner('');
    setRepo('');
    setToken('');
    setBaseUrl('https://gitlab.com');
    setProjectId('');
    setManifestUrl('');
    setPublicKey('');
  };

  const refresh = async (): Promise<void> => {
    const l = await window.electronAPI?.providers.list();
    setList(l ?? []);
    setLoading(false);
  };

  useEffect(() => {
    void refresh();
  }, []);

  if (loading) {
    return (
      <div data-testid="providers-loading" className="text-sm text-text-secondary py-4">
        加载中...
      </div>
    );
  }

  const onSetDefault = async (id: string): Promise<void> => {
    setBusyId(id);
    try {
      await window.electronAPI?.providers.setDefault(id);
      await refresh();
    } finally {
      setBusyId(null);
    }
  };

  const onTest = async (id: string): Promise<void> => {
    setBusyId(id);
    try {
      const r = await window.electronAPI?.providers.test(id);
      if (r?.ok) {
        toast.success(`连接 OK（${r.latencyMs}ms）`);
      } else {
        toast.error(`失败：${r?.error ?? 'unknown'}`);
      }
    } finally {
      setBusyId(null);
    }
  };

  const onRemove = async (id: string): Promise<void> => {
    const ok = await confirmDialog({ title: '确定删除？', danger: true });
    if (!ok) return;
    setBusyId(id);
    try {
      await window.electronAPI?.providers.remove(id);
      await refresh();
      toast.success('已删除更新源');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`删除失败：${msg}`);
    } finally {
      setBusyId(null);
    }
  };

  const handleSubmitAdd = async (): Promise<void> => {
    const config: Record<string, unknown> = {
      channelMap: { stable: true, beta: true, alpha: true },
      requireArtifactSignature: false,
    };
    if (providerType === 'github' || providerType === 'gitee') {
      config.owner = owner.trim();
      config.repo = repo.trim();
      if (token.trim()) config.token = token.trim();
    } else if (providerType === 'gitlab') {
      config.baseUrl = baseUrl.trim();
      config.projectId = projectId.trim();
      if (token.trim()) config.token = token.trim();
    } else if (providerType === 'generic-http') {
      config.manifestUrl = manifestUrl.trim();
      config.publicKey = publicKey.trim();
      config.requireArtifactSignature = true;
    }

    setBusyId('__add__');
    try {
      await window.electronAPI?.providers.add({
        type: providerType,
        displayName: displayName.trim() || 'Untitled',
        enabled: true,
        isDefault: false,
        config,
      });
      await refresh();
      setAddOpen(false);
      resetAddForm();
      toast.success('已添加更新源');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`添加失败：${msg}`);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="providers-manager space-y-4" data-testid="providers-manager">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-text">更新源管理</h2>
          <p data-testid="providers-current-default" className="text-xs text-text-secondary mt-0.5">
            当前默认：
            {list.find((p) => p.isDefault)?.displayName ?? '（无，使用内置）'}
          </p>
        </div>
        <button
          type="button"
          data-testid="providers-add-button"
          onClick={() => {
            resetAddForm();
            setAddOpen(true);
          }}
          disabled={busyId !== null}
          className="px-3 py-1.5 text-xs font-medium rounded-radius-sm bg-primary text-text-inverse hover:bg-primary-hover disabled:opacity-50 transition-colors"
        >
          + 添加更新源
        </button>
      </div>

      <div className="border border-border rounded-radius-md overflow-hidden bg-surface">
        <table className="w-full text-xs text-left border-collapse">
          <thead className="bg-bg-subtle border-b border-border text-text-secondary">
            <tr>
              <th className="px-3 py-2 font-medium">名称</th>
              <th className="px-3 py-2 font-medium">类型</th>
              <th className="px-3 py-2 font-medium">状态</th>
              <th className="px-3 py-2 font-medium text-right">操作</th>
            </tr>
          </thead>
          <tbody data-testid="providers-list-body" className="divide-y divide-border">
            {list.map((p) => (
              <tr key={p.id} data-testid={`provider-row-${p.id}`} className="hover:bg-bg-hover/50">
                <td className="px-3 py-2 font-medium text-text">{p.displayName}</td>
                <td className="px-3 py-2 text-text-secondary font-mono">{p.type}</td>
                <td className="px-3 py-2">
                  <span
                    className={`inline-flex items-center px-1.5 py-0.5 rounded text-2xs font-medium ${
                      p.isDefault
                        ? 'bg-primary/15 text-primary'
                        : p.enabled
                          ? 'bg-success/15 text-success'
                          : 'bg-bg-subtle text-text-tertiary'
                    }`}
                  >
                    {p.isDefault ? '默认' : p.enabled ? '启用' : '禁用'}
                  </span>
                </td>
                <td className="px-3 py-2 text-right space-x-1.5">
                  {!p.isDefault && (
                    <button
                      type="button"
                      data-testid={`provider-set-default-${p.id}`}
                      onClick={() => void onSetDefault(p.id)}
                      disabled={busyId !== null}
                      className="px-2 py-1 rounded border border-border text-text-secondary hover:bg-bg-hover hover:text-text disabled:opacity-50 transition-colors"
                    >
                      设为默认
                    </button>
                  )}
                  <button
                    type="button"
                    data-testid={`provider-test-${p.id}`}
                    onClick={() => void onTest(p.id)}
                    disabled={busyId !== null}
                    className="px-2 py-1 rounded border border-border text-text-secondary hover:bg-bg-hover hover:text-text disabled:opacity-50 transition-colors"
                  >
                    测试连接
                  </button>
                  <button
                    type="button"
                    data-testid={`provider-remove-${p.id}`}
                    onClick={() => void onRemove(p.id)}
                    disabled={busyId !== null || p.isDefault}
                    className="px-2 py-1 rounded border border-error/40 text-error hover:bg-error/10 disabled:opacity-40 transition-colors"
                  >
                    删除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent data-testid="providers-add-dialog">
          <DialogHeader>
            <DialogTitle>添加更新源</DialogTitle>
            <DialogDescription>
              配置 GitHub / Gitee / GitLab 或通用 HTTP 更新源（访问令牌将加密掩码存储）。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 text-xs">
            <div>
              <label htmlFor="provider-type-select" className="block text-text-secondary mb-1">
                更新源类型
              </label>
              <select
                id="provider-type-select"
                data-testid="provider-type-select"
                value={providerType}
                onChange={(e) => setProviderType(e.target.value as ProviderConfigSummary['type'])}
                className="w-full px-2.5 py-1.5 rounded-radius-sm border border-border bg-surface text-text"
              >
                <option value="github">GitHub</option>
                <option value="gitee">Gitee</option>
                <option value="gitlab">GitLab</option>
                <option value="generic-http">Generic HTTP</option>
              </select>
            </div>

            <div>
              <label htmlFor="provider-display-name" className="block text-text-secondary mb-1">
                显示名称
              </label>
              <input
                id="provider-display-name"
                data-testid="provider-display-name-input"
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="例如：内网镜像源"
                className="w-full px-2.5 py-1.5 rounded-radius-sm border border-border bg-surface text-text"
              />
            </div>

            {(providerType === 'github' || providerType === 'gitee') && (
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label htmlFor="provider-owner" className="block text-text-secondary mb-1">
                    Owner / 组织
                  </label>
                  <input
                    id="provider-owner"
                    data-testid="provider-owner-input"
                    type="text"
                    value={owner}
                    onChange={(e) => setOwner(e.target.value)}
                    placeholder="oneMuggle"
                    className="w-full px-2.5 py-1.5 rounded-radius-sm border border-border bg-surface text-text"
                  />
                </div>
                <div>
                  <label htmlFor="provider-repo" className="block text-text-secondary mb-1">
                    仓库名 (Repo)
                  </label>
                  <input
                    id="provider-repo"
                    data-testid="provider-repo-input"
                    type="text"
                    value={repo}
                    onChange={(e) => setRepo(e.target.value)}
                    placeholder="sage"
                    className="w-full px-2.5 py-1.5 rounded-radius-sm border border-border bg-surface text-text"
                  />
                </div>
              </div>
            )}

            {providerType === 'gitlab' && (
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label htmlFor="provider-base-url" className="block text-text-secondary mb-1">
                    GitLab 地址
                  </label>
                  <input
                    id="provider-base-url"
                    type="url"
                    value={baseUrl}
                    onChange={(e) => setBaseUrl(e.target.value)}
                    placeholder="https://gitlab.com"
                    className="w-full px-2.5 py-1.5 rounded-radius-sm border border-border bg-surface text-text"
                  />
                </div>
                <div>
                  <label htmlFor="provider-project-id" className="block text-text-secondary mb-1">
                    Project ID
                  </label>
                  <input
                    id="provider-project-id"
                    type="text"
                    value={projectId}
                    onChange={(e) => setProjectId(e.target.value)}
                    placeholder="12345"
                    className="w-full px-2.5 py-1.5 rounded-radius-sm border border-border bg-surface text-text"
                  />
                </div>
              </div>
            )}

            {providerType !== 'generic-http' && (
              <div>
                <label htmlFor="provider-token" className="block text-text-secondary mb-1">
                  访问令牌 (Token，公开仓库可留空)
                </label>
                <input
                  id="provider-token"
                  data-testid="provider-token-input"
                  type="password"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  placeholder="••••••••"
                  className="w-full px-2.5 py-1.5 rounded-radius-sm border border-border bg-surface text-text"
                />
              </div>
            )}

            {providerType === 'generic-http' && (
              <>
                <div>
                  <label htmlFor="provider-manifest-url" className="block text-text-secondary mb-1">
                    Manifest URL
                  </label>
                  <input
                    id="provider-manifest-url"
                    type="url"
                    value={manifestUrl}
                    onChange={(e) => setManifestUrl(e.target.value)}
                    placeholder="https://updates.example.com/latest.json"
                    className="w-full px-2.5 py-1.5 rounded-radius-sm border border-border bg-surface text-text"
                  />
                </div>
                <div>
                  <label htmlFor="provider-public-key" className="block text-text-secondary mb-1">
                    RSA 公钥 (PEM)
                  </label>
                  <textarea
                    id="provider-public-key"
                    rows={3}
                    value={publicKey}
                    onChange={(e) => setPublicKey(e.target.value)}
                    placeholder="-----BEGIN PUBLIC KEY-----"
                    className="w-full px-2.5 py-1.5 rounded-radius-sm border border-border bg-surface text-text font-mono"
                  />
                </div>
              </>
            )}
          </div>

          <DialogFooter>
            <button
              type="button"
              onClick={() => setAddOpen(false)}
              className="px-3 py-1.5 text-xs rounded-radius-sm border border-border text-text-secondary hover:bg-bg-hover"
            >
              取消
            </button>
            <button
              type="button"
              data-testid="providers-submit-add"
              disabled={busyId !== null}
              onClick={() => void handleSubmitAdd()}
              className="px-3 py-1.5 text-xs font-medium rounded-radius-sm bg-primary text-text-inverse hover:bg-primary-hover disabled:opacity-50"
            >
              保存更新源
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
