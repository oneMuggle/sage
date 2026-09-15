/**
 * R17-C: InputCard ↑ 输入历史导航测试
 *
 * 兑现 shortcuts.ts "↑（空输入时）编辑上一条发送过的消息" 的既有承诺：
 * - 空输入 ↑ 回填最近一条发送
 * - 继续 ↑ 更早、↓ 回到较近、↓ 到头清空退出
 * - 非空输入（用户正在打字）↑ 不触发
 * - 手动编辑文本退出历史导航
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import { InputCard } from '../InputCard';

const withI18n = (ui: React.ReactElement) => <I18nProvider defaultLocale="zh">{ui}</I18nProvider>;

const setup = (inputHistory: string[]) => {
  const onChange = vi.fn();
  const onSubmit = vi.fn();
  const { rerender } = render(
    withI18n(
      <InputCard value="" onChange={onChange} onSubmit={onSubmit} inputHistory={inputHistory} />,
    ),
  );
  const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
  return { textarea, onChange, onSubmit, rerender };
};

describe('InputCard — R17-C 输入历史', () => {
  it('空输入 ↑ 回填最近一条发送', () => {
    const { textarea, onChange } = setup(['第二条', '第一条']);
    fireEvent.keyDown(textarea, { key: 'ArrowUp' });
    expect(onChange).toHaveBeenLastCalledWith('第二条');
  });

  it('继续 ↑ 走到更早的历史', () => {
    const { textarea, onChange } = setup(['B', 'A']);
    fireEvent.keyDown(textarea, { key: 'ArrowUp' });
    fireEvent.keyDown(textarea, { key: 'ArrowUp' });
    expect(onChange).toHaveBeenLastCalledWith('A');
  });

  it('↓ 回退，到头清空退出导航', () => {
    const { textarea, onChange } = setup(['B', 'A']);
    fireEvent.keyDown(textarea, { key: 'ArrowUp' }); // B
    fireEvent.keyDown(textarea, { key: 'ArrowUp' }); // A
    fireEvent.keyDown(textarea, { key: 'ArrowDown' }); // 回到 B
    expect(onChange).toHaveBeenLastCalledWith('B');
    fireEvent.keyDown(textarea, { key: 'ArrowDown' }); // 到头 → 清空
    expect(onChange).toHaveBeenLastCalledWith('');
  });

  it('非空输入 ↑ 不触发历史导航', () => {
    const onChange = vi.fn();
    const { rerender } = render(
      withI18n(
        <InputCard value="正在输入" onChange={onChange} onSubmit={vi.fn()} inputHistory={['B']} />,
      ),
    );
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    fireEvent.keyDown(textarea, { key: 'ArrowUp' });
    // 光标移动是浏览器默认行为，不产生 onChange 回填
    expect(onChange).not.toHaveBeenCalled();
    rerender(
      withI18n(
        <InputCard value="正在输入" onChange={onChange} onSubmit={vi.fn()} inputHistory={['B']} />,
      ),
    );
  });

  it('手动编辑文本后退出历史导航（不再误回填）', () => {
    const onChange = vi.fn();
    let value = '';
    const { rerender } = render(
      withI18n(
        <InputCard
          value={value}
          onChange={(v) => {
            value = v;
            onChange(v);
          }}
          onSubmit={vi.fn()}
          inputHistory={['B', 'A']}
        />,
      ),
    );
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    fireEvent.keyDown(textarea, { key: 'ArrowUp' }); // 进入历史 → B
    expect(onChange).toHaveBeenLastCalledWith('B');
    // 用户手动编辑（受控 value 更新后触发 change 事件）
    rerender(
      withI18n(
        <InputCard
          value={value}
          onChange={(v) => {
            value = v;
            onChange(v);
          }}
          onSubmit={vi.fn()}
          inputHistory={['B', 'A']}
        />,
      ),
    );
    fireEvent.change(textarea, { target: { value: 'B（改）' } });
    fireEvent.keyDown(textarea, { key: 'ArrowUp' }); // 非空输入 ↑ → 不触发
    expect(onChange).toHaveBeenLastCalledWith('B（改）');
  });

  it('inputHistory 为空时 ↑ 完全不干预', () => {
    const onChange = vi.fn();
    render(
      withI18n(<InputCard value="" onChange={onChange} onSubmit={vi.fn()} inputHistory={[]} />),
    );
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    fireEvent.keyDown(textarea, { key: 'ArrowUp' });
    expect(onChange).not.toHaveBeenCalled();
  });
});
