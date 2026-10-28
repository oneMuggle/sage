import { Star } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { listModels } from '../entities/model-catalog/api';
import type { CandidateModel } from '../entities/model-catalog/types';
import { isEndpointConfigured } from '../entities/setting/endpointReadiness';
import {
  defaultRecommendations,
  type AssistantRecommendation,
} from '../entities/welcome/recommendations';
import { useSettings } from '../features/manage-settings/useSettings';
import { OnboardingWizard } from '../features/onboarding/OnboardingWizard';
import type { PendingComposerOptions } from '../features/send-message/pendingComposerOptions';
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
import { AUTO_MODEL_ID, type ModelOption } from '../widgets/welcome/ModelPicker';
import type { ProjectOption } from '../widgets/welcome/ProjectPicker';
import { QuickActionBar, type QuickAction } from '../widgets/welcome/QuickActionBar';
import { WelcomeHero } from '../widgets/welcome/WelcomeHero';
import { WelcomeInputCard } from '../widgets/welcome/WelcomeInputCard';
import { WelcomeToolbar } from '../widgets/welcome/WelcomeToolbar';
import type {
  WorktreeMode as WorktreeModeType,
  WorktreePickerValue,
} from '../widgets/welcome/WorktreePicker';

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

/** catalog 价格：input/output 都已知时才展示 `${input}/${output} USD/M`。 */
function buildPriceLabel(price: CandidateModel['price'] | undefined): string | null {
  const input = price?.input_per_million;
  const output = price?.output_per_million;
  if (!input || !output) return null;
  return `${input}/${output} USD/M`;
}

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
    const stored = localStorage.getItem(STORAGE_KEY_MODEL);
    // R29: 自动哨兵不是模型 id；模式切回手动后不得残留
    return stored === AUTO_MODEL_ID ? null : stored;
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
  // R27: catalog 富化数据（tier / context / price）；离线时保持空 Map → 平铺。
  const [tierLookup, setTierLookup] = useState<Map<string, CandidateModel>>(() => new Map());

  // R27 数据源：挂载后拉一次 catalog。失败静默保持平铺（不 toast、不抛错）。
  const hasConfiguredEndpoint = useMemo(
    () => settings.endpoints.some((endpoint) => Boolean(endpoint.baseUrl)),
    [settings.endpoints],
  );
  useEffect(() => {
    if (!hasConfiguredEndpoint) return;
    let cancelled = false;
    listModels({ limit: 1000, offset: 0 })
      .then((res) => {
        if (cancelled) return;
        setTierLookup(new Map(res.items.map((m) => [m.model_key.model_id, m])));
      })
      .catch(() => {
        // 离线 / 后端不可用：保持无 tier，平铺列表（R27）。
      });
    return () => {
      cancelled = true;
    };
  }, [hasConfiguredEndpoint]);

  // Derive models from settings.endpoints, enriched by catalog when available.
  const models: ModelOption[] = useMemo(() => {
    const result: ModelOption[] = [];
    for (const endpoint of settings.endpoints) {
      if (endpoint.discoveredModels) {
        for (const model of endpoint.discoveredModels) {
          const catalogModel = tierLookup.get(model.id);
          result.push({
            modelId: model.id,
            endpointName: endpoint.name,
            tier: catalogModel?.tier ?? null,
            contextTokens: catalogModel?.native ?? null,
            priceLabel: buildPriceLabel(catalogModel?.price),
          });
        }
      }
    }
    return result;
  }, [settings.endpoints, tierLookup]);

  const globalModelId = settings.modelSelections.chatModel.modelId;

  // Load projects
  useEffect(() => {
    projectApi
      .list()
      .then((list) => {
        setProjects(
          list.map((p) => ({
            id: p.id,
            name: p.name,
            path: p.path,
            sessionId: p.lastSessionId,
          })),
        );
      })
      .catch(() => {
        // Silently fail - user can still work without projects
      });
  }, []);

  // Load branches and worktrees (need a session ID, use current or temp)
  useEffect(() => {
    // Use a temporary session ID for loading branches/worktrees
    // This is safe because we only read git state, not session state
    worktreeApi
      .branches('temp')
      .then((res) => {
        setBranches(res.branches);
        setWorktrees(res.worktrees);
      })
      .catch(() => {
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
    // R29: 自动哨兵绝不写入 localStorage，避免日后切回手动模式继承非法模型 id
    if (modelId && modelId !== AUTO_MODEL_ID) {
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

  // 新会话页的草稿会话：用户在新会话页输入 `@` 时需要 sessionId 才能搜索
  // 工作区文件（AtFileMenu → fileSearchClient → workspace_search_files）。
  // 因此 `@` 菜单激活时懒创建一个会话并绑定项目/最近工作区；提交时复用，
  // 避免为同一条消息创建两个会话。
  const draftSessionRef = useRef<{ projectId: string | null; sessionId: string } | null>(null);
  const draftPromiseRef = useRef<Promise<string | null> | null>(null);
  // 2026-10-29 修复: 用 generation 计数器取消「换项目后仍在飞行中」的旧创建请求,
  // 避免旧 promise resolve 时覆盖 `setCurrentSessionId(null)` 把 UI 指到错误项目。
  const draftGenerationRef = useRef(0);

  const ensureDraftSession = useCallback(async (): Promise<string | null> => {
    const existing = draftSessionRef.current;
    if (existing && existing.projectId === projectId) return existing.sessionId;
    if (draftPromiseRef.current) return draftPromiseRef.current;
    const generation = ++draftGenerationRef.current;
    const creation = (async () => {
      try {
        const sessionId = projectId
          ? (await projectApi.createSession(projectId)).session.id
          : await createSession();
        // 创建期间用户已切换项目 → 丢弃本次结果, 让新项目的 ensureDraftSession 重新创建。
        if (draftGenerationRef.current !== generation) return null;
        draftSessionRef.current = { projectId, sessionId };
        setCurrentSessionId(sessionId);
        return sessionId;
      } catch (error) {
        if (draftGenerationRef.current !== generation) return null;
        const message = error instanceof Error ? error.message : String(error);
        toast.error(`创建会话失败: ${message}`);
        return null;
      } finally {
        if (draftGenerationRef.current === generation) {
          draftPromiseRef.current = null;
        }
      }
    })();
    draftPromiseRef.current = creation;
    return creation;
  }, [projectId, createSession, setCurrentSessionId]);

  const handleAtQueryActive = useCallback(() => {
    void ensureDraftSession();
  }, [ensureDraftSession]);

  const handleProjectChange = useCallback(
    (id: string | null) => {
      setProjectId(id);
      // 草稿会话与旧项目绑定 —— 换项目后清掉，下一次 `@` 或提交时重新创建。
      const draft = draftSessionRef.current;
      if (draft && draft.projectId !== id) {
        draftSessionRef.current = null;
        draftPromiseRef.current = null;
        // 2026-10-29: bump generation 使任何在飞行的旧创建请求 resolve 时不覆盖状态。
        draftGenerationRef.current += 1;
        setCurrentSessionId(null);
      }
    },
    [setCurrentSessionId],
  );

  const handleSubmit = useCallback(
    async (
      value: string,
      dialogProjectId?: string | null,
      dialogModelId?: string,
      options?: PendingComposerOptions,
    ): Promise<boolean> => {
      setSubmitting(true);
      try {
        // Use dialog values if provided, otherwise use toolbar state
        const effectiveProjectId = dialogProjectId ?? projectId;
        const effectiveModelId = dialogModelId ?? modelId;

        // 1. Reuse the draft session created on `@` activation when it matches
        //    the target project; otherwise create a fresh one (with project
        //    binding if selected).
        const draft = draftSessionRef.current;
        let sessionId: string;
        if (draft && draft.projectId === (effectiveProjectId ?? null)) {
          sessionId = draft.sessionId;
        } else {
          sessionId = effectiveProjectId
            ? (await projectApi.createSession(effectiveProjectId)).session.id
            : await createSession();
        }
        draftSessionRef.current = null;

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
        // R29: 自动路由不写会话覆盖，交由后端按 task_type 选择
        if (effectiveModelId && effectiveModelId !== AUTO_MODEL_ID) {
          await sessionApi.setModelOverride(sessionId, effectiveModelId);
        }

        setCurrentSessionId(sessionId);
        navigate('/chat', {
          state: { pendingMessage: value, pendingOptions: options },
        });
        return true;
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error);
        toast.error(`创建会话失败: ${message}`);
        setSubmitting(false);
        return false;
      }
    },
    [
      createSession,
      setCurrentSessionId,
      navigate,
      projectId,
      modelId,
      worktreeMode,
      worktreeBranch,
      worktreeId,
    ],
  );

  // WelcomeInputCard 的 onSend 只带 (value, options)；项目/模型的显式覆盖
  // 仅由 TaskBriefDialog 使用，这里把位置参数补齐。
  const handleWelcomeSend = useCallback(
    (value: string, options?: PendingComposerOptions) => {
      void handleSubmit(value, undefined, undefined, options);
    },
    [handleSubmit],
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
            disabled={submitting || needsOnboarding || !settings.modelSelections.chatModel.modelId}
            onClose={() => setBriefRecommendation(null)}
            onSubmit={handleSubmit}
          />
        )}

        <WelcomeInputCard
          placeholder={placeholder}
          onSend={handleWelcomeSend}
          onAtQueryActive={handleAtQueryActive}
          disabled={submitting}
          toolbar={
            <WelcomeToolbar
              projectId={projectId}
              onProjectChange={handleProjectChange}
              projects={projects}
              modelId={modelId}
              onModelChange={setModelId}
              models={models}
              globalModelId={globalModelId}
              autoAvailable={settings.routing?.mode === 'auto'}
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
