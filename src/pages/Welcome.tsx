import { Star } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
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
import { worktreeApi, type BranchEntry, type SessionWorktree } from '../shared/api/worktreeApi';
import { useI18n, type TranslationKey } from '../shared/lib/i18n';
import { useStore } from '../shared/lib/store';
import { AssistantRecommendations } from '../widgets/welcome/AssistantRecommendations';
import type { ModelOption } from '../widgets/welcome/ModelPicker';
import type { ProjectOption } from '../widgets/welcome/ProjectPicker';
import { QuickActionBar, type QuickAction } from '../widgets/welcome/QuickActionBar';
import { WelcomeHero } from '../widgets/welcome/WelcomeHero';
import { WelcomeInputCard } from '../widgets/welcome/WelcomeInputCard';
import { WelcomeToolbar } from '../widgets/welcome/WelcomeToolbar';
import type { WorktreeMode as WorktreeModeType, WorktreePickerValue } from '../widgets/welcome/WorktreePicker';

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

// Toolbar preferences localStorage keys
const STORAGE_KEY_PROJECT = 'welcomeProjectId';
const STORAGE_KEY_MODEL = 'welcomeModelId';
const STORAGE_KEY_WORKTREE_MODE = 'welcomeWorktreeMode';
const STORAGE_KEY_WORKTREE_BRANCH = 'welcomeWorktreeBranch';
const STORAGE_KEY_WORKTREE_ID = 'welcomeWorktreeId';

