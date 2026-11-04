// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { NumberField } from '../NumberField';

function Harness({
  initial = 5,
  onChange,
  min,
  max,
  clampOnChange,
}: {
  initial?: number;
  onChange?: (v: number) => void;
  min?: number;
  max?: number;
  clampOnChange?: boolean;
}) {
  const [value, setValue] = useState(initial);
  return (
    <NumberField
      value={value}
      min={min}
      max={max}
      clampOnChange={clampOnChange}
      testId="num"
      onChange={(next) => {
        setValue(next);
        onChange?.(next);
      }}
    />
  );
}

describe('NumberField', () => {
  it('允许清空输入而不立即回填', () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const input = screen.getByTestId('num') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '' } });
    expect(input.value).toBe('');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('清空后可以输入新数字', () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const input = screen.getByTestId('num') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '' } });
    fireEvent.change(input, { target: { value: '12' } });
    expect(input.value).toBe('12');
    expect(onChange).toHaveBeenLastCalledWith(12);
  });

  it('失焦时非法空值恢复上一次合法值', () => {
    render(<Harness initial={7} />);
    const input = screen.getByTestId('num') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '' } });
    fireEvent.blur(input);
    expect(input.value).toBe('7');
  });

  it('越界值在 clampOnChange=false 时不即时提交，失焦时钳制', () => {
    const onChange = vi.fn();
    render(
      <Harness initial={5} onChange={onChange} min={1} max={10} clampOnChange={false} />,
    );
    const input = screen.getByTestId('num') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '0' } });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.blur(input);
    expect(onChange).toHaveBeenLastCalledWith(1);
    expect(input.value).toBe('1');

    fireEvent.change(input, { target: { value: '20' } });
    expect(onChange).toHaveBeenCalledTimes(1);
    fireEvent.blur(input);
    expect(onChange).toHaveBeenLastCalledWith(10);
  });

  it('Enter 提交并失焦，Escape 还原当前已提交值', () => {
    render(<Harness initial={3} />);
    const input = screen.getByTestId('num') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '9' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(input.value).toBe('9');

    fireEvent.change(input, { target: { value: '' } });
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(input.value).toBe('9');
  });
});
