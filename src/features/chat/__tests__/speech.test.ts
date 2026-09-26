// 对话阅读体验 B1：朗读的纯逻辑 —— 支持检测、朗读文本、语言判断、切片、选语音。
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  detectSpeechLang,
  isSpeechSupported,
  pickVoice,
  SPEECH_CHUNK_MAX,
  splitSpeechChunks,
  toSpeechText,
} from '../speech';

function voice(lang: string, localService: boolean): SpeechSynthesisVoice {
  const name = `${lang}-${localService ? 'local' : 'remote'}`;
  return { lang, localService, name, voiceURI: name, default: false } as SpeechSynthesisVoice;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('speech helpers (B1)', () => {
  it('reports support only when speechSynthesis and the utterance class both exist', () => {
    expect(isSpeechSupported()).toBe(false);
    vi.stubGlobal('speechSynthesis', {});
    expect(isSpeechSupported()).toBe(false);
    vi.stubGlobal('SpeechSynthesisUtterance', class {});
    expect(isSpeechSupported()).toBe(true);
  });

  it('turns markdown into speech text with code blocks omitted', () => {
    const md = '## 步骤\n先运行：\n```bash\nnpm test\n```\n**完成**   即可';
    expect(toSpeechText(md, '此处代码已略过。')).toBe(
      '步骤\n先运行：\n\n此处代码已略过。\n\n完成 即可',
    );
  });

  it('picks the speech language by the han / latin ratio', () => {
    expect(detectSpeechLang('请用 React 写一个 TodoList 组件')).toBe('zh-CN');
    expect(detectSpeechLang('Use React to build a TodoList component')).toBe('en-US');
    expect(detectSpeechLang('1234 !!!')).toBe('en-US');
  });

  it('splits long text into sentence-aligned chunks within the limit', () => {
    const sentence = '这是一个用于测试朗读切分的句子。';
    const text = sentence.repeat(30);
    const chunks = splitSpeechChunks(text);
    expect(chunks.length).toBeGreaterThan(1);
    expect(chunks.every((c) => c.length <= SPEECH_CHUNK_MAX && c.endsWith('。'))).toBe(true);
    expect(chunks.join('').replace(/ /g, '')).toBe(text);
  });

  it('merges short sentences and cuts over-long ones at commas, else hard', () => {
    expect(splitSpeechChunks('Hello world. This is Sage! Ready?')).toEqual([
      'Hello world. This is Sage! Ready?',
    ]);
    const commas = `${'x'.repeat(100)}，${'y'.repeat(100)}`;
    expect(splitSpeechChunks(commas)).toEqual([`${'x'.repeat(100)}，`, 'y'.repeat(100)]);
    expect(splitSpeechChunks('a'.repeat(400)).map((c) => c.length)).toEqual([180, 180, 40]);
    expect(splitSpeechChunks('   ')).toEqual([]);
  });

  it('prefers a local voice of the language, then any voice of it', () => {
    const remoteZh = voice('zh-CN', false);
    const localZh = voice('zh-CN', true);
    const localTw = voice('zh-TW', true);
    const localEn = voice('en-US', true);
    expect(pickVoice([remoteZh, localTw, localZh, localEn], 'zh-CN')).toBe(localZh);
    expect(pickVoice([remoteZh, localTw], 'zh-CN')).toBe(localTw);
    expect(pickVoice([remoteZh], 'zh-CN')).toBe(remoteZh);
    expect(pickVoice([voice('en_GB', false)], 'en-US')?.lang).toBe('en_GB');
    expect(pickVoice([localEn], 'zh-CN')).toBeNull();
  });
});
