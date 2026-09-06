// src/widgets/chat/__tests__/SessionUsageBadge.test.tsx
// U14 会话用量徽章测试 — usageApi 全 mock。
import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import type { SessionUsage } from '../../../shared/api/usageApi';
import { SessionUsageBadge } from '../SessionUsageBadge';

const mockFetch = vi.fn<(sessionId: string) => Promise<SessionUsage>>();

vi.mock('../../../shared/api/usageApi', () => ({
  fetchSessionUsage: (sessionId: string) => mockFetch(sessionId),
}));

describe('SessionUsageBadge', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders nothing without a session', () => {
    const { container } = render(<SessionUsageBadge sessionId={null} />);
    expect(container.querySelector('[data-testid="session-usage-badge"]')).toBeNull();
  });

  it('shows token and cost when usage exists', async () => {
    mockFetch.mockResolvedValue({
      session_id: 's1',
      requests: 5,
      prompt_tokens: 900,
      completion_tokens: 100,
      total_tokens: 1000,
      estimated_cost_usd: 0.0123,
    });
    render(<SessionUsageBadge sessionId="s1" />);
    await waitFor(() => {
      expect(screen.getByTestId('session-usage-badge')).toBeInTheDocument();
    });
    expect(screen.getByText(/1.0k tok/)).toBeInTheDocument();
    expect(screen.getByText(/· \$0\.0123/)).toBeInTheDocument();
  });

  it('hides badge when session has no usage', async () => {
    mockFetch.mockResolvedValue({
      session_id: 's1',
      requests: 0,
      prompt_tokens: 0,
      completion_tokens: 0,
      total_tokens: 0,
      estimated_cost_usd: 0,
    });
    const { container } = render(<SessionUsageBadge sessionId="s1" />);
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith('s1');
    });
    expect(container.querySelector('[data-testid="session-usage-badge"]')).toBeNull();
  });
});