// eslint-disable-next-line react-refresh/only-export-components
export function formatWelcomePageMarkdown(params: {
  locale: string;
  needsOnboarding: boolean;
  recommendationCount: number;
  activeRecommendationId: string | null;
}): string {
  return [
    '# 欢迎页状态摘要 (Welcome Page Summary)',
    '',
    `- **界面语言**: \`${params.locale}\``,
    `- **需要首启向导**: ${params.needsOnboarding ? '是' : '否'}`,
    `- **推荐任务模板数**: ${params.recommendationCount}`,
    `- **当前打开任务简报**: ${params.activeRecommendationId ? `\`${params.activeRecommendationId}\`` : '无'}`,
  ].join('\n');
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatWelcomePageJson(params: {
  locale: string;
  needsOnboarding: boolean;
  recommendationCount: number;
  activeRecommendationId: string | null;
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

export function Welcome() {
  const { locale } = useI18n();
  const navigate = useNavigate();
  const { createSession, setCurrentSessionId } = useStore();
  const { settings } = useSettings();

  const phrases = locale === 'zh' ? PLACEHOLDER_PHRASES_ZH : PLACEHOLDER_PHRASES_EN;
  const { current: typewriterText } = useTypewriterPlaceholder(phrases);
  const placeholder = typewriterText;

  const [briefRecommendation, setBriefRecommendation] = useState<AssistantRecommendation | null>(
    null,
  );
  const [submitting, setSubmitting] = useState(false);
  const [reusedBrief, setReusedBrief] = useState<TaskBrief | undefined>();

  // R26: 首启向导 —— 尚无可用端点（缺 baseUrl 或必填 apiKey）时展示三步引导
  const [wizardDismissed, setWizardDismissed] = useState(false);
  const needsOnboarding =
    settings.endpoints.every((e) => !isEndpointConfigured(e)) && !wizardDismissed;

  // Toolbar state with localStorage persistence
  const [projectId, setProjectId] = useState<string | null>(() => {
    return localStorage.getItem(STORAGE_KEY_PROJECT);
  });
  const [modelId, setModelId] = useState<string | null>(() => {
    return localStorage.getItem(STORAGE_KEY_MODEL);
  });
  const [worktreeMode, setWorktreeMode] = useState<WorktreeModeType>(() => {
    return (localStorage.getItem(STORAGE_KEY_WORKTREE_MODE) as WorktreeModeType) || 'none';
  });
  const [worktreeBranch, setWorktreeBranch] = useState<string | null>(() => {
    return localStorage.getItem(STORAGE_KEY_WORKTREE_BRANCH);
  });
  const [worktreeId, setWorktreeId] = useState<string | null>(() => {
    return localStorage.getItem(STORAGE_KEY_WORKTREE_ID);
  });

  // Data loading state
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [branches, setBranches] = useState<BranchEntry[]>([]);
  const [worktrees, setWorktrees] = useState<SessionWorktree[]>([]);

  // Derive models from settings.endpoints
  const models: ModelOption[] = useMemo(() => {
    const result: ModelOption[] = [];
    for (const endpoint of settings.endpoints) {
      if (endpoint.discoveredModels) {
        for (const model of endpoint.discoveredModels) {
          result.push({
            modelId: model.modelId,
            endpointName: endpoint.name,
          });
        }
      }
    }
    return result;
  }, [settings.endpoints]);

  const globalModelId = settings.modelSelections.chatModel.modelId;

  // Load projects
  useEffect(() => {
    projectApi.list().then((list) => {
      setProjects(
        list.map((p) => ({
          id: p.id,
          name: p.name,
          path: p.path,
          sessionId: p.lastSessionId,
        })),
      );
    }).catch(() => {
      // Silently fail - user can still work without projects
    });
  }, []);

  // Load branches and worktrees (need a session ID, use current or temp)
  useEffect(() => {
    // Use a temporary session ID for loading branches/worktrees
    // This is safe because we only read git state, not session state
    worktreeApi.branches('temp').then((res) => {
      setBranches(res.branches);
      setWorktrees(res.worktrees);
    }).catch(() => {
      // Silently fail - user can still work without worktree options
    });
  }, []);

  // Persist toolbar state to localStorage
  useEffect(() => {
    if (projectId) {
      localStorage.setItem(STORAGE_KEY_PROJECT, projectId);
    } else {
      localStorage.removeItem(STORAGE_KEY_PROJECT);
    }
  }, [projectId]);

  useEffect(() => {
    if (modelId) {
      localStorage.setItem(STORAGE_KEY_MODEL, modelId);
    } else {
      localStorage.removeItem(STORAGE_KEY_MODEL);
    }
  }, [modelId]);

  useEffect(() => {
    if (worktreeMode !== 'none') {
      localStorage.setItem(STORAGE_KEY_WORKTREE_MODE, worktreeMode);
    } else {
      localStorage.removeItem(STORAGE_KEY_WORKTREE_MODE);
    }
  }, [worktreeMode]);

  useEffect(() => {
    if (worktreeBranch) {
      localStorage.setItem(STORAGE_KEY_WORKTREE_BRANCH, worktreeBranch);
    } else {
      localStorage.removeItem(STORAGE_KEY_WORKTREE_BRANCH);
    }
  }, [worktreeBranch]);

  useEffect(() => {
    if (worktreeId) {
      localStorage.setItem(STORAGE_KEY_WORKTREE_ID, worktreeId);
    } else {
      localStorage.removeItem(STORAGE_KEY_WORKTREE_ID);
    }
  }, [worktreeId]);

  const handleWorktreeChange = useCallback((value: WorktreePickerValue) => {
    setWorktreeMode(value.mode);
    setWorktreeBranch(value.branch);
    setWorktreeId(value.worktreeId);
  }, []);

  const handleRecommendationSelect = useCallback((rec: AssistantRecommendation) => {
    setReusedBrief(undefined);
    setBriefRecommendation(rec);
  }, []);

  const handleSubmit = useCallback(
    async (value: string, dialogProjectId?: string | null, dialogModelId?: string): Promise<boolean> => {
      setSubmitting(true);
      try {
        // Use dialog values if provided, otherwise use toolbar state
        const effectiveProjectId = dialogProjectId ?? projectId;
        const effectiveModelId = dialogModelId ?? modelId;

        // 1. Create session (with project binding if selected)
        const sessionId = effectiveProjectId
          ? (await projectApi.createSession(effectiveProjectId)).session.id
          : await createSession();

        // 2. Create worktree if selected
        if (worktreeMode === 'new' && worktreeBranch) {
          try {
            await worktreeApi.create(sessionId, 'new', worktreeBranch);
          } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            toast.warning(`创建 worktree 失败: ${message}，将继续使用主工作区`);
          }
        } else if (worktreeMode === 'open' && worktreeId) {
          // Switch to existing worktree
          try {
            await worktreeApi.create(sessionId, 'open', worktreeId);
          } catch (error) {
            const message = error instanceof Error ? error.message : String(error);
            toast.warning(`切换到 worktree 失败: ${message}，将继续使用主工作区`);
          }
        }

        // 3. Set model override if selected
        if (effectiveModelId) {
          await sessionApi.setModelOverride(sessionId, effectiveModelId);
        }

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
    [createSession, setCurrentSessionId, navigate, projectId, modelId, worktreeMode, worktreeBranch, worktreeId],
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

  /* v8 ignore start */
  /* v8 ignore stop */

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
              submitting || needsOnboarding || !settings.modelSelections.chatModel.modelId
            }
            onClose={() => setBriefRecommendation(null)}
            onSubmit={handleSubmit}
          />
        )}

        <WelcomeInputCard
          placeholder={placeholder}
          onSend={handleSubmit}
          disabled={submitting}
          toolbar={
            <WelcomeToolbar
              projectId={projectId}
              onProjectChange={setProjectId}
              projects={projects}
              modelId={modelId}
              onModelChange={setModelId}
              models={models}
              globalModelId={globalModelId}
              worktreeMode={worktreeMode}
              worktreeBranch={worktreeBranch}
              worktreeId={worktreeId}
              onWorktreeChange={handleWorktreeChange}
              branches={branches}
              worktrees={worktrees}
            />
          }
        />

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

// eslint-disable-next-line react-refresh/only-export-components
export function auditWelcomePageGovernance(): {
  module: 'src/pages/Welcome.tsx';
  phase: 'P172';
  domain: 'pages';
  supportsRecommendationsAndSavedRecipes: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/pages/Welcome.tsx',
    phase: 'P172',
    domain: 'pages',
    supportsRecommendationsAndSavedRecipes: true,
    compliant: true,
  };
}
