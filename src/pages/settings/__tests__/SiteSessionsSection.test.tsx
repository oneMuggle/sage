// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { SiteSessionsSection } from '../SiteSessionsSection';

const mocks = vi.hoisted(() => ({
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock('sonner', () => ({
  toast: { success: mocks.toastSuccess, error: mocks.toastError },
}));

const TEMPLATES = [
  {
    id: 'cnki',
    display_name: '知网 CNKI',
    domains: ['cnki.net'],
    login_url: 'https://kns.cnki.net/',
    login_hint: 'campus or personal account',
  },
];

const SITE = {
  domain: '.cnki.net',
  display_name: '知网 CNKI',
  login_url: 'https://kns.cnki.net/',
  kind: 'cookie' as const,
  status: 'logged_in' as const,
  expires_in_seconds: 3600,
  has_local_storage: true,
  origin_count: 1,
  saved_at: Date.now(),
  source_profile: 'login-default',
};

function jsonResponse(payload: unknown, ok = true): Response {
  return {
    ok,
    status: ok ? 200 : 500,
    json: async () => payload,
  } as Response;
}

function installFetch(initialSites: unknown[], afterLoginSites: unknown[] = initialSites) {
  let sites = initialSites;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? 'GET').toUpperCase();
    if (url.endsWith('/api/v1/web-access/sites') && method === 'GET') {
      return jsonResponse({ sites });
    }
    if (url.endsWith('/api/v1/web-access/site-templates')) {
      return jsonResponse({ templates: TEMPLATES });
    }
    if (url.endsWith('/api/v1/web-access/sites/login') && method === 'POST') {
      sites = afterLoginSites;
      return jsonResponse({ job_id: 'j-1' });
    }
    if (url.endsWith('/api/v1/web-access/sites/login/j-1')) {
      return jsonResponse({ job_id: 'j-1', url: 'https://kns.cnki.net/', status: 'success' });
    }
    return jsonResponse({ ok: false, error: 'unexpected' }, false);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderSection(): void {
  render(
    <I18nProvider>
      <SiteSessionsSection pollIntervalMs={1} />
    </I18nProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  mocks.toastSuccess.mockReset();
  mocks.toastError.mockReset();
});

beforeEach(() => {
  mocks.toastSuccess.mockReset();
  mocks.toastError.mockReset();
});

describe('SiteSessionsSection', () => {
  it('shows empty state and keeps advanced section collapsed', async () => {
    installFetch([]);
    renderSection();

    await waitFor(() => expect(screen.getByTestId('site-sessions-empty')).toBeTruthy());
    expect(screen.getByText(/还没有登录任何网站/)).toBeTruthy();
    expect(screen.getByTestId('site-advanced')).not.toHaveAttribute('open');
  });

  it('renders a signed-in website with human status', async () => {
    installFetch([SITE]);
    renderSection();

    await waitFor(() => expect(screen.getByTestId('site-row-.cnki.net')).toBeTruthy());
    expect(screen.getAllByText('知网 CNKI').length).toBeGreaterThan(0);
    expect(screen.getByTestId('site-status-.cnki.net').textContent).toContain('已登录');
    expect(screen.getByText('浏览器会话')).toBeTruthy();
  });

  it('fills the URL from a template and starts a login job', async () => {
    const fetchMock = installFetch([], [SITE]);
    renderSection();
    await waitFor(() => expect(screen.getByTestId('site-sessions-empty')).toBeTruthy());

    fireEvent.change(screen.getByTestId('site-template-select'), { target: { value: 'cnki' } });
    expect((screen.getByTestId('site-url-input') as HTMLInputElement).value).toBe(
      'https://kns.cnki.net/',
    );

    fireEvent.click(screen.getByTestId('site-login-btn'));
    await waitFor(() => expect(mocks.toastSuccess).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByTestId('site-row-.cnki.net')).toBeTruthy());

    const urls = fetchMock.mock.calls.map((call) => String(call[0]));
    expect(urls.some((url) => url.endsWith('/web-access/sites/login'))).toBe(true);
    expect(urls.some((url) => url.endsWith('/web-access/sites/login/j-1'))).toBe(true);
  });

  it('rejects a non-http URL without calling the API', async () => {
    const fetchMock = installFetch([]);
    renderSection();
    await waitFor(() => expect(screen.getByTestId('site-sessions-empty')).toBeTruthy());

    fireEvent.change(screen.getByTestId('site-url-input'), { target: { value: 'file:///etc' } });
    fireEvent.click(screen.getByTestId('site-login-btn'));

    expect(mocks.toastError).toHaveBeenCalled();
    const posts = fetchMock.mock.calls.filter(
      (call) => String(call[0]).endsWith('/web-access/sites/login'),
    );
    expect(posts).toHaveLength(0);
  });
});
