import { Send } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { useTypewriterPlaceholder } from '../../features/welcome/useTypewriterPlaceholder';

interface WelcomeInputCardProps {
  placeholder?: string;
  typewriterPhrases?: string[];
  onSend?: (value: string) => void;
  disabled?: boolean;
  initialValue?: string;
}

/**
 * win7 适配:Welcome 页是首次进入应用的引导屏,主 input 走简单 textarea 行内实现。
 * main 版的同位置组件引自 `../chat/InputCard`(带附件 / slash command / 知识库引用),
 * win7 没有该组件,移植它需连带 port `SlashCommandMenu` + `slashCommands` 两个
 * 未在 win7 实现的依赖,投入产出比不匹配 Welcome 屏"轻量输入"定位。
 *
 * 如未来 win7 Chat 也升级到 main 同款 InputCard,可把本组件还原为
 * `<InputCard value onChange onSubmit placeholder disabled autoFocus />` 调用。
 */
export function WelcomeInputCard({
  placeholder,
  typewriterPhrases,
  onSend,
  disabled = false,
  initialValue = '',
}: WelcomeInputCardProps) {
  const [value, setValue] = useState(initialValue);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const { current: typewriterText } = useTypewriterPlaceholder(typewriterPhrases ?? ['']);

  useEffect(() => {
    setValue(initialValue);
  }, [initialValue]);

  useEffect(() => {
    // autoFocus
    textareaRef.current?.focus();
  }, []);

  const handleChange = (newValue: string) => {
    setValue(newValue);
  };

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed || !onSend) return;
    onSend(trimmed);
    setValue('');
  };

  const effectivePlaceholder =
    typewriterPhrases && typewriterPhrases.length > 0 ? typewriterText : (placeholder ?? '');

  return (
    <div className="w-full max-w-2xl mx-auto" data-testid="welcome-input-card">
      <div className="focus-within:shadow-[0_0_0_3px_var(--primary-focus-ring)] transition-shadow rounded-radius-md border border-border bg-surface">
        <div className="flex items-end gap-2 p-3">
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => handleChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSubmit();
              }
            }}
            placeholder={effectivePlaceholder}
            disabled={disabled}
            rows={1}
            className="flex-1 resize-none bg-transparent text-sm text-text placeholder:text-muted focus:outline-none disabled:opacity-50 max-h-32"
            aria-label={effectivePlaceholder}
          />
          <button
            type="button"
            onClick={handleSubmit}
            disabled={disabled || value.trim().length === 0}
            className="inline-flex items-center justify-center w-8 h-8 rounded-radius-sm bg-primary text-text-inverse hover:opacity-90 disabled:opacity-30 disabled:cursor-not-allowed transition-opacity"
            aria-label="send"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
