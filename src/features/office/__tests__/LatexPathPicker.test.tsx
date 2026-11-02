import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { LatexPathPicker } from '../LatexPathPicker';

const ORIGINAL_ELECTRON_API = (window as { electronAPI?: unknown }).electronAPI;

function Harness({ onChange }: { onChange: (value: string) => void }) {
  const [value, setValue] = useState('');
  return (
    <LatexPathPicker
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange(next);
      }}
      title="选择 LaTeX 文件"
      extensions={['tex', 'ltx']}
      placeholder="paper/main.tex"
      testId="latex-picker-test"
    />
  );
}

beforeEach(() => {
  Object.defineProperty(window, 'electronAPI', {
    value: { selectFile: vi.fn().mockResolvedValue('/ws/paper/main.tex') },
    configurable: true,
  });
});

afterEach(() => {
  Object.defineProperty(window, 'electronAPI', {
    value: ORIGINAL_ELECTRON_API,
    configurable: true,
  });
  vi.clearAllMocks();
});

describe('LatexPathPicker', () => {
  it('uses the native picker and updates the value', async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    fireEvent.click(screen.getByTestId('latex-picker-test-pick'));

    await waitFor(() =>
      expect(onChange).toHaveBeenCalledWith('/ws/paper/main.tex'),
    );
    expect(screen.getByTestId('latex-picker-test')).toHaveValue(
      '/ws/paper/main.tex',
    );
  });

  it('accepts a dropped file with an allowed extension', async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const file = new File(['content'], 'main.tex');
    Object.defineProperty(file, 'path', { value: '/ws/main.tex' });

    fireEvent.drop(screen.getByTestId('latex-picker-test-dropzone'), {
      dataTransfer: { files: [file] },
    });

    await waitFor(() => expect(onChange).toHaveBeenCalledWith('/ws/main.tex'));
  });

  it('rejects a dropped file with an unsupported extension', async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const file = new File(['content'], 'main.pdf');
    Object.defineProperty(file, 'path', { value: '/ws/main.pdf' });

    fireEvent.drop(screen.getByTestId('latex-picker-test-dropzone'), {
      dataTransfer: { files: [file] },
    });

    await waitFor(() =>
      expect(screen.getByText(/不支持的文件类型/)).toBeInTheDocument(),
    );
    expect(onChange).not.toHaveBeenCalled();
  });
});
