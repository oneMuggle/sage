// src/features/chat/readAloudStore.ts
//
// 对话阅读体验 B1（docs/mcp-chat-reading-nav-optimization.md §10.4）：全局唯一的
// 朗读播放状态。同一时刻只朗读一条消息：开始新的朗读会先打断旧的；再次点击
// 同一条即停止。片段逐个入队交给 speechSynthesis，最后一个片段结束时复位。
//
// speechSynthesis.cancel() 会让已入队片段触发 error / end 回调 —— 用自增的
// 播放代次过滤掉旧代次的回调，避免旧朗读的收尾把新朗读的状态清掉。

import { create } from 'zustand';

import {
  detectSpeechLang,
  isSpeechSupported,
  pickVoice,
  splitSpeechChunks,
  toSpeechText,
} from './speech';

interface ReadAloudState {
  /** 正在朗读的消息 ID；null = 空闲 */
  speakingId: string | null;
  /** 朗读一条消息（Markdown 原文）；codeOmitted = 代码块的替代提示语 */
  speak: (messageId: string, markdown: string, codeOmitted: string) => void;
  stop: () => void;
}

let generation = 0;

export const useReadAloudStore = create<ReadAloudState>((set) => ({
  speakingId: null,
  speak: (messageId, markdown, codeOmitted) => {
    if (!isSpeechSupported()) return;
    const synth = window.speechSynthesis;
    generation += 1;
    const mine = generation;
    synth.cancel();
    const text = toSpeechText(markdown, codeOmitted);
    const chunks = splitSpeechChunks(text);
    if (chunks.length === 0) {
      set({ speakingId: null });
      return;
    }
    const lang = detectSpeechLang(text);
    const voice = pickVoice(synth.getVoices(), lang);
    const finish = (): void => {
      if (generation !== mine) return;
      generation += 1;
      set({ speakingId: null });
    };
    chunks.forEach((chunk, index) => {
      const utterance = new window.SpeechSynthesisUtterance(chunk);
      utterance.lang = lang;
      if (voice) utterance.voice = voice;
      utterance.onerror = () => {
        // 合成失败时丢弃剩余片段，不要读一半跳一半
        if (generation === mine) synth.cancel();
        finish();
      };
      if (index === chunks.length - 1) utterance.onend = finish;
      synth.speak(utterance);
    });
    set({ speakingId: messageId });
  },
  stop: () => {
    generation += 1;
    if (isSpeechSupported()) window.speechSynthesis.cancel();
    set({ speakingId: null });
  },
}));
