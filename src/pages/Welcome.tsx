import { Globe, MessageCircle, Star } from 'lucide-react';
import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { defaultRecommendations } from '../entities/welcome/recommendations';
import { useTypewriterPlaceholder } from '../features/welcome/useTypewriterPlaceholder';
import { useI18n, type TranslationKey } from '../shared/lib/i18n';
import { useStore } from '../shared/lib/store';
import { AssistantRecommendations } from '../widgets/welcome/AssistantRecommendations';
import { QuickActionBar, type QuickAction } from '../widgets/welcome/QuickActionBar';
import { WelcomeHero } from '../widgets/welcome/WelcomeHero';
import { WelcomeInputCard } from '../widgets/welcome/WelcomeInputCard';

const PLACEHOLDER_PHRASES_ZH = [
  '帮我写代码...',
  '解释这段代码...',
  '脑暴一个点子...',
  '总结这篇文章...',
  '翻译成英文...',
];

const PLACEHOLDER_PHRASES_EN = [
  'Help me write code...',
  'Explain this snippet...',
  'Brainstorm an idea...',
  'Summarize this article...',
  'Translate to English...',
];

const GITHUB_URL = 'https://github.com/';
const WEBUI_URL = 'http://localhost:8765/webui';

export function Welcome() {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const { createSession, setCurrentSessionId } = useStore();

  const phrases = locale === 'zh' ? PLACEHOLDER_PHRASES_ZH : PLACEHOLDER_PHRASES_EN;
  const { current: typewriterText } = useTypewriterPlaceholder(phrases);
  const placeholder = typewriterText;

  const [prefill, setPrefill] = useState('');

  const handleRecommendationSelect = useCallback((rec: { prompt: string }) => {
    setPrefill(rec.prompt);
  }, []);

  const handleSubmit = useCallback(
    async (value: string) => {
      try {
        const sessionId = await createSession();
        setCurrentSessionId(sessionId);
        navigate('/chat');
        // The submitted prompt is the prefill value (already injected via initialValue);
        // we just need to create a session and route the user to the chat page.
        // Future enhancement: send the prompt via useChat here.
        void value;
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error);
        toast.error(`创建会话失败: ${message}`);
      }
    },
    [createSession, setCurrentSessionId, navigate],
  );

  const quickActions: QuickAction[] = [
    {
      id: 'feedback',
      icon: <MessageCircle className="w-4 h-4" />,
      labelKey: 'welcome.quick.feedback' as TranslationKey,
      descKey: 'welcome.quick.feedback_desc' as TranslationKey,
      onClick: () => {
        toast.info('反馈功能开发中…');
      },
    },
    {
      id: 'github',
      icon: <Star className="w-4 h-4" />,
      labelKey: 'welcome.quick.github' as TranslationKey,
      descKey: 'welcome.quick.github_desc' as TranslationKey,
      onClick: () => {
        window.open(GITHUB_URL, '_blank', 'noopener,noreferrer');
      },
    },
    {
      id: 'webui',
      icon: <Globe className="w-4 h-4" />,
      labelKey: 'welcome.quick.webui' as TranslationKey,
      descKey: 'welcome.quick.webui_desc' as TranslationKey,
      onClick: () => {
        window.open(WEBUI_URL, '_blank', 'noopener,noreferrer');
      },
      badge: { text: t('welcome.quick.webui_unavailable'), variant: 'warning' },
    },
  ];

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-y-auto">
      <div className="flex-1 flex flex-col items-center justify-start pt-[10vh] px-4 pb-8 gap-6">
        <WelcomeHero onBack={() => navigate(-1)} />

        <WelcomeInputCard initialValue={prefill} placeholder={placeholder} onSend={handleSubmit} />

        <AssistantRecommendations
          recommendations={defaultRecommendations}
          onSelect={handleRecommendationSelect}
        />

        <div className="mt-8">
          <QuickActionBar actions={quickActions} />
        </div>
      </div>
    </div>
  );
}
