/**
 * 共享工具白名单编辑器：外部 `value` 同步与本地逐字输入互不覆盖。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ToolAllowlistEditor } from '../ToolAllowlistEditor';

const runtimeTools = vi.fn();
const listPlugins = vi.fn();

vi.mock('../../../shared/api/pluginClient', async () => {
  const actual = await vi.importActual<typeof import('../../../shared/api/pluginClient')>(
    '../../../shared/api/pluginClient',
  );
  return {
    ...actual,
    pluginClient: {
      ...actual.pluginClient,
      runtimeTools: (...a: unknown[]) => runtimeTools(...a),
      list: (...a: unknown[]) => listPlugins(...a),
    },
  };
});

const textarea = () => document.getElementById('agent-tools') as HTMLTextAreaElement;

/** 等待插件快照两个请求落到终态，避免测试结束后的 act 警告。 */
const settle = () =>
  screen.findByText('当前没有已发布的运行中插件工具。先到插件页启动插件，再刷新。');

beforeEach(() => {
  runtimeTools.mockReset().mockResolvedValue([]);
  listPlugins.mockReset().mockResolvedValue([]);
});

describe('ToolAllowlistEditor external value sync', () => {
  it('writes an externally changed value back into the textarea', async () => {
    const { rerender } = render(<ToolAllowlistEditor value={['read_file']} onChange={vi.fn()} />);
    await settle();
    expect(textarea().value).toBe('read_file');

    rerender(<ToolAllowlistEditor value={['read_file', 'web_search']} onChange={vi.fn()} />);

    expect(textarea().value).toBe('read_file\nweb_search');
  });

  it('keeps in-progress typing when the parent does not echo the new value', async () => {
    const onChange = vi.fn();
    const { rerender } = render(<ToolAllowlistEditor value={['read_file']} onChange={onChange} />);
    await settle();

    fireEvent.change(textarea(), { target: { value: 'read_file, web_se' } });
    expect(textarea().value).toBe('read_file, web_se');

    // 父组件仍持有旧 value（未回写 props）时，不能把草稿覆盖掉
    rerender(<ToolAllowlistEditor value={['read_file']} onChange={onChange} />);
    expect(textarea().value).toBe('read_file, web_se');
    expect(onChange).toHaveBeenLastCalledWith(['read_file', 'web_se']);
  });

  it('keeps duplicate entries in the draft but reports the deduped list', async () => {
    const onChange = vi.fn();
    render(<ToolAllowlistEditor value={[]} onChange={onChange} />);
    await settle();

    fireEvent.change(textarea(), { target: { value: 'bash\nbash\nread_file' } });

    expect(textarea().value).toBe('bash\nbash\nread_file');
    expect(onChange).toHaveBeenLastCalledWith(['bash', 'read_file']);
  });

  it('honours idPrefix and label overrides', async () => {
    render(
      <ToolAllowlistEditor
        value={[]}
        onChange={vi.fn()}
        idPrefix="specialist"
        label="工具能力（高级）"
      />,
    );
    await settle();

    expect(document.getElementById('specialist-tools')).toBeInTheDocument();
    expect(screen.getByText('工具能力（高级）')).toBeInTheDocument();
  });
});
