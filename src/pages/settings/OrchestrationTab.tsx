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

import { useSettings } from '../../features/manage-settings/useSettings';

import { SettingRow, Toggle } from './components';

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
  dataTestId,
  value,
  onChange,
  min = 0,
  max,
}: {
  label: string;
  desc?: string;
  dataTestId: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
}) {
  return (
    <SettingRow label={label} desc={desc}>
      <input
        type="number"
        data-testid={dataTestId}
        min={min}
        max={max}
        value={value}
        onChange={(e) => {
          // 空输入 = 不修改：Number('') === 0 会经 n >= min 守卫提交 0，
          // 落库后 load_orch_settings() 读到 0 → asyncio.Semaphore(0) → 编排挂死。
          if (e.target.value === '') return;
          const n = Number(e.target.value);
          if (Number.isFinite(n) && n >= min && (max === undefined || n <= max)) {
            onChange(Math.floor(n));
          }
        }}
        className="w-32 px-2 py-1 text-xs border border-border rounded-radius-sm bg-bg text-text focus:outline-none focus:border-primary"
      />
    </SettingRow>
  );
}

/** scratch 根目录名——后端 scratch_root 键（相对 data 目录的单层目录名，空/空白输入不提交）。 */
function TextField({
  label,
  desc,
  dataTestId,
  value,
  onChange,
}: {
  label: string;
  desc?: string;
  dataTestId: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <SettingRow label={label} desc={desc}>
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
  const setOrch = (patch: Partial<typeof settings.orch>) =>
    updateSettings({ orch: { ...settings.orch, ...patch } });

  return (
    <div className="space-y-6" data-testid="orch-settings-section">
      <p className="text-xs text-muted leading-relaxed">
        编排器派发子代理的执行参数（orch 段）。修改即保存并生效于新发起的 run；预算与守门项设 0
        表示不限制，请谨慎放开。
      </p>
      <section>
        {/* Round 1/3 (2026-09-19) 计划前置旋钮 —— 管线级开关排最前。
            关闭后 multi 拆解行为与 2026-09-19 之前完全一致。 */}
        <h3 className="text-sm font-semibold text-text mb-3">计划前置</h3>
        <SettingRow
          label="拆解前澄清需求"
          desc="复杂任务进入编排前,先判断目标是否有歧义并向你提问(≤3 问);超时或跳过则按合理默认值执行并在计划中写明假设"
        >
          <Toggle
            testId="orch-plan-preflight"
            value={settings.orch.planPreflightEnabled}
            onChange={(v) => setOrch({ planPreflightEnabled: v })}
          />
        </SettingRow>
        <SettingRow
          label="拆解前事实侦察"
          desc="拆解任务前派一个只读子代理快速收集工作区/网络/记忆事实,作为计划依据;会增加少量等待时间"
        >
          <Toggle
            testId="orch-plan-scout"
            value={settings.orch.planScoutEnabled}
            onChange={(v) => setOrch({ planScoutEnabled: v })}
          />
        </SettingRow>
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">并发与迭代</h3>
        <NumberField
          label="最大并发子任务数"
          desc="必须大于 0；设 0 会让编排信号量归零并挂死"
          dataTestId="orch-max-concurrent"
          value={settings.orch.maxConcurrentSubagents}
          onChange={(v) => setOrch({ maxConcurrentSubagents: v })}
          min={1}
        />
        <NumberField
          label="子任务重试次数"
          dataTestId="orch-max-retries"
          value={settings.orch.maxRetries}
          onChange={(v) => setOrch({ maxRetries: v })}
        />
        <NumberField
          label="Lane 迭代上限"
          dataTestId="orch-max-lane-iterations"
          value={settings.orch.maxLaneIterations}
          onChange={(v) => setOrch({ maxLaneIterations: v })}
        />
        <NumberField
          label="子代理迭代上限"
          dataTestId="orch-max-subagent-iterations"
          value={settings.orch.maxSubagentIterations}
          onChange={(v) => setOrch({ maxSubagentIterations: v })}
        />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">结果上限</h3>
        <NumberField
          label="聚合结果上限（字符）"
          dataTestId="orch-max-aggregate"
          value={settings.orch.maxAggregateChars}
          onChange={(v) => setOrch({ maxAggregateChars: v })}
        />
        <NumberField
          label="单结果截断上限（字符）"
          dataTestId="orch-max-subagent-result"
          value={settings.orch.maxSubagentResultChars}
          onChange={(v) => setOrch({ maxSubagentResultChars: v })}
        />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">预算与守门</h3>
        <NumberField
          label="Run token 预算（tokens，0=不限）"
          desc="单个 run 累计 total_tokens 上限，触顶后剩余任务收口归因 budget_exceeded"
          dataTestId="orch-run-token-budget"
          value={settings.orch.runTokenBudget}
          onChange={(v) => setOrch({ runTokenBudget: v })}
        />
        <NumberField
          label="Run 墙钟上限（分钟，0=不限）"
          desc="单个 run 的最长挂钟时间，超限后剩余任务经 run 级取消通道收口"
          dataTestId="orch-run-wall-clock-limit"
          value={settings.orch.runWallClockLimitMinutes}
          onChange={(v) => setOrch({ runWallClockLimitMinutes: v })}
        />
        <NumberField
          label="单子任务超时（秒，0=不限）"
          desc="子任务挂钟超时，防止卡死任务占住并发信号量"
          dataTestId="orch-subagent-task-timeout"
          value={settings.orch.subagentTaskTimeoutS}
          onChange={(v) => setOrch({ subagentTaskTimeoutS: v })}
        />
        <NumberField
          label="重派链上限（次）"
          desc="每 run retry_of 链式重派上限，防止误判时无限重派；超限降级普通任务"
          dataTestId="orch-max-retry-of-chains"
          value={settings.orch.maxRetryOfChains}
          onChange={(v) => setOrch({ maxRetryOfChains: v })}
        />
      </section>
      <section>
        <h3 className="text-sm font-semibold text-text mb-3">隔离与审批</h3>
        <SettingRow
          label="子代理自动批准非危险工具"
          desc="编排子代理遇到需审批的工具时,自动放行非危险调用;破坏性/可疑命令与工作区越界仍弹窗确认"
        >
          <Toggle
            value={settings.orch.subagentApprovalMode === 'auto'}
            onChange={(v) => setOrch({ subagentApprovalMode: v ? 'auto' : 'ask' })}
          />
        </SettingRow>
        {/* RD16 (round26): 后端 P2 隔离层旋钮 —— 仅隔离，不自动合并产物；
            非 git 仓库 / git 不可用时自动降级 scratch 目录隔离。 */}
        <SettingRow
          label="子任务 git worktree 隔离"
          desc="会话绑定 git 仓库时,每个子任务在临时 worktree 副本中工作(仅文件系统隔离,产物不自动合并回主工作区);非仓库或 git 失败自动降级"
        >
          <Toggle
            testId="orch-worktree-isolation"
            value={settings.orch.worktreeIsolation}
            onChange={(v) => setOrch({ worktreeIsolation: v })}
          />
        </SettingRow>
        <TextField
          label="Scratch 根目录名（data 目录下）"
          desc="仅限单层目录名；绝对路径、含 / 或 .. 的输入会被后端拒绝并回落默认"
          dataTestId="orch-scratch-root"
          value={settings.orch.scratchRoot}
          onChange={(v) => setOrch({ scratchRoot: v })}
        />
      </section>
    </div>
  );
}
