// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import type { ToolCall } from '../../../shared/lib/store';
import { BrowserPanel } from '../BrowserPanel';

const controlMocks = vi.hoisted(() => ({
  fetchBrowserControl: vi.fn(),
  setBrowserControl: vi.fn(),
  fetchPendingConfirmations: vi.fn(),
  resolveConfirmation: vi.fn(),
  fetchBrowserAudit: vi.fn(),
}));

vi.mock('../../../shared/api/browserControlClient', () => ({
  fetchBrowserControl: controlMocks.fetchBrowserControl,
  setBrowserControl: controlMocks.setBrowserControl,
  fetchPendingConfirmations: controlMocks.fetchPendingConfirmations,
  resolveConfirmation: controlMocks.resolveConfirmation,
  fetchBrowserAudit: controlMocks.fetchBrowserAudit,
}));

const panel = {
  show: vi.fn(async () => ({ ok: true })),
  hide: vi.fn(async () => ({ ok: true })),
  setBounds: vi.fn(async () => ({ ok: true })),
  navigate: vi.fn(async () => ({ ok: true })),
  back: vi.fn(async () => ({ ok: true })),
  forward: vi.fn(async () => ({ ok: true })),
  reload: vi.fn(async () => ({ ok: true })),
  current: vi.fn(async () => ({
    url: 'https://kns.cnki.net/',
    title: '知网',
    canGoBack: true,
    canGoForward: false,
  })),
};

class ResizeObserverStub {
  observe = vi.fn();
  disconnect = vi.fn();
}

const invoke = vi.fn(async () => ({ ok: true }));

function installElectronApi(value: typeof panel | undefined): void {
  (window as unknown as { electronAPI?: unknown }).electronAPI =
    value === undefined ? undefined : { browserPanel: value, invoke };
}

function renderPanel(toolCalls: ToolCall[] = []): ReturnType<typeof render> {
  return render(
    <I18nProvider>
      <BrowserPanel toolCalls={toolCalls} />
    </I18nProvider>,
  );
}

/** 构造 browser_* 工具调用：result 为 ToolResult.to_dict 的 JSON 字符串。 */
function browserToolCall(
  name: string,
  args: Record<string, unknown>,
  meta: Record<string, unknown>,
  id = name,
): ToolCall {
  return {
    id,
    name,
    args,
    result: JSON.stringify({
      success: true,
      content: { result: 'ok', browser_meta: { session_id: 's1', ...meta } },
    }),
  };
}

/** 构造带顶层 error 的失败工具调用（安全门禁前缀走这里）。 */
function browserErrorCall(name: string, error: string, id: string): ToolCall {
  return {
    id,
    name,
    args: {},
    result: JSON.stringify({
      success: false,
      error,
      content: { browser_meta: { session_id: 's1', action: 'navigate' } },
    }),
  };
}

