import { useEffect, useState } from 'react';

import { InputCard } from '../chat/InputCard';
import { useTypewriterPlaceholder } from '../../features/welcome/useTypewriterPlaceholder';

interface WelcomeInputCardProps {
  placeholder?: string;
  typewriterPhrases?: string[];
  onSend?: (value: string) => void;
  disabled?: boolean;
  initialValue?: string;
}

export function WelcomeInputCard({
  placeholder,
  typewriterPhrases,
  onSend,
  disabled = false,
  initialValue = '',
}: WelcomeInputCardProps) {
  const [value, setValue] = useState(initialValue);

  const { current: typewriterText } = useTypewriterPlaceholder(
    typewriterPhrases ?? [''],
  );

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
    typewriterPhrases && typewriterPhrases.length > 0 ? typewriterText : placeholder ?? '';

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
    </div>
  );
}
