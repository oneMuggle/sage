import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { MineruServiceCard } from '../MineruServiceCard';

const { mocks } = vi.hoisted(() => ({
  mocks: { status: vi.fn(), getPreference: vi.fn(), setPreference: vi.fn() },
}));

vi.mock('../../../shared/api/mineruApi', () => ({
  mineruApi: { status: mocks.status },
}));
vi.mock('../../../shared/api/settingsClient', () => ({
  settingsClient: {
    getPreference: mocks.getPreference,
    setPreference: mocks.setPreference,
  },
}));

function renderCard() {
  return render(
    <I18nProvider defaultLocale="zh">
      <MineruServiceCard />
    </I18nProvider>,
  );
}

describe('MineruServiceCard', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('shows server status and warns when auth required without key', async () => {
    mocks.status.mockResolvedValue({
      configured: true,
      enabled: true,
      hasApiKey: false,
      reachable: true,
      serverAuthMode: 'required',
      serverTiers: ['flash', 'standard'],
      serverVersion: '4.1.7',
      reason: 'api_key_required_or_invalid',
    });
    mocks.getPreference.mockResolvedValue(
      JSON.stringify({ enabled: true, baseUrl: 'http://10.0.0.8:8000' }),
    );
    renderCard();
    expect(await screen.findByText(/需要 API Key/)).toBeTruthy();
    expect(screen.getByDisplayValue('http://10.0.0.8:8000')).toBeTruthy();
  });

  it('persists edited fields', async () => {
    mocks.status.mockResolvedValue({
      configured: false,
      enabled: false,
      hasApiKey: false,
      reachable: false,
      serverAuthMode: 'unknown',
      serverTiers: null,
      serverVersion: null,
      reason: 'not_configured',
    });
    mocks.getPreference.mockResolvedValue(null);
    mocks.setPreference.mockResolvedValue(undefined);
    renderCard();
    const input = await screen.findByPlaceholderText('http://10.0.0.8:8000');
    fireEvent.change(input, { target: { value: 'http://10.1.1.1:8000' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() => expect(mocks.setPreference).toHaveBeenCalled());
    const [, raw] = mocks.setPreference.mock.calls[0];
    expect(JSON.parse(raw).baseUrl).toBe('http://10.1.1.1:8000');
  });
});
