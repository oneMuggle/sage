import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../desktopInvoke', () => ({
  invoke: vi.fn(),
}));

import { asrClient } from '../asrClient';
import { invoke } from '../desktopInvoke';

const invokeMock = invoke as unknown as ReturnType<typeof vi.fn>;

describe('asrClient', () => {
  afterEach(() => {
    invokeMock.mockReset();
  });

  it('transcribe() maps to asr_transcribe with snake_case payload', async () => {
    invokeMock.mockResolvedValueOnce({ text: '明天下午三点开会' });

    const result = await asrClient.transcribe('AAAA', 'webm', 'zh');

    expect(invokeMock).toHaveBeenCalledWith('asr_transcribe', {
      audio_base64: 'AAAA',
      format: 'webm',
      language: 'zh',
    });
    expect(result.text).toBe('明天下午三点开会');
  });

  it('omits language when not provided', async () => {
    invokeMock.mockResolvedValueOnce({ text: '' });

    await asrClient.transcribe('BBBB');

    expect(invokeMock).toHaveBeenCalledWith('asr_transcribe', {
      audio_base64: 'BBBB',
      format: 'webm',
    });
  });

  it('propagates invoke failures', async () => {
    invokeMock.mockRejectedValueOnce(new Error('ASR 模型未配置'));

    await expect(asrClient.transcribe('CCCC')).rejects.toThrow('ASR 模型未配置');
  });
});
