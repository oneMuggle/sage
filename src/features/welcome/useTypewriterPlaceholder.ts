import { useEffect, useRef, useState } from 'react';

interface TypewriterState {
  current: string;
  isTyping: boolean;
}

const TYPE_INTERVAL_MS = 50;
const PAUSE_INTERVAL_MS = 1000;

export function useTypewriterPlaceholder(phrases: string[]): TypewriterState {
  const safePhrases = phrases.length > 0 ? phrases : [''];
  const [phraseIndex, setPhraseIndex] = useState(0);
  const [charIndex, setCharIndex] = useState(1);
  const [isTyping, setIsTyping] = useState(true);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const currentPhrase = safePhrases[phraseIndex] ?? '';

  useEffect(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }

    if (charIndex < currentPhrase.length) {
      // 还在打字阶段
      setIsTyping(true);
      timerRef.current = setTimeout(() => {
        setCharIndex((ci) => ci + 1);
      }, TYPE_INTERVAL_MS);
    } else {
      // 短语打完了，进入暂停
      setIsTyping(false);
      timerRef.current = setTimeout(() => {
        setPhraseIndex((pi) => (pi + 1) % safePhrases.length);
        setCharIndex(1);
      }, PAUSE_INTERVAL_MS);
    }

    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [charIndex, phraseIndex, currentPhrase, safePhrases.length]);

  return {
    current: currentPhrase.slice(0, charIndex),
    isTyping,
  };
}
