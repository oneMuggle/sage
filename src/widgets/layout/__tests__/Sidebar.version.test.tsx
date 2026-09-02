import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { useStore } from '../../../shared/lib/store';
import { Sidebar } from '../Sidebar';

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
  localStorage.clear();
  const setState = useStore.setState as unknown as (partial: Record<string, unknown>) => void;
  setState({ currentSessionId: null, sessions: [] });
});

/**
 * 页脚版本号来自构建期注入的 `__APP_VERSION__`（PR-1.2）。
 *
 * 原先硬编码 `v0.1.1`，与 `package.json` 的真实版本长期脱节。改为 Vite `define`
 * 注入后，测试只断言"显示的就是注入值"，避免把版本号二次硬编码进测试。
 */
describe('Sidebar — footer version', () => {
  it('renders the injected build version instead of a hardcoded string', () => {
    render(
      <I18nProvider defaultLocale="zh">
        <MemoryRouter initialEntries={['/chat']}>
          <Sidebar />
        </MemoryRouter>
      </I18nProvider>,
    );

    expect(__APP_VERSION__).toMatch(/^\d+\.\d+\.\d+/);
    expect(screen.getByText(`v${__APP_VERSION__}`)).toBeInTheDocument();
    expect(screen.queryByText('v0.1.1')).not.toBeInTheDocument();
  });
});
