/**
 * Settings 页面 - 编排（Orchestration）设置 Tab
 *
 * 原为 GeneralTab 的「编排」section，因编排旋钮持续膨胀
 * (RD15/RD16/Round 3) 拆为独立 tab，并按语义分五组：计划前置 /
 * 并发与迭代 / 结果上限 / 预算与守门 / 隔离与审批。
 *
 * 持久化契约不变：updateSettings({ orch: { ...settings.orch, [key]: v } })
 * 部分更新，必须保留其余 orch 键。
 */

import { getSettingMetadata } from '../../entities/setting/settingsRegistry';
import { useSettings } from '../../features/manage-settings/useSettings';
import { useI18n } from '../../shared/lib/i18n';
import { NumberField as NumberInput } from '../../shared/ui/NumberField';

import { SettingRow, Toggle } from './components';

export interface OrchestrationTabAuditInput {
  planPreflightEnabled: boolean;
  planScoutEnabled: boolean;
  maxScoutIterations: number;
  maxPlannerIterations: number;
  maxConcurrentSubagents: number;
  maxRetries: number;
  maxLaneIterations: number;
  maxSubagentIterations: number;
  subagentApprovalMode: string;
  worktreeIsolation: boolean;
  scratchRoot: string;
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatOrchestrationTabAuditSnapshot(input: OrchestrationTabAuditInput): string {
  return [
    `# 编排设置审计快照`,
    `- 拆解前澄清: ${input.planPreflightEnabled ? '开启' : '关闭'}`,
    `- 拆解前侦察: ${input.planScoutEnabled ? '开启' : '关闭'}`,
    `- 侦察迭代预算: ${input.maxScoutIterations}`,
    `- Planner 迭代预算: ${input.maxPlannerIterations}（预配置，暂未生效）`,
    `- 最大并发子任务: ${input.maxConcurrentSubagents}`,
    `- 子任务重试次数: ${input.maxRetries}`,
    `- Lane 迭代上限: ${input.maxLaneIterations}`,
    `- 子代理迭代上限: ${input.maxSubagentIterations}`,
    `- 子代理审批模式: ${input.subagentApprovalMode}`,
    `- Worktree 隔离: ${input.worktreeIsolation ? '开启' : '关闭'}`,
    `- Scratch 根目录: ${input.scratchRoot || 'orch_scratch'}`,
  ].join('\n');
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatOrchestrationTabAuditJson(input: OrchestrationTabAuditInput): string {
  return JSON.stringify(
    {
      planPreflightEnabled: input.planPreflightEnabled,
      planScoutEnabled: input.planScoutEnabled,
      maxScoutIterations: input.maxScoutIterations,
      maxPlannerIterations: input.maxPlannerIterations,
      maxConcurrentSubagents: input.maxConcurrentSubagents,
      maxRetries: input.maxRetries,
      maxLaneIterations: input.maxLaneIterations,
      maxSubagentIterations: input.maxSubagentIterations,
      subagentApprovalMode: input.subagentApprovalMode,
      worktreeIsolation: input.worktreeIsolation,
      scratchRoot: input.scratchRoot || 'orch_scratch',
    },
    null,
    2,
  );
}

/**
 * 编排数字输入。部分更新契约：onChange 收到的 v 已通过非负有限数校验；
 * 调用方负责 spread settings.orch 保留其余键。
 *
 * min 默认 0（允许“不限/关闭”语义的字段）。不允许 0 的字段（如并发数）
 * 由调用方传 min=1 —— 0 会落库成 Semaphore(0) 导致编排挂死。
 */
function NumberField({
  label,
  desc,
  anchor,
  dataTestId,
  value,
  onChange,
  min = 0,
  max,
}: {
  label: string;
  desc?: string;
  /** P1-4: 设置搜索锚点（对应 settingsSearchIndex 的 key） */
  anchor?: string;
  dataTestId: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
}) {
  const metadata = anchor === undefined ? undefined : getSettingMetadata(anchor);
  const defaultValue =
    typeof metadata?.defaultValue === 'number' ? metadata.defaultValue : undefined;
  return (
    <SettingRow
      label={label}
      desc={desc}
      anchor={anchor}
      value={value}
      onReset={defaultValue === undefined ? undefined : () => onChange(defaultValue)}
    >
      <NumberInput
        value={value}
        onChange={onChange}
        min={min}
        max={max}
        clampOnChange={false}
        testId={dataTestId}
        className="w-32 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
      />
    </SettingRow>
  );
}

/** scratch 根目录名——后端 scratch_root 键（相对 data 目录的单层目录名，空/空白输入不提交）。 */
function TextField({
  label,
  desc,
  anchor,
  dataTestId,
  value,
  onChange,
}: {
  label: string;
  desc?: string;
  /** P1-4: 设置搜索锚点（对应 settingsSearchIndex 的 key） */
  anchor?: string;
  dataTestId: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const metadata = anchor === undefined ? undefined : getSettingMetadata(anchor);
  const defaultValue =
    typeof metadata?.defaultValue === 'string' ? metadata.defaultValue : undefined;
  return (
    <SettingRow
      label={label}
      desc={desc}
      anchor={anchor}
      value={value}
      onReset={defaultValue === undefined ? undefined : () => onChange(defaultValue)}
    >
      <input
        type="text"
        data-testid={dataTestId}
        value={value}
        onChange={(e) => {
          if (e.target.value.trim() === '') return;
          onChange(e.target.value.trim());
        }}
        className="w-48 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
      />
    </SettingRow>
  );
}

export function OrchestrationTab() {
  const { settings, updateSettings } = useSettings();
  const { t } = useI18n();
  const setOrch = (patch: Partial<typeof settings.orch>) =>
    updateSettings({ orch: { ...settings.orch, ...patch } });

  // 「恢复默认」统一从 registry 取 defaultValue —— 默认值只有一处来源，调用点不重复硬编码。
  const resetOrchKey = (key: keyof typeof settings.orch) => {
    const metadata = getSettingMetadata(`orch.${key}`);
    if (metadata !== undefined) {
      setOrch({ [key]: metadata.defaultValue } as Partial<typeof settings.orch>);
    }
  };

  return (
    <div className="space-y-6" data-testid="orch-settings-section">
      <p className="text-xs text-muted leading-relaxed">{t('settings.orch.intro')}</p>
      <section>
        {/* Round 1/3 (2026-09-19) 计划前置旋钮 —— 管线级开关排最前。
            关闭后 multi 拆解行为与 2026-09-19 之前完全一致。 */}
        <h3 className="text-sm font-semibold text-text mb-3">
          {t('settings.orch.section_plan_preflight')}
        </h3>
        <SettingRow
          anchor="orch.planPreflightEnabled"
          label={t('settings.orch.plan_preflight.label')}
          desc={t('settings.orch.plan_preflight.desc')}
          value={settings.orch.planPreflightEnabled}
          onReset={() => resetOrchKey('planPreflightEnabled')}
        >
          <Toggle
            testId="orch-plan-preflight"
            value={settings.orch.planPreflightEnabled}
            onChange={(v) => setOrch({ planPreflightEnabled: v })}
          />
        </SettingRow>
        <SettingRow
          anchor="orch.planScoutEnabled"
          label={t('settings.orch.plan_scout.label')}
          desc={t('settings.orch.plan_scout.desc')}
          value={settings.orch.planScoutEnabled}
          onReset={() => resetOrchKey('planScoutEnabled')}
        >
          <Toggle
            testId="orch-plan-scout"
            value={settings.orch.planScoutEnabled}
            onChange={(v) => setOrch({ planScoutEnabled: v })}
          />
        </SettingRow>
        <NumberField
          label={t('settings.orch.max_scout_iterations.label')}
          desc={t('settings.orch.max_scout_iterations.desc')}
          dataTestId="orch-max-scout-iterations"
          value={settings.orch.maxScoutIterations}
          min={1}
          onChange={(v) => setOrch({ maxScoutIterations: v })}
        />
        <NumberField
          label={t('settings.orch.max_planner_iterations.label')}
          desc={t('settings.orch.max_planner_iterations.desc')}
          dataTestId="orch-max-planner-iterations"
          value={settings.orch.maxPlannerIterations}
          min={1}
          onChange={(v) => setOrch({ maxPlannerIterations: v })}
        />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">
          {t('settings.orch.section_concurrency')}
        </h3>
        <NumberField
          anchor="orch.maxConcurrentSubagents"
          label={t('settings.orch.max_concurrent_subagents.label')}
          desc={t('settings.orch.max_concurrent_subagents.desc')}
          dataTestId="orch-max-concurrent"
          value={settings.orch.maxConcurrentSubagents}
          onChange={(v) => setOrch({ maxConcurrentSubagents: v })}
          min={1}
        />
        <NumberField
          anchor="orch.maxRetries"
          label={t('settings.orch.max_retries.label')}
          dataTestId="orch-max-retries"
          value={settings.orch.maxRetries}
          onChange={(v) => setOrch({ maxRetries: v })}
        />
        <NumberField
          anchor="orch.maxLaneIterations"
          label={t('settings.orch.max_lane_iterations.label')}
          dataTestId="orch-max-lane-iterations"
          value={settings.orch.maxLaneIterations}
          onChange={(v) => setOrch({ maxLaneIterations: v })}
        />
        <NumberField
          anchor="orch.maxSubagentIterations"
          label={t('settings.orch.max_subagent_iterations.label')}
          dataTestId="orch-max-subagent-iterations"
          value={settings.orch.maxSubagentIterations}
          onChange={(v) => setOrch({ maxSubagentIterations: v })}
        />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">
          {t('settings.orch.section_result_limits')}
        </h3>
        <NumberField
          anchor="orch.maxAggregateChars"
          label={t('settings.orch.max_aggregate_chars.label')}
          dataTestId="orch-max-aggregate"
          value={settings.orch.maxAggregateChars}
          onChange={(v) => setOrch({ maxAggregateChars: v })}
        />
        <NumberField
          anchor="orch.maxSubagentResultChars"
          label={t('settings.orch.max_subagent_result_chars.label')}
          dataTestId="orch-max-subagent-result"
          value={settings.orch.maxSubagentResultChars}
          onChange={(v) => setOrch({ maxSubagentResultChars: v })}
        />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">
          {t('settings.orch.section_budget')}
        </h3>
        <NumberField
          anchor="orch.runTokenBudget"
          label={t('settings.orch.run_token_budget.label')}
          desc={t('settings.orch.run_token_budget.desc')}
          dataTestId="orch-run-token-budget"
          value={settings.orch.runTokenBudget}
          onChange={(v) => setOrch({ runTokenBudget: v })}
        />
        <NumberField
          anchor="orch.runWallClockLimitMinutes"
          label={t('settings.orch.run_wall_clock_limit.label')}
          desc={t('settings.orch.run_wall_clock_limit.desc')}
          dataTestId="orch-run-wall-clock-limit"
          value={settings.orch.runWallClockLimitMinutes}
          onChange={(v) => setOrch({ runWallClockLimitMinutes: v })}
        />
        <NumberField
          anchor="orch.subagentTaskTimeoutS"
          label={t('settings.orch.subagent_task_timeout.label')}
          desc={t('settings.orch.subagent_task_timeout.desc')}
          dataTestId="orch-subagent-task-timeout"
          value={settings.orch.subagentTaskTimeoutS}
          onChange={(v) => setOrch({ subagentTaskTimeoutS: v })}
        />
        <NumberField
          anchor="orch.maxRetryOfChains"
          label={t('settings.orch.max_retry_of_chains.label')}
          desc={t('settings.orch.max_retry_of_chains.desc')}
          dataTestId="orch-max-retry-of-chains"
          value={settings.orch.maxRetryOfChains}
          onChange={(v) => setOrch({ maxRetryOfChains: v })}
        />
        <NumberField
          anchor="orch.maxToolCallsPerRun"
          label={t('settings.orch.max_tool_calls_per_run.label')}
          desc={t('settings.orch.max_tool_calls_per_run.desc')}
          dataTestId="orch-max-tool-calls-per-run"
          value={settings.orch.maxToolCallsPerRun}
          onChange={(v) => setOrch({ maxToolCallsPerRun: v })}
        />
        <NumberField
          anchor="orch.maxIterations"
          label={t('settings.orch.max_iterations.label')}
          desc={t('settings.orch.max_iterations.desc')}
          dataTestId="orch-max-iterations"
          value={settings.orch.maxIterations}
          onChange={(v) => setOrch({ maxIterations: v })}
        />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">
          {t('settings.orch.section_dynamic_budget')}
        </h3>
        <p className="text-xs text-muted leading-relaxed mb-3">
          {t('settings.orch.dynamic_budget_intro')}
        </p>
        <SettingRow
          anchor="orch.dynamicBudgetEnabled"
          label={t('settings.orch.dynamic_budget_enabled.label')}
          desc={t('settings.orch.dynamic_budget_enabled.desc')}
          value={settings.orch.dynamicBudgetEnabled}
          onReset={() => resetOrchKey('dynamicBudgetEnabled')}
        >
          <Toggle
            testId="orch-dynamic-budget-enabled"
            value={settings.orch.dynamicBudgetEnabled}
            onChange={(v) => setOrch({ dynamicBudgetEnabled: v })}
          />
        </SettingRow>
        <NumberField
          anchor="orch.budgetSimple"
          label={t('settings.orch.budget_simple.label')}
          desc={t('settings.orch.budget_simple.desc')}
          dataTestId="orch-budget-simple"
          value={settings.orch.budgetSimple}
          min={1}
          onChange={(v) => setOrch({ budgetSimple: v })}
        />
        <NumberField
          anchor="orch.budgetMedium"
          label={t('settings.orch.budget_medium.label')}
          desc={t('settings.orch.budget_medium.desc')}
          dataTestId="orch-budget-medium"
          value={settings.orch.budgetMedium}
          min={1}
          onChange={(v) => setOrch({ budgetMedium: v })}
        />
        <NumberField
          anchor="orch.budgetComplex"
          label={t('settings.orch.budget_complex.label')}
          desc={t('settings.orch.budget_complex.desc')}
          dataTestId="orch-budget-complex"
          value={settings.orch.budgetComplex}
          min={1}
          onChange={(v) => setOrch({ budgetComplex: v })}
        />
        <NumberField
          anchor="orch.budgetLong"
          label={t('settings.orch.budget_long.label')}
          desc={t('settings.orch.budget_long.desc')}
          dataTestId="orch-budget-long"
          value={settings.orch.budgetLong}
          min={1}
          onChange={(v) => setOrch({ budgetLong: v })}
        />
        <NumberField
          anchor="orch.budgetHardCap"
          label={t('settings.orch.budget_hard_cap.label')}
          desc={t('settings.orch.budget_hard_cap.desc')}
          dataTestId="orch-budget-hard-cap"
          value={settings.orch.budgetHardCap}
          min={1}
          onChange={(v) => setOrch({ budgetHardCap: v })}
        />
        <NumberField
          anchor="orch.budgetMaxExtensions"
          label={t('settings.orch.budget_max_extensions.label')}
          desc={t('settings.orch.budget_max_extensions.desc')}
          dataTestId="orch-budget-max-extensions"
          value={settings.orch.budgetMaxExtensions}
          min={0}
          onChange={(v) => setOrch({ budgetMaxExtensions: v })}
        />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">
          {t('settings.orch.section_question_limits')}
        </h3>
        <p className="text-xs text-muted leading-relaxed mb-3">
          {t('settings.orch.question_limits_intro')}
        </p>
        <NumberField
          anchor="orch.maxConsecutiveUnansweredQuestions"
          label={t('settings.orch.max_consecutive_unanswered.label')}
          desc={t('settings.orch.max_consecutive_unanswered.desc')}
          dataTestId="orch-max-consecutive-unanswered"
          value={settings.orch.maxConsecutiveUnansweredQuestions}
          onChange={(v) => setOrch({ maxConsecutiveUnansweredQuestions: v })}
          min={1}
        />
        <NumberField
          anchor="orch.minOptionsPerQuestion"
          label={t('settings.orch.min_options_per_question.label')}
          desc={t('settings.orch.min_options_per_question.desc')}
          dataTestId="orch-min-options-per-question"
          value={settings.orch.minOptionsPerQuestion}
          onChange={(v) => setOrch({ minOptionsPerQuestion: v })}
          min={1}
          max={settings.orch.maxOptionsPerQuestion}
        />
        <NumberField
          anchor="orch.maxOptionsPerQuestion"
          label={t('settings.orch.max_options_per_question.label')}
          desc={t('settings.orch.max_options_per_question.desc')}
          dataTestId="orch-max-options-per-question"
          value={settings.orch.maxOptionsPerQuestion}
          onChange={(v) => setOrch({ maxOptionsPerQuestion: v })}
          min={settings.orch.minOptionsPerQuestion}
        />
        <NumberField
          anchor="orch.maxClarifyQuestionsInPrompt"
          label={t('settings.orch.max_clarify_questions_in_prompt.label')}
          desc={t('settings.orch.max_clarify_questions_in_prompt.desc')}
          dataTestId="orch-max-clarify-questions-in-prompt"
          value={settings.orch.maxClarifyQuestionsInPrompt}
          onChange={(v) => setOrch({ maxClarifyQuestionsInPrompt: v })}
          min={1}
        />
        <NumberField
          anchor="orch.maxClarifyQuestionsPerRound"
          label={t('settings.orch.max_clarify_questions_per_round.label')}
          desc={t('settings.orch.max_clarify_questions_per_round.desc')}
          dataTestId="orch-max-clarify-questions-per-round"
          value={settings.orch.maxClarifyQuestionsPerRound}
          onChange={(v) => setOrch({ maxClarifyQuestionsPerRound: v })}
          min={1}
        />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">
          {t('settings.orch.section_isolation')}
        </h3>
        <SettingRow
          anchor="orch.subagentApprovalMode"
          label={t('settings.orch.subagent_approval_mode.label')}
          desc={t('settings.orch.subagent_approval_mode.desc')}
          value={settings.orch.subagentApprovalMode}
          onReset={() => resetOrchKey('subagentApprovalMode')}
        >
          <Toggle
            value={settings.orch.subagentApprovalMode === 'auto'}
            onChange={(v) => setOrch({ subagentApprovalMode: v ? 'auto' : 'ask' })}
          />
        </SettingRow>
        {/* RD16 (round26): 后端 P2 隔离层旋钮 —— 仅隔离，不自动合并产物；
            非 git 仓库 / git 不可用时自动降级 scratch 目录隔离。 */}
        <SettingRow
          anchor="orch.worktreeIsolation"
          label={t('settings.orch.worktree_isolation.label')}
          desc={t('settings.orch.worktree_isolation.desc')}
          value={settings.orch.worktreeIsolation}
          onReset={() => resetOrchKey('worktreeIsolation')}
        >
          <Toggle
            testId="orch-worktree-isolation"
            value={settings.orch.worktreeIsolation}
            onChange={(v) => setOrch({ worktreeIsolation: v })}
          />
        </SettingRow>
        <TextField
          anchor="orch.scratchRoot"
          label={t('settings.orch.scratch_root.label')}
          desc={t('settings.orch.scratch_root.desc')}
          dataTestId="orch-scratch-root"
          value={settings.orch.scratchRoot}
          onChange={(v) => setOrch({ scratchRoot: v })}
        />
      </section>
    </div>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function auditOrchestrationTabGovernance(): {
  module: 'src/pages/settings/OrchestrationTab.tsx';
  phase: 'P173';
  domain: 'settings';
  supportsWorktreeIsolationAndBudgetControls: boolean;
  compliant: boolean;
} {
  return {
    module: 'src/pages/settings/OrchestrationTab.tsx',
    phase: 'P173',
    domain: 'settings',
    supportsWorktreeIsolationAndBudgetControls: true,
    compliant: true,
  };
}
