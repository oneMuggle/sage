// @vitest-environment jsdom
/**
 * P0-A (2026-09-18): 最大上下文长度编辑器 — 档位下拉 + 自定义(数值+K/M单位)。
 * 回归钉: 旧版 number input 硬编码 max=128000, 512K/1M 无法输入。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import { DEFAULT_SETTINGS, type AppSettings } from '../../../entities/setting/types';
import { ModelsTab } from '../ModelsTab';
import type { EndpointsTabProps } from '../components';

function makeProps(overrides: Partial<AppSettings> = {}): EndpointsTabProps {
  const updateSettings = vi.fn();
  const settings: AppSettings = {
    ...DEFAULT_SETTINGS,
    endpoints: [
      {
        id: 'ep1',
        name: 'OpenAI',
        baseUrl: 'https://api.openai.com/v1',
        apiKey: 'sk-x',
        protocol: 'openai-compatible',
        modelId: '',
        localModelPath: '',
        discoveredModels: [
          { id: 'gpt-4o', capabilities: ['chat', 'vision'], endpointId: 'ep1' },
        ],
        lastDiscoveredAt: 0,
      },
    ],
    ...overrides,
  };
  return { settings, updateSettings } as EndpointsTabProps;
}

function renderTab(props: EndpointsTabProps) {
  return render(
    <MemoryRouter>
      <ModelsTab {...props} />
    </MemoryRouter>,
  );
}

describe('ModelsTab 上下文长度编辑器', () => {
  it('档位下拉包含 512K / 1M / 2M (回归钉: 旧 max=128000 拦死长上下文)', () => {
    const props = makeProps();
    renderTab(props);
    const select = screen.getByLabelText('最大上下文长度档位');
    const labels = Array.from((select as HTMLSelectElement).options).map((o) => o.text);
    expect(labels).toEqual(expect.arrayContaining(['512K', '1M', '2M', '自定义…']));
  });

  it('值命中预设档时选中对应档位, 切换档位直接写回归一化 token 数', () => {
    const props = makeProps({ maxContext: 131072 });
    renderTab(props);
    const select = screen.getByLabelText('最大上下文长度档位') as HTMLSelectElement;
    expect(select.value).toBe('131072');

    fireEvent.change(select, { target: { value: '524288' } });
    expect(props.updateSettings).toHaveBeenCalledWith({ maxContext: 524288 });
  });

  it('自定义模式: 数值 + 单位切换按乘数归一化写回', () => {
    // 300000 非预设档 → 直接进自定义形态, 派生初值 300 + K
    const props = makeProps({ maxContext: 300000 });
    renderTab(props);
    expect(screen.getByLabelText('上下文长度数值')).toHaveValue(300);

    fireEvent.change(screen.getByLabelText('上下文长度数值'), { target: { value: '512' } });
    expect(props.updateSettings).toHaveBeenLastCalledWith({ maxContext: 512000 });

    fireEvent.change(screen.getByLabelText('上下文长度数值'), { target: { value: '1' } });
    fireEvent.change(screen.getByLabelText('上下文长度单位'), { target: { value: 'M' } });
    expect(props.updateSettings).toHaveBeenLastCalledWith({ maxContext: 1000000 });
  });

  it('旧数据非预设值 (8000) 自动进入自定义形态并回显', () => {
    const props = makeProps({ maxContext: 8000 });
    renderTab(props);
    const select = screen.getByLabelText('最大上下文长度档位') as HTMLSelectElement;
    expect(select.value).toBe('custom');
    // 8000 派生为 8 + K 的自定义初值
    expect(screen.getByLabelText('上下文长度数值')).toHaveValue(8);
    expect((screen.getByLabelText('上下文长度单位') as HTMLSelectElement).value).toBe('K');
    expect(screen.getByTestId('settings-context-length-resolved').textContent).toContain('8,000');
  });
});
