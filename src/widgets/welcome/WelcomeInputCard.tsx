import { useEffect, useState } from 'react';

import { useTypewriterPlaceholder } from '../../features/welcome/useTypewriterPlaceholder';
import { InputCard } from '../chat/InputCard';

interface WelcomeInputCardProps {
  placeholder?: string;
  typewriterPhrases?: string[];
  onSend?: (value: string) => void;
  disabled?: boolean;
  initialValue?: string;
  toolbar?: React.ReactNode;
}

export function formatWelcomeInputMarkdown(params: {
  value: string;
  placeholder: string;
  disabled: boolean;
}): string {
  return [
    '# 欢迎页输入卡片草稿 (Welcome Input Draft)',
    '',
    `- **当前占位文案**: ${params.placeholder || '无'}`,
    `- **禁用状态**: ${params.disabled ? '已禁用' : '可输入'}`,
    `- **草稿字符数**: ${params.value.length}`,
    '',
    '## 草稿正文',
    '',
    params.value || '_空_',
  ].join('\n');
}

export function formatWelcomeInputJson(params: {
  value: string;
  placeholder: string;
  disabled: boolean;
}): string {
  return JSON.stringify(
    {
      exportedAt: new Date().toISOString(),
      ...params,
    },
    null,
    2,
  );
}

export function WelcomeInputCard({
  placeholder,
  typewriterPhrases,
  onSend,
  disabled = false,
  initialValue = '',
  toolbar,
}: WelcomeInputCardProps) {
  const [value, setValue] = useState(initialValue);

  const { current: typewriterText } = useTypewriterPlaceholder(typewriterPhrases ?? ['']);

  useEffect(() => {
    setValue(initialValue);
  }, [initialValue]);

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

  /* v8 ignore start */

  /* v8 ignore stop */

  return (
    <div className="w-full max-w-2xl mx-auto" data-testid="welcome-input-card">
      <div className="focus-within:shadow-[0_0_0_3px_var(--primary-focus-ring)] transition-shadow">
        <InputCard
          value={value}
          onChange={handleChange}
          onSubmit={handleSubmit}
          placeholder={effectivePlaceholder}
          disabled={disabled}
          autoFocus
        />
      </div>
      {toolbar && (
        <div className="mt-1">{toolbar}</div>
      )}
    </div>
  );
}
