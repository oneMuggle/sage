/**
 * ProvidersManager — Phase 2 (2026-09-10) Settings UI for the pluggable
 * update providers introduced in Phase 1.
 *
 * Scopes:
 *   - List user-configured providers (displayName / type / status).
 *   - Promote a non-default provider to default.
 *   - Test connectivity (`providers.test` → ping/manifest probe in main).
 *   - Remove a non-default provider.
 *   - Add a provider via guided prompts (Phase 2 keeps the UX minimal; the
 *     polished wizard lands alongside Phase 3 GitHub/Gitee/GitLab providers).
 *
 * Security: `providers.list/get` already mask `config.token` to `***masked***`
 * via providerIpc.maskToken(), so this UI never displays raw credentials.
 * Adding a provider accepts a token via `prompt()` which is a deliberate
 * Phase-2 trade-off — Phase 3's wizard replaces the prompts with a proper
 * <input type="password"> that doesn't echo back.
 */
import { useEffect, useState } from 'react';

import type { ProviderConfigSummary } from '../../shared/types/electron-api';

export function ProvidersManager(): JSX.Element {
  const [list, setList] = useState<ProviderConfigSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = async (): Promise<void> => {
    const l = await window.electronAPI?.providers.list();
    setList(l ?? []);
    setLoading(false);
  };

  useEffect(() => {
    void refresh();
  }, []);

  if (loading) return <div data-testid="providers-loading">加载中...</div>;

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
        window.alert(`连接 OK（${r.latencyMs}ms）`);
      } else {
        window.alert(`失败：${r?.error ?? 'unknown'}`);
      }
    } finally {
      setBusyId(null);
    }
  };

  const onRemove = async (id: string): Promise<void> => {
    if (!window.confirm('确定删除？')) return;
    setBusyId(id);
    try {
      await window.electronAPI?.providers.remove(id);
      await refresh();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      window.alert(`删除失败：${msg}`);
    } finally {
      setBusyId(null);
    }
  };

  const onAdd = async (): Promise<void> => {
    const choice = window.prompt('类型？\n1=github 2=gitee 3=gitlab 4=generic-http') ?? '';
    const map: Record<string, ProviderConfigSummary['type']> = {
      '1': 'github',
      '2': 'gitee',
      '3': 'gitlab',
      '4': 'generic-http',
    };
    const t = map[choice];
    if (!t) return;
    const displayName = window.prompt('显示名称？') ?? 'Untitled';
    const owner = window.prompt('owner？(github/gitee)') ?? '';
    const repo = window.prompt('repo？(github/gitee，gitlab 留空)') ?? '';
    const token = window.prompt(
      'token？(github 公开仓库可留空，gitlab 必填)',
    ) ?? '';
    const baseUrl =
      t === 'gitlab'
        ? window.prompt('baseUrl？(https://gitlab.com 或自建)') ?? ''
        : '';
    const projectId = t === 'gitlab' ? window.prompt('projectId？') ?? '' : '';
    const manifestUrl =
      t === 'generic-http' ? window.prompt('manifestUrl？') ?? '' : '';
    const publicKey =
      t === 'generic-http' ? window.prompt('RSA 公钥（PEM）？') ?? '' : '';
    const config: Record<string, unknown> = {
      channelMap: { stable: true, beta: true, alpha: true },
      requireArtifactSignature: false,
    };
    if (t === 'github' || t === 'gitee') {
      config.owner = owner;
      config.repo = repo;
      if (token) config.token = token;
    } else if (t === 'gitlab') {
      config.baseUrl = baseUrl;
      config.projectId = projectId;
      if (token) config.token = token;
    } else if (t === 'generic-http') {
      config.manifestUrl = manifestUrl;
      config.publicKey = publicKey;
      config.requireArtifactSignature = true;
    }
    setBusyId('__add__');
    try {
      await window.electronAPI?.providers.add({
        type: t,
        displayName,
        enabled: true,
        isDefault: false,
        config,
      });
      await refresh();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      window.alert(`添加失败：${msg}`);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="providers-manager" data-testid="providers-manager">
      <h2>更新源管理</h2>
      <p data-testid="providers-current-default">
        当前默认：
        {list.find((p) => p.isDefault)?.displayName ?? '（无，使用内置）'}
      </p>
      <table>
        <thead>
          <tr>
            <th>名称</th>
            <th>类型</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody data-testid="providers-list-body">
          {list.map((p) => (
            <tr key={p.id} data-testid={`provider-row-${p.id}`}>
              <td>{p.displayName}</td>
              <td>{p.type}</td>
              <td>
                {p.isDefault ? '默认' : p.enabled ? '启用' : '禁用'}
              </td>
              <td>
                {!p.isDefault && (
                  <button
                    data-testid={`provider-set-default-${p.id}`}
                    onClick={() => void onSetDefault(p.id)}
                    disabled={busyId !== null}
                  >
                    设为默认
                  </button>
                )}
                <button
                  data-testid={`provider-test-${p.id}`}
                  onClick={() => void onTest(p.id)}
                  disabled={busyId !== null}
                >
                  测试连接
                </button>
                <button
                  data-testid={`provider-remove-${p.id}`}
                  onClick={() => void onRemove(p.id)}
                  disabled={busyId !== null || p.isDefault}
                >
                  删除
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button
        data-testid="providers-add-button"
        onClick={() => void onAdd()}
        disabled={busyId !== null}
      >
        + 添加更新源
      </button>
    </div>
  );
}