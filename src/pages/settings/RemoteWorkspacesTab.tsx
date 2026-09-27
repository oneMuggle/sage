/**
 * Settings → 远程工作区（Workspace MCP Server, M4）
 *
 * Spec: docs/plans/2026-09-26-workspace-mcp-m4-ui.md §2.4
 *
 * - 后端管理 API 走 remoteMcpApi（COMMAND_ROUTES）。
 * - 隧道 / 急停 / 复制地址走 Electron 主进程（remoteMcpBridge），
 *   token 只在主进程写入剪贴板，不经过渲染进程。
 * - 写入 / 命令权限开启需二次确认（命令执行不是沙箱）。
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import {
  DEFAULT_REMOTE_MCP_PORT,
  remoteMcpApi,
  remoteMcpBridge,
  type RemoteApprovalMode,
  type RemoteMcpState,
  type RemotePermission,
  type RemoteTunnelState,
  type RemoteWorkspace,
} from '../../shared/api/remoteMcpApi';
import { useI18n } from '../../shared/lib/i18n';

import { SettingRow, Toggle } from './components';

const POLL_MS = 3000;
const PERMISSIONS: RemotePermission[] = ['read', 'write', 'shell'];

const BTN = 'px-3 py-1 text-xs rounded-radius-sm border border-border text-text hover:bg-surface transition-colors disabled:opacity-50';
const BTN_PRIMARY = 'px-3 py-1 text-xs bg-primary text-text-inverse rounded-radius-sm hover:bg-primary-hover transition-colors disabled:opacity-50';
const BTN_DANGER = 'px-3 py-1 text-xs rounded-radius-sm bg-error text-text-inverse hover:opacity-90 transition-opacity disabled:opacity-50';
const INPUT = 'px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary';

function useText(): (zh: string, en: string) => string {
  const { locale } = useI18n();
  return useCallback((zh: string, en: string) => (String(locale).startsWith('zh') ? zh : en), [locale]);
}

function errorText(err: unknown): string {
  if (err instanceof Error) return err.message.replace(/^Error invoking remote method '[^']+': (Error: )?/, '');
  return String(err);
}

export function RemoteWorkspacesTab() {
  const L = useText();
  const bridge = remoteMcpBridge();
  const [state, setState] = useState<RemoteMcpState | null>(null);
  const [tunnel, setTunnel] = useState<RemoteTunnelState | null>(null);
  const [port, setPort] = useState(String(DEFAULT_REMOTE_MCP_PORT));
  const [newName, setNewName] = useState('');
  const [newRoot, setNewRoot] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const [s, t] = await Promise.all([remoteMcpApi.state(), bridge ? bridge.tunnelState() : Promise.resolve(null)]);
      if (!mounted.current) return;
      setState(s);
      setTunnel(t);
      if (s.listener.port) setPort((prev) => (prev === String(DEFAULT_REMOTE_MCP_PORT) ? String(s.listener.port) : prev));
    } catch (err) {
      if (mounted.current) setError(errorText(err));
    }
  }, [bridge]);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const timer = setInterval(() => {
      if (typeof document === 'undefined' || document.visibilityState !== 'hidden') void refresh();
    }, POLL_MS);
    return () => {
      mounted.current = false;
      clearInterval(timer);
    };
  }, [refresh]);

  const run = async (action: () => Promise<unknown>, okNotice?: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await action();
      if (result && typeof result === 'object' && 'workspaces' in (result as object)) setState(result as RemoteMcpState);
      if (okNotice) setNotice(okNotice);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
      void refresh();
    }
  };

  const listenerRunning = state?.listener.running ?? false;
  const paused = state?.paused ?? false;
  const tunnelActive = tunnel ? tunnel.state !== 'stopped' && tunnel.state !== 'error' : false;

  const toggleListener = (on: boolean) => {
    const value = Number(port);
    void run(() => (on ? remoteMcpApi.startListener(value) : remoteMcpApi.stopListener()));
  };

  const toggleTunnel = (on: boolean) => {
    if (!bridge) return;
    if (on && !window.confirm(L(
      '开启公网通道后，任何拿到地址的人都能以已授权的权限访问工作区。地址等同于密码。继续？',
      'Anyone with the public URL can use the granted permissions. The URL is a password. Continue?',
    ))) return;
    void run(() => (on ? bridge.startTunnel() : bridge.stopTunnel()));
  };

  const emergency = () => {
    void run(async () => {
      if (bridge) await bridge.emergencyStop();
      else await remoteMcpApi.stopListener();
    }, L('已急停：通道已关闭，所有调用被拒绝', 'Emergency stop: tunnel closed, all calls refused'));
  };

  const setPermission = (ws: RemoteWorkspace, key: RemotePermission, value: boolean) => {
    if (value && key === 'shell' && !window.confirm(L(
      '命令执行不是沙箱，拥有当前 Windows 用户的全部权限。确定为该工作区开启？',
      'Command execution is NOT sandboxed and runs with your full user rights. Enable for this workspace?',
    ))) return;
    if (value && key === 'write' && !window.confirm(L(
      '开启后远端可以修改该目录下的文件（受保护路径除外）。确定？',
      'Remote clients will be able to modify files in this folder (protected paths excluded). Continue?',
    ))) return;
    void run(() => remoteMcpApi.updateWorkspace(ws.id, { permissions: { [key]: value } }));
  };

  const copy = (ws: RemoteWorkspace, usePublic: boolean) => {
    if (!bridge) return;
    void run(() => bridge.copyUrl(ws.id, { public: usePublic }), L('地址已复制到剪贴板', 'URL copied to clipboard'));
  };

  const permLabel: Record<RemotePermission, string> = {
    read: L('读取', 'Read'),
    write: L('写入', 'Write'),
    shell: L('命令', 'Commands'),
    office: 'Office',
    memory: L('记忆', 'Memory'),
  };

  return (
    <div className="space-y-6" data-testid="remote-workspaces-tab">
      <section>
        <h3 className="text-sm font-semibold text-text mb-1">{L('远程工作区（MCP）', 'Remote workspaces (MCP)')}</h3>
        <p className="text-xs text-muted">
          {L(
            '让外部 MCP 客户端（Claude Code、ShunCode 等）按授权访问本机目录。命令执行不是沙箱；公网地址等同于密码；路径黑名单不等于数据防泄漏，不要共享含敏感资料的目录。',
            'Let external MCP clients access local folders with explicit grants. Commands are not sandboxed; the public URL is a password; path deny-lists are not DLP — do not share sensitive folders.',
          )}
        </p>
      </section>

      {error ? <div data-testid="remote-mcp-error" className="px-3 py-2 text-xs text-error bg-surface rounded-radius-sm">{error}</div> : null}
      {notice ? <div data-testid="remote-mcp-notice" className="px-3 py-2 text-xs text-success bg-surface rounded-radius-sm">{notice}</div> : null}

      <section>
        <SettingRow
          label={L('MCP 监听器', 'MCP listener')}
          desc={listenerRunning
            ? `http://127.0.0.1:${state?.listener.port}/mcp/<token>`
            : state?.listener.error || L('仅监听本机回环地址', 'Loopback only')}
        >
          <div className="flex items-center gap-2">
            <input
              aria-label={L('端口', 'Port')}
              className={`${INPUT} w-20`}
              value={port}
              disabled={listenerRunning || busy}
              onChange={(e) => setPort(e.target.value.replace(/\D/g, '').slice(0, 5))}
            />
            <Toggle value={listenerRunning} onChange={toggleListener} disabled={busy} testId="remote-mcp-listener-toggle" />
          </div>
        </SettingRow>

        <SettingRow
          label={L('公网通道（Cloudflare Quick Tunnel）', 'Public tunnel (Cloudflare Quick Tunnel)')}
          desc={!bridge
            ? L('仅桌面版可用', 'Desktop app only')
            : tunnel && !tunnel.supported
              ? L('当前系统版本不提供公网通道', 'Not available on this OS version')
              : tunnelSummary(tunnel, L)}
        >
          <Toggle
            value={tunnelActive}
            onChange={toggleTunnel}
            disabled={busy || !bridge || !tunnel?.supported || (!tunnelActive && (!listenerRunning || paused))}
            testId="remote-mcp-tunnel-toggle"
          />
        </SettingRow>
        {tunnel?.addressChanged ? (
          <div className="px-3 py-2 text-xs text-warning bg-surface rounded-radius-sm">
            {L('公网地址已变化，旧地址已失效，请重新复制。', 'The public URL changed; the old one no longer works. Copy it again.')}
          </div>
        ) : null}

        <SettingRow
          label={paused ? L('已急停', 'Emergency-stopped') : L('全部急停', 'Emergency stop')}
          desc={`${L('快捷键', 'Hotkey')} Ctrl+Alt+Esc · ${tunnel?.hotkeyRegistered ? L('已注册', 'registered') : L('未注册', 'not registered')} · ${L('运行中命令', 'running commands')} ${state?.running_commands ?? 0}`}
        >
          {paused ? (
            <button type="button" className={BTN} disabled={busy} onClick={() => void run(() => remoteMcpApi.resume())}>
              {L('恢复服务', 'Resume')}
            </button>
          ) : (
            <button type="button" data-testid="remote-mcp-emergency" className={BTN_DANGER} disabled={busy} onClick={emergency}>
              {L('全部急停', 'Stop everything')}
            </button>
          )}
        </SettingRow>
      </section>

      <section>
        <h3 className="text-sm font-semibold text-text mb-3">{L('工作区', 'Workspaces')}</h3>
        <div className="flex items-center gap-2 mb-3">
          <input className={`${INPUT} w-32`} placeholder={L('名称', 'Name')} value={newName} onChange={(e) => setNewName(e.target.value)} />
          <input
            className={`${INPUT} flex-1`}
            placeholder={L('目录绝对路径（不能是盘符根或用户主目录）', 'Absolute folder path (not a drive root or home)')}
            value={newRoot}
            onChange={(e) => setNewRoot(e.target.value)}
          />
          <button
            type="button"
            className={BTN_PRIMARY}
            disabled={busy || !newName.trim() || !newRoot.trim()}
            onClick={() => void run(async () => {
              const s = await remoteMcpApi.createWorkspace(newName.trim(), newRoot.trim());
              setNewName('');
              setNewRoot('');
              return s;
            }, L('已添加（默认只读）', 'Added (read-only by default)'))}
          >
            {L('添加', 'Add')}
          </button>
        </div>

        {state && state.workspaces.length === 0 ? (
          <div className="text-xs text-muted">{L('还没有共享的工作区', 'No shared workspaces yet')}</div>
        ) : null}

        <ul className="space-y-3">
          {state?.workspaces.map((ws) => (
            <li key={ws.id} data-testid={`remote-ws-${ws.id}`} className="p-3 border border-border rounded-radius-sm space-y-2">
              <div className="flex items-center justify-between">
                <div className="min-w-0">
                  <div className="text-sm text-text truncate">{ws.name}</div>
                  <div className="text-xs text-muted font-mono truncate">{ws.root}</div>
                </div>
                <div className="flex items-center gap-2 text-xs text-muted">
                  <span>{L('会话', 'Sessions')} {ws.sessions}</span>
                  <Toggle
                    value={ws.enabled}
                    onChange={(v) => void run(() => remoteMcpApi.updateWorkspace(ws.id, { enabled: v }))}
                    disabled={busy}
                    testId={`remote-ws-enabled-${ws.id}`}
                  />
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-4 text-xs">
                {PERMISSIONS.map((key) => (
                  <label key={key} className="flex items-center gap-1 text-text">
                    <input
                      type="checkbox"
                      data-testid={`remote-ws-perm-${key}-${ws.id}`}
                      checked={Boolean(ws.permissions[key])}
                      disabled={busy || key === 'read'}
                      onChange={(e) => setPermission(ws, key, e.target.checked)}
                    />
                    {permLabel[key]}
                  </label>
                ))}
                <label className="flex items-center gap-1 text-text">
                  {L('审批', 'Approval')}
                  <select
                    data-testid={`remote-ws-approval-${ws.id}`}
                    className={INPUT}
                    value={ws.approval ?? 'auto'}
                    disabled={busy}
                    onChange={(e) =>
                      void run(() =>
                        remoteMcpApi.updateWorkspace(ws.id, { approval: e.target.value as RemoteApprovalMode }),
                      )
                    }
                  >
                    <option value="auto">{L('自动（危险命令仍需审批）', 'Auto (destructive commands still ask)')}</option>
                    <option value="ask">{L('写入和命令每次询问', 'Ask for every write / command')}</option>
                  </select>
                </label>
              </div>
              {ws.token_reset ? (
                <div className="px-2 py-1 text-xs text-warning bg-surface rounded-radius-sm">
                  {L(
                    '本机无法解密原有 token（可能换了电脑或用户），已重置并停用。启用后请重新复制地址。',
                    'The stored token could not be decrypted (new machine or user); it was reset and the workspace disabled. Re-enable and copy the URL again.',
                  )}
                </div>
              ) : null}
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" className={BTN} disabled={busy || !bridge || !ws.enabled || paused} onClick={() => copy(ws, false)}>
                  {L('复制本机地址', 'Copy local URL')}
                </button>
                <button
                  type="button"
                  className={BTN}
                  disabled={busy || !bridge || !ws.enabled || paused || !tunnel?.url}
                  onClick={() => copy(ws, true)}
                >
                  {L('复制公网地址', 'Copy public URL')}
                </button>
                <button
                  type="button"
                  className={BTN}
                  disabled={busy}
                  onClick={() => {
                    if (window.confirm(L('重置后旧地址立即失效，已连接的会话会断开。继续？', 'The old URL stops working and sessions disconnect. Continue?'))) {
                      void run(() => remoteMcpApi.rotateWorkspace(ws.id), L('已重置 token', 'Token rotated'));
                    }
                  }}
                >
                  {L('重置 token', 'Rotate token')}
                </button>
                <button
                  type="button"
                  className={`${BTN} text-error`}
                  disabled={busy}
                  onClick={() => {
                    if (window.confirm(L(`移除工作区“${ws.name}”？`, `Remove workspace "${ws.name}"?`))) {
                      void run(() => remoteMcpApi.deleteWorkspace(ws.id));
                    }
                  }}
                >
                  {L('移除', 'Remove')}
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3 className="text-sm font-semibold text-text mb-2">{L('审计（最近事件）', 'Audit (recent)')}</h3>
        {state && state.audit.length ? (
          <div className="max-h-64 overflow-auto border border-border rounded-radius-sm">
            <table className="w-full text-xs">
              <tbody>
                {state.audit.map((row, i) => (
                  <tr key={i} className="border-b border-border last:border-0">
                    <td className="px-2 py-1 text-muted font-mono whitespace-nowrap">{String(row.time ?? row.ts ?? '')}</td>
                    <td className="px-2 py-1 text-text">{row.event}</td>
                    <td className="px-2 py-1 text-muted">{row.tool ?? ''}</td>
                    <td className="px-2 py-1 text-muted">{row.code ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-xs text-muted">{L('暂无事件', 'No events')}</div>
        )}
      </section>
    </div>
  );
}

function tunnelSummary(tunnel: RemoteTunnelState | null, L: (zh: string, en: string) => string): string {
  if (!tunnel) return '';
  const names: Record<string, string> = {
    stopped: L('未开启', 'Off'),
    starting: L('正在启动…', 'Starting…'),
    running: L('运行中', 'Running'),
    degraded: L('自检失败（地址保留）', 'Self-check failed (URL kept)'),
    reconnecting: L(`重连中（第 ${tunnel.retryCount} 次）`, `Reconnecting (#${tunnel.retryCount})`),
    error: L('出错', 'Error'),
  };
  const parts = [names[tunnel.state] ?? tunnel.state];
  if (tunnel.url) parts.push(tunnel.url.replace(/^https:\/\//, ''));
  if (tunnel.health.latencyMs !== undefined && tunnel.health.state === 'healthy') parts.push(`${tunnel.health.latencyMs} ms`);
  if (tunnel.error && tunnel.state !== 'running') parts.push(tunnel.error);
  return parts.join(' · ');
}
