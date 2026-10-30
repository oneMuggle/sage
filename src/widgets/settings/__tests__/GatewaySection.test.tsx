// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../GatewayCard', () => ({
  GatewayCard: ({ platform }: { platform: string }) => (
    <div data-testid={`gateway-card-${platform}`} />
  ),
}));

import { GatewaySection } from '../GatewaySection';

describe('GatewaySection', () => {
  it('默认折叠：不挂载网关卡（零请求）', () => {
    render(<GatewaySection />);
    expect(screen.queryByTestId('gateway-card-telegram')).not.toBeInTheDocument();
    expect(screen.queryByTestId('gateway-card-discord')).not.toBeInTheDocument();
    expect(screen.queryByTestId('gateway-card-slack')).not.toBeInTheDocument();
  });

  it('展开后挂载三个平台卡片，收起后卸载', () => {
    render(<GatewaySection />);
    fireEvent.click(screen.getByText('展开网关配置'));
    expect(screen.getByTestId('gateway-card-telegram')).toBeInTheDocument();
    expect(screen.getByTestId('gateway-card-discord')).toBeInTheDocument();
    expect(screen.getByTestId('gateway-card-slack')).toBeInTheDocument();

    fireEvent.click(screen.getByText('收起网关配置'));
    expect(screen.queryByTestId('gateway-card-telegram')).not.toBeInTheDocument();
  });
});
