// src/features/chat/speech.ts
//
// 对话阅读体验 B1（docs/mcp-chat-reading-nav-optimization.md §10.4）：消息朗读的
// 纯逻辑。朗读走 Web Speech API（speechSynthesis）；Windows 上 Chromium 使用系统
// 本地 SAPI 语音，离线可用。本模块只负责"读什么、怎么切、用哪种语言"，播放
// 状态由 readAloudStore 管理。

import { markdownToPlainText } from './markdownText';

/** 单个朗读片段的最大长度：Chromium 对过长的 utterance 可能中途静默停止 */
export const SPEECH_CHUNK_MAX = 180;

export type SpeechLang = 'zh-CN' | 'en-US';

export function isSpeechSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    'speechSynthesis' in window &&
    typeof window.SpeechSynthesisUtterance === 'function'
  );
}

/** Markdown → 朗读文本：代码块替换为提示语，其余去掉标记只留可见文字 */
export function toSpeechText(markdown: string, codeOmitted: string): string {
  return markdownToPlainText(markdown, { codeBlockReplacement: codeOmitted })
    .replace(/[ \t]+/g, ' ')
    .trim();
}

/** 按汉字与拉丁字母的占比选择朗读语言（中英混排以中文为主时仍用中文语音） */
export function detectSpeechLang(text: string): SpeechLang {
  const han = text.match(/[\u3400-\u9fff]/g)?.length ?? 0;
  const latin = text.match(/[A-Za-z]/g)?.length ?? 0;
  return han > 0 && han * 3 >= latin ? 'zh-CN' : 'en-US';
}

/** 过长的句子在逗号 / 空白处再切，实在找不到切点就硬切 */
function splitLongSentence(sentence: string, maxLen: number): string[] {
  const pieces: string[] = [];
  let rest = sentence;
  while (rest.length > maxLen) {
    const head = rest.slice(0, maxLen);
    const cut = Math.max(
      head.lastIndexOf('，'),
      head.lastIndexOf(','),
      head.lastIndexOf('、'),
      head.lastIndexOf(' '),
    );
    const end = cut > maxLen / 3 ? cut + 1 : maxLen;
    pieces.push(rest.slice(0, end).trim());
    rest = rest.slice(end).trim();
  }
  if (rest) pieces.push(rest);
  return pieces;
}

/** 按句切分并合并成不超过 maxLen 的片段，保持原有顺序 */
export function splitSpeechChunks(text: string, maxLen = SPEECH_CHUNK_MAX): string[] {
  const sentences = text
    .split(/(?<=[。！？!?；;…\n])|(?<=\.)\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
  const chunks: string[] = [];
  let buffer = '';
  for (const sentence of sentences) {
    for (const piece of splitLongSentence(sentence, maxLen)) {
      if (!buffer) {
        buffer = piece;
      } else if (buffer.length + 1 + piece.length <= maxLen) {
        buffer = `${buffer} ${piece}`;
      } else {
        chunks.push(buffer);
        buffer = piece;
      }
    }
  }
  if (buffer) chunks.push(buffer);
  return chunks;
}

/** 优先选同语种的本地语音（离线可用、延迟低），其次同语种任意语音 */
export function pickVoice(
  voices: ReadonlyArray<SpeechSynthesisVoice>,
  lang: SpeechLang,
): SpeechSynthesisVoice | null {
  const prefix = lang.slice(0, 2).toLowerCase();
  const sameLang = voices.filter((v) => v.lang.replace('_', '-').toLowerCase().startsWith(prefix));
  const exact = sameLang.filter(
    (v) => v.lang.replace('_', '-').toLowerCase() === lang.toLowerCase(),
  );
  return (
    exact.find((v) => v.localService) ??
    sameLang.find((v) => v.localService) ??
    exact[0] ??
    sameLang[0] ??
    null
  );
}
