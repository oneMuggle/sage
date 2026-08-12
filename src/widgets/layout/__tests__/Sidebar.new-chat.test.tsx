import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { useStore } from '../../../shared/lib/store';
import { Sidebar } from '../Sidebar';

// Capture the current path so we can assert that clicking "+ 新对话" navigates to /welcome
function PathProbe() {
  const location = useLocation();
  return <div data-testid="current-path">{location.pathname}</div>;
}

vi.mock('../../../features/manage-settings/useSettings', () => ({
  useSettings: () => ({
    settings: {
      endpoints: [],
      modelSelections: {
        chatModel: { endpointId: null, modelId: null },
        visionModel: { endpointId: null, modelId: null },
        embeddingModel: { endpointId: null, modelId: null },
      },
      maxContext: 4096,
      temperature: 0.7,
    },
  }),
}));

vi.mock('../../../features/manage-endpoints/api', () => ({
  testEndpointConnection: vi.fn().mockResolvedValue({ success: false }),
}));

beforeEach(() => {
  const setState = useStore.setState as unknown as (partial: Record<string, unknown>) => void;
  setState({ currentSessionId: null, sessions: [] });
});

function renderSidebar() {
  return render(
    <I18nProvider defaultLocale="zh">
      <MemoryRouter initialEntries={['/chat']}>
        <Sidebar />
        <PathProbe />
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe('Sidebar — new chat button navigates to /welcome', () => {
  it('renders the new chat button on the conversations section header', () => {
    renderSidebar();
    // The button is a Plus icon with aria-label translated to "新对话"
    const button = screen.getByRole('button', { name: /新对话/ });
    expect(button).toBeInTheDocument();
  });

  it('clicking new chat button navigates to /welcome', () => {
    renderSidebar();
    const button = screen.getByRole('button', { name: /新对话/ });
    fireEvent.click(button);
    expect(screen.getByTestId('current-path').textContent).toBe('/welcome');
  });
});

// Selecting a session while on /welcome must stay a SPA navigation —
// the previous `window.location.href = '/chat'` assignment caused a full
// page reload, producing a visible flash. We assert the route transitions
// to /chat under React Router instead of doing a full reload: under jsdom,
// `window.location.href = ...` would short-circuit React Router and the
// route probe would not see a path update.
describe('Sidebar — selecting a session from /welcome must stay a SPA navigation', () => {
  function renderSidebarOnWelcome() {
    return render(
      <I18nProvider defaultLocale="zh">
        <MemoryRouter initialEntries={['/welcome']}>
          <Sidebar />
          <PathProbe />
        </MemoryRouter>
      </I18nProvider>,
    );
  }

  beforeEach(() => {
    const setState = useStore.setState as unknown as (partial: Record<string, unknown>) => void;
    setState({
      currentSessionId: null,
      sessions: [
        {
          id: 'sess-1',
          title: '历史会话',
          createdAt: 0,
          updatedAt: 0,
          messageCount: 0,
        },
      ],
    });
  });

  it('transitions to /chat under React Router after selecting a session from /welcome', () => {
    renderSidebarOnWelcome();
    const item = screen.getByRole('button', { name: /历史会话/ });
    fireEvent.click(item);
    expect(screen.getByTestId('current-path').textContent).toBe('/chat');
  });
});
