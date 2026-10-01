import { Star } from 'lucide-react';
import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { isEndpointConfigured } from '../entities/setting/endpointReadiness';
import {
  defaultRecommendations,
  type AssistantRecommendation,
} from '../entities/welcome/recommendations';
import { useSettings } from '../features/manage-settings/useSettings';
import { OnboardingWizard } from '../features/onboarding/OnboardingWizard';
import { SavedTaskRecipes } from '../features/task-brief/SavedTaskRecipes';
import { TaskBriefDialog } from '../features/task-brief/TaskBriefDialog';
import type { TaskBrief } from '../features/task-brief/taskBrief';
import { useTypewriterPlaceholder } from '../features/welcome/useTypewriterPlaceholder';
import { projectApi } from '../shared/api/projectApi';
import { sessionApi } from '../shared/api/sessionApi';
import { useI18n, type TranslationKey } from '../shared/lib/i18n';
import { useStore } from '../shared/lib/store';
import { AssistantRecommendations } from '../widgets/welcome/AssistantRecommendations';
import { QuickActionBar, type QuickAction } from '../widgets/welcome/QuickActionBar';
import { WelcomeHero } from '../widgets/welcome/WelcomeHero';
import { WelcomeInputCard } from '../widgets/welcome/WelcomeInputCard';

const PLACEHOLDER_PHRASES_ZH = [
  '根据资料写一份可交付的报告…',
  '分析表格并说明计算口径…',
  '制作一份可编辑的演示文稿…',
  '总结这篇文章...',
  '翻译成英文...',
];

const PLACEHOLDER_PHRASES_EN = [
  'Create a deliverable report from sources…',
  'Analyze a spreadsheet with clear assumptions…',
  'Build an editable presentation…',
  'Summarize this article...',
  'Translate to English...',
];

const GITHUB_URL = 'https://github.com/oneMuggle/sage';

export function Welcome() {
  const { locale } = useI18n();
  const navigate = useNavigate();
  const { createSession, setCurrentSessionId } = useStore();

  const phrases = locale === 'zh' ? PLACEHOLDER_PHRASES_ZH : PLACEHOLDER_PHRASES_EN;
  const { current: typewriterText } = useTypewriterPlaceholder(phrases);
  const placeholder = typewriterText;

  const [briefRecommendation, setBriefRecommendation] = useState<AssistantRecommendation | null>(
    null,
  );
  const [submitting, setSubmitting] = useState(false);
  const [reusedBrief, setReusedBrief] = useState<TaskBrief | undefined>();

  // R26: 首启向导 —— 尚无可用端点（缺 baseUrl 或必填 apiKey）时展示三步引导
  const { settings: wizardSettings, isLoading: settingsLoading } = useSettings();
  const [wizardDismissed, setWizardDismissed] = useState(false);
  const needsOnboarding =
    !settingsLoading &&
    !wizardDismissed &&
    wizardSettings.endpoints.every((e) => !isEndpointConfigured(e));

  const handleRecommendationSelect = useCallback((rec: AssistantRecommendation) => {
    setReusedBrief(undefined);
    setBriefRecommendation(rec);
  }, []);

  const handleSubmit = useCallback(
    async (value: string, projectId: string | null = null, modelId?: string): Promise<boolean> => {
      setSubmitting(true);
      try {
        const sessionId = projectId
          ? (await projectApi.createSession(projectId)).session.id
          : await createSession();
        if (modelId) await sessionApi.setModelOverride(sessionId, modelId);
        setCurrentSessionId(sessionId);
        navigate('/chat', { state: { pendingMessage: value } });
        return true;
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error);
        toast.error(`创建会话失败: ${message}`);
        setSubmitting(false);
        return false;
      }
    },
    [createSession, setCurrentSessionId, navigate],
  );

  const quickActions: QuickAction[] = [
    {
      id: 'github',
      icon: <Star className="w-4 h-4" />,
      labelKey: 'welcome.quick.github' as TranslationKey,
      descKey: 'welcome.quick.github_desc' as TranslationKey,
      onClick: () => {
        window.open(GITHUB_URL, '_blank', 'noopener,noreferrer');
      },
    },
  ];

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-y-auto">
      <div className="flex-1 flex flex-col items-center justify-start pt-[10vh] px-4 pb-8 gap-6">
        <WelcomeHero />
        {briefRecommendation && (
          <TaskBriefDialog
            key={briefRecommendation.id}
            recommendation={briefRecommendation}
            initialBrief={reusedBrief}
            disabled={
              submitting || needsOnboarding || !wizardSettings.modelSelections.chatModel.modelId
            }
            onClose={() => setBriefRecommendation(null)}
            onSubmit={handleSubmit}
          />
        )}

        <WelcomeInputCard placeholder={placeholder} onSend={handleSubmit} disabled={submitting} />

        {needsOnboarding && <OnboardingWizard onComplete={() => setWizardDismissed(true)} />}

        <div className="flex gap-2 text-ui-base">
          <button
            type="button"
            onClick={() => navigate('/projects')}
            className="px-3 py-2 rounded border border-ui-border"
          >
            {locale === 'en' ? 'Project workbench' : '项目工作台'}
          </button>
          <button
            type="button"
            onClick={() => navigate('/office')}
            className="px-3 py-2 rounded border border-ui-border"
          >
            {locale === 'en' ? 'Documents and review' : '文档与验收'}
          </button>
        </div>
        <AssistantRecommendations
          recommendations={defaultRecommendations}
          onSelect={handleRecommendationSelect}
        />

        <SavedTaskRecipes
          onUse={(recipe) => {
            const recommendation = defaultRecommendations.find(
              (item) => item.id === recipe.brief.scenario,
            );
            if (recommendation) {
              setReusedBrief(recipe.brief);
              setBriefRecommendation(recommendation);
            }
          }}
        />
        <div className="mt-8">
          <QuickActionBar actions={quickActions} />
        </div>
      </div>
    </div>
  );
}
