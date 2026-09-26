// 对话阅读体验 B1：朗读播放状态 —— 分片入队、末片结束复位、切换打断、错误收尾。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useReadAloudStore } from '../readAloudStore';

class FakeUtterance {
  text: string;
  lang = '';
  voice: unknown = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(text: string) {
    this.text = text;
  }
}

function installSpeech() {
  const spoken: FakeUtterance[] = [];
  const synth = {
    speak: vi.fn((u: FakeUtterance) => {
      spoken.push(u);
    }),
    cancel: vi.fn(),
    getVoices: vi.fn(() => []),
  };
  vi.stubGlobal('speechSynthesis', synth);
  vi.stubGlobal('SpeechSynthesisUtterance', FakeUtterance);
  return { synth, spoken };
}

beforeEach(() => {
  useReadAloudStore.setState({ speakingId: null });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('readAloudStore (B1)', () => {
  it('queues sentence chunks and resets after the last chunk ends', () => {
    const { synth, spoken } = installSpeech();
    useReadAloudStore.getState().speak('m1', '第一句话。'.repeat(60), '代码略');
    expect(synth.cancel).toHaveBeenCalledTimes(1);
    expect(spoken.length).toBeGreaterThan(1);
    expect(spoken.every((u) => u.lang === 'zh-CN')).toBe(true);
    expect(useReadAloudStore.getState().speakingId).toBe('m1');

    spoken[0].onend?.();
    expect(useReadAloudStore.getState().speakingId).toBe('m1');
    spoken[spoken.length - 1].onend?.();
    expect(useReadAloudStore.getState().speakingId).toBeNull();
  });

  it('switching messages interrupts the old one and ignores its stale callbacks', () => {
    const { synth, spoken } = installSpeech();
    const store = useReadAloudStore.getState();
    store.speak('m1', 'Hello there.', 'code');
    const old = spoken[spoken.length - 1];
    store.speak('m2', '你好。', '代码');
    expect(synth.cancel).toHaveBeenCalledTimes(2);
    expect(useReadAloudStore.getState().speakingId).toBe('m2');

    // cancel() 让旧片段收到 interrupted 错误与 end
    old.onerror?.();
    old.onend?.();
    expect(useReadAloudStore.getState().speakingId).toBe('m2');
    expect(synth.cancel).toHaveBeenCalledTimes(2);
  });

  it('stop() cancels playback; a synthesis error drops the remaining chunks', () => {
    const { synth, spoken } = installSpeech();
    const store = useReadAloudStore.getState();
    store.speak('m1', 'One. Two.', 'code');
    store.stop();
    expect(useReadAloudStore.getState().speakingId).toBeNull();
    expect(synth.cancel).toHaveBeenCalledTimes(2);

    store.speak('m1', 'x'.repeat(400), 'code');
    expect(spoken.slice(-3).map((u) => u.text.length)).toEqual([180, 180, 40]);
    spoken[spoken.length - 3].onerror?.();
    expect(synth.cancel).toHaveBeenCalledTimes(4);
    expect(useReadAloudStore.getState().speakingId).toBeNull();
  });

  it('does nothing for content without readable text or without speech support', () => {
    useReadAloudStore.getState().speak('m1', 'hello', 'code');
    expect(useReadAloudStore.getState().speakingId).toBeNull();

    const { synth } = installSpeech();
    useReadAloudStore.getState().speak('m1', '   ', 'code');
    expect(synth.speak).not.toHaveBeenCalled();
    expect(useReadAloudStore.getState().speakingId).toBeNull();
  });
});