/** 待确认项（M4）：字段与 BrowserPendingConfirmation 一致，可按需覆盖。 */
function pendingConfirmation(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'c1',
    session_id: 's1',
    kind: 'site_access',
    code: 'site_access',
    domain: 'example.com',
    description: '首次访问该站点',
    options: ['session', 'always', 'deny'],
    screenshot_path: '',
    created_at: 1,
    ...overrides,
  };
}

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', ResizeObserverStub);
  Object.values(panel).forEach((fn) => fn.mockClear());
  invoke.mockClear();
  controlMocks.fetchBrowserControl.mockReset();
  controlMocks.fetchBrowserControl.mockResolvedValue({
    session_id: 's1',
    state: 'agent',
    known: true,
  });
  controlMocks.setBrowserControl.mockReset();
  controlMocks.setBrowserControl.mockImplementation(async (id: string, action: string) => ({
    session_id: id,
    state: action === 'pause' ? 'paused' : action === 'takeover' ? 'user_takeover' : 'agent',
  }));
  controlMocks.fetchPendingConfirmations.mockReset();
  controlMocks.fetchPendingConfirmations.mockResolvedValue([]);
  controlMocks.resolveConfirmation.mockReset();
  controlMocks.resolveConfirmation.mockResolvedValue({
    confirmation_id: 'c1',
    kind: 'site_access',
    decision: 'always',
    control_state: 'agent',
  });
  controlMocks.fetchBrowserAudit.mockReset();
  controlMocks.fetchBrowserAudit.mockResolvedValue([]);
  panel.current.mockImplementation(async () => ({
    url: 'https://kns.cnki.net/',
    title: '知网',
    canGoBack: true,
    canGoForward: false,
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
  installElectronApi(undefined);
});

describe('BrowserPanel', () => {
  it('shows the desktop-only hint without the Electron API', () => {
    installElectronApi(undefined);
    renderPanel();
    expect(screen.getByText(/仅在 Sage 桌面端可用/)).toBeTruthy();
  });

  it('shows the BrowserView on mount, reports bounds and hides on unmount', async () => {
    installElectronApi(panel);
    const { unmount } = renderPanel();
    await waitFor(() => expect(panel.show).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(panel.setBounds).toHaveBeenCalled());
    expect((panel.setBounds.mock.calls[0] as unknown[])[0]).toMatchObject({
      x: 0,
      y: 0,
      width: 0,
      height: 0,
    });
    unmount();
    expect(panel.hide).toHaveBeenCalled();
  });

  it('navigates only for http(s) URLs', async () => {
    installElectronApi(panel);
    renderPanel();
    const input = screen.getByTestId('browser-panel-address');
    fireEvent.change(input, { target: { value: 'file:///etc/passwd' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(panel.navigate).not.toHaveBeenCalled();
    expect(screen.getByText(/http:\/\//)).toBeTruthy();

    fireEvent.change(input, { target: { value: 'https://kns.cnki.net/' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(panel.navigate).toHaveBeenCalledWith('https://kns.cnki.net/'));
  });

  it('reflects current URL and navigation buttons', async () => {
    installElectronApi(panel);
    renderPanel();
    await waitFor(() =>
      expect((screen.getByTestId('browser-panel-address') as HTMLInputElement).value).toBe(
        'https://kns.cnki.net/',
      ),
    );
    expect((screen.getByLabelText('后退') as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByLabelText('前进') as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('BrowserPanel M3 AI 操作区', () => {
  it('从 toolCalls 渲染步骤并显示交互元素名', () => {
    installElectronApi(panel);
    renderPanel([
      browserToolCall(
        'browser_navigate',
        { url: 'https://example.com/' },
        { action: 'navigate', url: 'https://example.com/' },
        'c1',
      ),
      browserToolCall(
        'browser_interact',
        { text: '搜索' },
        { action: 'interact', target_name: '搜索' },
        'c2',
      ),
    ]);
    expect(screen.getByText('打开 https://example.com/')).toBeTruthy();
    expect(screen.getByText('点击「搜索」')).toBeTruthy();
    expect(screen.getAllByText('成功')).toHaveLength(2);
  });

  it('无 browser_meta.session_id 时禁用控制按钮并提示等待', () => {
    installElectronApi(panel);
    renderPanel();
    expect(screen.getByText('等待 AI 开始浏览器操作')).toBeTruthy();
    expect((screen.getByTestId('browser-ai-pause') as HTMLButtonElement).disabled).toBe(true);
  });

  it('有 browser_meta.session_id 时控制按钮可用', () => {
    installElectronApi(panel);
    renderPanel([
      browserToolCall('browser_navigate', {}, { action: 'navigate', url: 'https://example.com/' }),
    ]);
    expect((screen.getByTestId('browser-ai-pause') as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByTestId('browser-ai-focus') as HTMLButtonElement).disabled).toBe(false);
  });

  it('点击暂停调用 setBrowserControl(pause) 并更新徽章', async () => {
    installElectronApi(panel);
    renderPanel([
      browserToolCall('browser_navigate', {}, { action: 'navigate', url: 'https://example.com/' }),
    ]);
    fireEvent.click(screen.getByTestId('browser-ai-pause'));
    await waitFor(() => expect(controlMocks.setBrowserControl).toHaveBeenCalledWith('s1', 'pause'));
    await waitFor(() => expect(screen.getByTestId('browser-ai-status').textContent).toBe('已暂停'));
  });

  it('点击接管后聚焦 agent 可见窗口', async () => {
    installElectronApi(panel);
    renderPanel([
      browserToolCall('browser_navigate', {}, { action: 'navigate', url: 'https://example.com/' }),
    ]);
    fireEvent.click(screen.getByTestId('browser-ai-takeover'));
    await waitFor(() =>
      expect(controlMocks.setBrowserControl).toHaveBeenCalledWith('s1', 'takeover'),
    );
    await waitFor(() =>
      expect(invoke).toHaveBeenCalledWith('agent_browser_focus', { session: 's1' }),
    );
  });

  it('徽章按 fetchBrowserControl 返回值渲染', async () => {
    controlMocks.fetchBrowserControl.mockResolvedValue({
      session_id: 's1',
      state: 'user_takeover',
      known: true,
    });
    installElectronApi(panel);
    renderPanel([
      browserToolCall('browser_navigate', {}, { action: 'navigate', url: 'https://example.com/' }),
    ]);
    await waitFor(() =>
      expect(screen.getByTestId('browser-ai-status').textContent).toBe('用户接管'),
    );
  });
});

describe('BrowserPanel M4 安全确认', () => {
  it('site_access 待确认项渲染 alertdialog、标题与三个选项', async () => {
    controlMocks.fetchPendingConfirmations.mockResolvedValue([pendingConfirmation()]);
    installElectronApi(panel);
    renderPanel([
      browserToolCall('browser_navigate', {}, { action: 'navigate', url: 'https://example.com/' }),
    ]);
    const bar = await screen.findByTestId('browser-confirm-bar');
    expect(bar.getAttribute('role')).toBe('alertdialog');
    expect(bar.textContent).toContain('允许 Sage 访问 example.com？');
    expect(bar.textContent).toContain('首次访问该站点');
    expect(screen.getByTestId('browser-confirm-option-session').textContent).toBe('仅本次会话');
    expect(screen.getByTestId('browser-confirm-option-always').textContent).toBe('始终允许');
    expect(screen.getByTestId('browser-confirm-option-deny').textContent).toBe('拒绝');
    expect(screen.queryByTestId('browser-confirm-option-approve')).toBeNull();
  });

  it('sensitive_action 待确认项渲染敏感操作标题与两选项', async () => {
    controlMocks.fetchPendingConfirmations.mockResolvedValue([
      pendingConfirmation({
        id: 'c2',
        kind: 'sensitive_action',
        code: 'submit_form',
        domain: '',
        description: '提交表单',
        options: ['approve', 'deny'],
      }),
    ]);
    installElectronApi(panel);
    renderPanel([
      browserToolCall('browser_navigate', {}, { action: 'navigate', url: 'https://example.com/' }),
    ]);
    const bar = await screen.findByTestId('browser-confirm-bar');
    expect(bar.textContent).toContain('确认执行敏感操作：提交表单');
    expect(screen.getByTestId('browser-confirm-option-approve').textContent).toBe('批准一次');
    expect(screen.getByTestId('browser-confirm-option-deny').textContent).toBe('拒绝');
    expect(screen.queryByTestId('browser-confirm-option-session')).toBeNull();
    expect(screen.queryByTestId('browser-confirm-option-always')).toBeNull();
  });

  it('点击「始终允许」调用 resolveConfirmation(always)', async () => {
    controlMocks.fetchPendingConfirmations.mockResolvedValue([pendingConfirmation()]);
    installElectronApi(panel);
    renderPanel([
      browserToolCall('browser_navigate', {}, { action: 'navigate', url: 'https://example.com/' }),
    ]);
    fireEvent.click(await screen.findByTestId('browser-confirm-option-always'));
    await waitFor(() =>
      expect(controlMocks.resolveConfirmation).toHaveBeenCalledWith('c1', 'always'),
    );
  });

  it('时间线按安全门禁前缀渲染等待确认 / 已拦截 / 用户已拒绝徽章', () => {
    installElectronApi(panel);
    renderPanel([
      browserErrorCall('browser_navigate', 'needs_confirmation: https://a.com/', 'e1'),
      browserErrorCall('browser_navigate', 'hard_blocked: javascript:alert(1)', 'e2'),
      browserErrorCall('browser_navigate', 'denied_by_user: site_access', 'e3'),
    ]);
    expect(screen.getByText('等待确认')).toBeTruthy();
    expect(screen.getByText('已拦截（需接管）')).toBeTruthy();
    expect(screen.getByText('用户已拒绝')).toBeTruthy();
  });
});
