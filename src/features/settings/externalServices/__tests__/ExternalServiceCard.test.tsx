import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../../shared/lib/i18n';
import { ExternalServiceCard } from '../ExternalServiceCard';
import type { ExternalServiceUiSpec } from '../registry';

const { mocks } = vi.hoisted(() => ({
  mocks: { getPreference: vi.fn(), setPreference: vi.fn() },
}));

vi.mock('../../../../shared/api/settingsClient', () => ({
  settingsClient: {
    getPreference: mocks.getPreference,
    setPreference: mocks.setPreference,
  },
}));

const BASE_SPEC: ExternalServiceUiSpec = {
  key: 'ocr_config',
  title: 'Demo service',
  description: 'Declarative demo',
  statusEndpoint: '/api/v1/demo/status',
  defaults: { baseUrl: '', enabled: false },
  fields: [
    { jsonKey: 'baseUrl', label: 'Base URL', type: 'text', placeholder: 'http://demo' },
    { jsonKey: 'enabled', label: 'Enabled', type: 'boolean' },
  ],
  fetchStatus: async () => ({
    configured: false,
    enabled: false,
    hasApiKey: false,
    reachable: false,
    reason: 'not_configured',
  }),
  testId: 'demo-service-card',
};

const CUSTOM_STATUS_SPEC: ExternalServiceUiSpec = {
  ...BASE_SPEC,
  renderStatus: (status) => <div>custom:{status.reason}</div>,
};

function renderCard(spec: ExternalServiceUiSpec) {
  return render(
    <I18nProvider defaultLocale="zh">
      <ExternalServiceCard spec={spec} />
    </I18nProvider>,
  );
}

describe('ExternalServiceCard', () => {
  beforeEach(() => {
    mocks.getPreference.mockResolvedValue(null);
    mocks.setPreference.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders fields and status from the declarative spec', async () => {
    renderCard(BASE_SPEC);

    expect(screen.getByLabelText('Base URL')).toBeTruthy();
    expect(screen.getByLabelText('Enabled')).toBeTruthy();
    expect(screen.getByText('Demo service')).toBeTruthy();
    expect(await screen.findByText(/服务不可达/)).toBeTruthy();
    expect(screen.getByTestId('demo-service-card')).toBeTruthy();
  });

  it('uses a custom status renderer when provided', async () => {
    renderCard(CUSTOM_STATUS_SPEC);

    expect(await screen.findByText('custom:not_configured')).toBeTruthy();
  });

  it('persists edited values under the spec preference key', async () => {
    renderCard(BASE_SPEC);

    const input = await screen.findByPlaceholderText('http://demo');
    fireEvent.change(input, { target: { value: 'http://changed' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => expect(mocks.setPreference).toHaveBeenCalled());
    const [key, raw] = mocks.setPreference.mock.calls[0];
    expect(key).toBe('ocr_config');
    expect(JSON.parse(raw).baseUrl).toBe('http://changed');
  });
});
