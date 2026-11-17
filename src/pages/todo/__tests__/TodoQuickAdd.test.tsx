import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { TodoQuickAdd } from '../TodoQuickAdd';

const asrMocks = vi.hoisted(() => ({ transcribe: vi.fn() }));

vi.mock('../../../shared/api/asrClient', () => ({
  asrClient: { transcribe: asrMocks.transcribe },
}));

describe('TodoQuickAdd', () => {
  it('previews parsed due date, priority and tags', () => {
    render(<TodoQuickAdd isOpen onClose={() => {}} onSubmit={vi.fn()} />);

    fireEvent.change(screen.getByTestId('quick-add-input'), {
      target: { value: '明天下午3点 交报告 !高 #工作' },
    });

    const preview = screen.getByTestId('quick-add-preview');
    expect(preview.textContent).toContain('优先级 高');
    expect(preview.textContent).toContain('工作');
  });

  it('submits the parsed input and closes', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(<TodoQuickAdd isOpen onClose={onClose} onSubmit={onSubmit} />);

    fireEvent.change(screen.getByTestId('quick-add-input'), {
      target: { value: '后天 9点半 开会' },
    });
    fireEvent.click(screen.getByTestId('quick-add-submit'));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({
          title: '开会',
          due_at: expect.stringMatching(/T09:30:00$/),
        }),
      );
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('disables submit when the input is empty', () => {
    render(<TodoQuickAdd isOpen onClose={() => {}} onSubmit={vi.fn()} />);
    expect(screen.getByTestId('quick-add-submit')).toBeDisabled();
  });

  it('records audio and appends the transcribed text', async () => {
    asrMocks.transcribe.mockResolvedValue({ text: '明天交周报' });

    const stopTrack = vi.fn();
    const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop: stopTrack }] });
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia },
    });

    class FakeMediaRecorder {
      static isTypeSupported = () => true;
      ondataavailable: ((event: { data: Blob }) => void) | null = null;
      onstop: (() => void) | null = null;
      start() {}
      stop() {
        this.ondataavailable?.({
          data: new Blob(['audio-bytes'], { type: 'audio/webm' }),
        });
        this.onstop?.();
      }
    }
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder);

    render(<TodoQuickAdd isOpen onClose={() => {}} onSubmit={vi.fn()} />);

    fireEvent.click(screen.getByTestId('quick-add-mic'));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByTestId('quick-add-mic')).toHaveAttribute('aria-label', '停止录音'),
    );

    fireEvent.click(screen.getByTestId('quick-add-mic'));

    await waitFor(() => expect(asrMocks.transcribe).toHaveBeenCalled());
    await waitFor(() => {
      const input = screen.getByTestId('quick-add-input') as HTMLInputElement;
      expect(input.value).toContain('明天交周报');
    });
    expect(stopTrack).toHaveBeenCalled();
  });
});
