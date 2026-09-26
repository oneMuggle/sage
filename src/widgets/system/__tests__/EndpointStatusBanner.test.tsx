// 对话阅读体验第二轮 C3：端点不可达全局提示条。
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_SETTINGS, type EndpointConfig } from '../../../entities/setting/types';
import { useSettingsStore } from '../../../features/manage-settings/settingsStore';
import { useEndpointStatusStore, type EndpointIssue } from '../../../shared/lib/endpointStatus';
import { I18nProvider } from '../../../shared/lib/i18n';
import { EndpointStatusBanner } from '../EndpointStatusBanner';

const fetchModels = vi.fn();
vi.mock('../../../features/manage-endpoints/api', () => ({
  fetchModelsByProtocol: (...args: unknown[]) => fetchModels(...args),
}));
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock('sonner', () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

const endpoint: EndpointConfig = {
  id: 'ep-1',
  name: 'Test',
  baseUrl: 'https://api.example.com/v1',
  apiKey: 'sk-test',
  protocol: 'openai-compatible',
  modelId: '',
  localModelPath: '',
  discoveredModels: [],
  lastDiscoveredAt: null,
};

const issue = (patch: Partial<EndpointIssue> = {}): EndpointIssue => ({
  kind: 'network',
  baseUrl: 'https://api.example.com/v1',
  host: 'api.example.com',
  model: 'gpt-test',
  status: null,
  message: 'connect ECONNREFUSED',
  at: 1,
  ...patch,
});

function setOnline(value: boolean) {
  Object.defineProperty(window.navigator, 'onLine', { configurable: true, get: () => value });
}

const renderBanner = () =>
  render(
    <I18nProvider defaultLocale="zh">
      <MemoryRouter>
        <EndpointStatusBanner />
      </MemoryRouter>
    </I18nProvider>,
  );

beforeEach(() => {
  setOnline(true);
  fetchModels.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
  useEndpointStatusStore.setState({ issue: null, dismissed: false });
  useSettingsStore.setState({
    settings: {
      ...DEFAULT_SETTINGS,
      endpoints: [endpoint],
      modelSelections: {
        ...DEFAULT_SETTINGS.modelSelections,
        chatModel: { endpointId: 'ep-1', modelId: 'gpt-test' },
      },
    },
  });
});

afterEach(() => {
  setOnline(true);
});

describe('EndpointStatusBanner', () => {
  it('stays hidden while the endpoint is fine', () => {
    renderBanner();
    expect(screen.queryByTestId('endpoint-banner')).toBeNull();
    expect(screen.queryByTestId('endpoint-banner-offline')).toBeNull();
  });

  it('describes the unreachable endpoint and can be dismissed', () => {
    useEndpointStatusStore.setState({ issue: issue() });
    renderBanner();
    expect(screen.getByTestId('endpoint-banner')).toHaveTextContent(
      '无法连接模型端点 api.example.com，请检查网络或代理设置（模型 gpt-test）',
    );
    fireEvent.click(screen.getByTestId('endpoint-banner-dismiss'));
    expect(screen.queryByTestId('endpoint-banner')).toBeNull();
  });

  it('uses the gateway wording for 5xx outages', () => {
    useEndpointStatusStore.setState({ issue: issue({ kind: 'server', status: 503, model: null }) });
    renderBanner();
    expect(screen.getByTestId('endpoint-banner')).toHaveTextContent(
      '模型端点 api.example.com 暂时不可用（HTTP 503）',
    );
  });

  it('clears the notice when a re-check reaches the endpoint', async () => {
    fetchModels.mockResolvedValueOnce([]);
    useEndpointStatusStore.setState({ issue: issue() });
    renderBanner();
    fireEvent.click(screen.getByTestId('endpoint-banner-recheck'));
    await waitFor(() => expect(useEndpointStatusStore.getState().issue).toBeNull());
    expect(fetchModels).toHaveBeenCalledWith(
      'openai-compatible',
      'https://api.example.com/v1',
      'sk-test',
    );
    expect(toastSuccess).toHaveBeenCalledWith('模型端点已恢复连接');
    expect(screen.queryByTestId('endpoint-banner')).toBeNull();
  });

  it('keeps the notice and reports when the re-check still fails', async () => {
    fetchModels.mockRejectedValueOnce(new Error('ETIMEDOUT'));
    useEndpointStatusStore.setState({ issue: issue() });
    renderBanner();
    fireEvent.click(screen.getByTestId('endpoint-banner-recheck'));
    await waitFor(() => expect(toastError).toHaveBeenCalledWith('仍无法连接：ETIMEDOUT'));
    expect(screen.getByTestId('endpoint-banner')).toBeInTheDocument();
  });

  it('hides a stale notice after switching to another endpoint', () => {
    useEndpointStatusStore.setState({ issue: issue({ baseUrl: 'https://other.test/v1' }) });
    renderBanner();
    expect(screen.queryByTestId('endpoint-banner')).toBeNull();
  });

  it('shows an offline notice and re-checks silently once back online', async () => {
    fetchModels.mockResolvedValueOnce([]);
    useEndpointStatusStore.setState({ issue: issue() });
    renderBanner();

    setOnline(false);
    act(() => {
      window.dispatchEvent(new Event('offline'));
    });
    expect(screen.getByTestId('endpoint-banner-offline')).toHaveTextContent('网络已断开');

    setOnline(true);
    act(() => {
      window.dispatchEvent(new Event('online'));
    });
    await waitFor(() => expect(useEndpointStatusStore.getState().issue).toBeNull());
    expect(toastSuccess).not.toHaveBeenCalled();
    expect(screen.queryByTestId('endpoint-banner-offline')).toBeNull();
  });
});
