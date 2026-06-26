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
