# Sage 设置治理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 统一 Sage 设置页的元数据、生效时机、分组、存储路由和契约测试，并补齐更新配置与关键高级设置。

**Architecture:** 保留现有 `app_settings`、preferences KV、Electron JSON 和 localStorage 的物理存储位置，以元数据注册表统一描述它们；设置 UI 通过共享的 metadata、ApplyModeBadge 和 AdvancedSection 呈现契约。先完成 P0 行为修复，再进行 Tab/搜索重构，最后引入兼容旧 API 的统一存储路由和完整契约测试。

**Tech Stack:** React 18 + TypeScript + Zustand + Vitest/Testing Library + Electron IPC + FastAPI preferences KV。

**Spec:** `docs/superpowers/specs/2026-09-19-settings-governance-design.md`

## Global Constraints

- 物理存储位置保持兼容：不迁移既有用户配置，不删除现有 IPC/API。
- 所有新增用户文案先提供中文；已有 i18n key 保持兼容，不在本批次强行重写全部英文翻译。
- 前端输入校验不能替代后端校验；涉及安全、路径、URL、权限的值必须双层校验。
- API Key、Token、Cookie 和主密钥不得进入搜索索引、设置摘要、导出文件或普通日志。
- `maxConcurrentSubagents` 必须始终大于 0；其他允许 0 的字段必须明确标注“0 = 不限”。
- 设置保存失败必须对用户可见，不能只保留乐观本地状态。
- 每个任务完成后运行该任务列出的测试，再进行一次针对性 code review。

## 文件地图

- `src/entities/setting/metadata.ts`: 元数据类型、枚举和标签配置。
- `src/entities/setting/settingsRegistry.ts`: 全部可见/内部设置项注册表及查询函数。
- `src/entities/setting/settingsValidation.ts`: 统一约束验证和错误格式化。
- `src/pages/settings/components.tsx`: `ApplyModeBadge`、`AdvancedSection` 等共享 UI。
- `src/pages/settings/settingsSearchIndex.ts`: 从注册表派生搜索条目和目标定位信息。
- `src/pages/settings/Settings.tsx`: 主导航、搜索跳转和新分组 Tab。
- `src/pages/settings/GeneralTab.tsx`: 保留兼容入口，拆出基础内容。
- `src/pages/settings/BasicTab.tsx`: 外观、语言、时区、对话行为和托盘。
- `src/pages/settings/MemoryKnowledgeTab.tsx`: 记忆、嵌入、附件 RAG、上下文高级设置。
- `src/pages/settings/ToolsConnectionsTab.tsx`: MCP、Hooks、网关、网站凭据和工具权限入口。
- `src/pages/settings/OrchestrationTab.tsx`: 编排基础/高级折叠和输入约束。
- `src/pages/settings/UpdatesTab.tsx`: 8 个更新配置、基础/高级折叠和保存反馈。
- `src/shared/api/settingsClient.ts`: 保持现有 API，并增加 metadata 驱动的统一读写适配器。
- `src/entities/setting/storage.ts`: 统一适配器接入和失败状态处理。
- `src/pages/settings/__tests__/settingsRegistry.test.ts`: 注册表契约测试。
- `src/pages/settings/__tests__/UpdatesTab.test.tsx`: 更新页行为测试。
- `src/pages/settings/__tests__/OrchestrationTab.test.tsx`: 编排边界测试。
- `src/pages/settings/__tests__/Settings.test.tsx`: 搜索定位、折叠和导航测试。
- `docs/user-manual/18-settings.md`: 用户设置说明和生效时机表。

### Task 1: 完成元数据注册表和运行时验证

**Files:**
- Create: `src/entities/setting/metadata.ts`
- Create: `src/entities/setting/settingsRegistry.ts`
- Create: `src/entities/setting/settingsValidation.ts`
- Create: `src/pages/settings/__tests__/settingsRegistry.test.ts`
- Modify: `src/entities/setting/types.ts:122-255`

**Interfaces:**
- Produces `SettingMetadata`, `settingsRegistry`, `getSettingMetadata(key)`, `getSettingsByVisibility(visibility)`。
- Produces `validateSettingValue(key, value): string | null`。
- Registry keys for nested values use stable keys such as `orch.maxConcurrentSubagents` and `updates.rollbackWindowDays`。

- [ ] **Step 1: Write failing contract tests**

```ts
it('registers every public setting with storage and apply metadata', () => {
  const publicSettings = Object.values(settingsRegistry).filter(
    (item) => item.visibility !== 'internal',
  );
  expect(publicSettings.length).toBeGreaterThan(30);
  for (const item of publicSettings) {
    expect(item.key).toBeTruthy();
    expect(item.description).toBeTruthy();
    expect(item.defaultValue).not.toBeUndefined();
    expect(item.storage).toMatch(/^(app_settings|preference|electron|local)$/);
  }
});

it('rejects zero concurrent subagents', () => {
  expect(validateSettingValue('orch.maxConcurrentSubagents', 0)).toContain('大于 0');
  expect(validateSettingValue('orch.maxConcurrentSubagents', 1)).toBeNull();
});

it('includes all update config fields', () => {
  expect(Object.keys(settingsRegistry)).toEqual(expect.arrayContaining([
    'updates.updateStrategy', 'updates.channel',
    'updates.rollbackWindowDays', 'updates.autoRollbackThreshold',
    'updates.checkIntervalHours', 'updates.updateServerUrl',
    'updates.enableTelemetry', 'updates.cacheRetentionDays',
  ]));
});
```

- [ ] **Step 2: Run the contract test and verify RED**

Run: `npm exec vitest run src/pages/settings/__tests__/settingsRegistry.test.ts`
Expected: FAIL because the validation helper and complete registry contract are not wired.

- [ ] **Step 3: Implement metadata and validation**

Implement `SettingMetadata` with `scope`, `storage`, `storageKey`, `defaultValue`, `applyMode`, `visibility`, `riskLevel`, constraints, and optional validator. Keep registry defaults aligned with `DEFAULT_SETTINGS`, `SettingsRepository.KEYS`, and `electron/updateConfig.ts`. Implement generic number/enum/string validation plus the explicit concurrent-subagent validator.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `npm exec vitest run src/pages/settings/__tests__/settingsRegistry.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/entities/setting src/pages/settings/__tests__/settingsRegistry.test.ts
git commit -m "feat: add settings metadata registry"
```

### Task 2: Add shared apply-mode and advanced-section UI

**Files:**
- Modify: `src/pages/settings/components.tsx`
- Create: `src/pages/settings/__tests__/components.test.tsx`
- Modify: `src/entities/setting/metadata.ts`

**Interfaces:**
- Produces `ApplyModeBadge({ mode, compact? })`.
- Produces `AdvancedSection({ title, description?, defaultOpen?, children })`.
- Components must expose `data-testid="setting-apply-mode-${mode}"` and `data-testid="settings-advanced-section"`.

- [ ] **Step 1: Write failing component tests**

```tsx
it('renders the Chinese apply-mode label', () => {
  render(<ApplyModeBadge mode="next-run" />);
  expect(screen.getByText('下次 Run')).toBeInTheDocument();
});

it('keeps advanced content collapsed by default', () => {
  render(<AdvancedSection title="高级设置"><div>secret controls</div></AdvancedSection>);
  expect(screen.queryByText('secret controls')).not.toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: /高级设置/ }));
  expect(screen.getByText('secret controls')).toBeVisible();
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `npm exec vitest run src/pages/settings/__tests__/components.test.tsx`
Expected: FAIL because components do not exist.

- [ ] **Step 3: Implement accessible components**

Use a button with `aria-expanded` and a stable content region for `AdvancedSection`. Use metadata label/color classes without introducing a new color system. Ensure keyboard activation works and no text overflows compact setting rows.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `npm exec vitest run src/pages/settings/__tests__/components.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pages/settings/components.tsx src/pages/settings/__tests__/components.test.tsx src/entities/setting/metadata.ts
git commit -m "feat: add settings apply and advanced controls"
```

### Task 3: Fix P0 model and orchestration semantics

**Files:**
- Modify: `src/pages/settings/ModelsTab.tsx:120-175`
- Modify: `src/pages/settings/OrchestrationTab.tsx:20-80`
- Modify: `src/entities/setting/settingsRegistry.ts`
- Modify: `src/pages/settings/__tests__/ModelsTab.test.tsx`
- Modify: `src/pages/settings/__tests__/OrchestrationTab.test.tsx`

**Interfaces:**
- `maxContext` is disabled while `autoContext` is true and shows the effective catalog value when available.
- Numeric orchestration fields use per-field minimums, especially `maxConcurrentSubagents >= 1`.

- [ ] **Step 1: Add failing tests**

```tsx
it('disables fixed context input in automatic mode', () => {
  renderModels({ autoContext: true, maxContext: 4096 });
  expect(screen.getByTestId('max-context-input')).toBeDisabled();
});

it('does not persist zero concurrent subagents', () => {
  renderOrchestration({ maxConcurrentSubagents: 4 });
  fireEvent.change(screen.getByTestId('orch-max-concurrent'), { target: { value: '0' } });
  expect(updateSettings).not.toHaveBeenCalledWith(expect.objectContaining({
    orch: expect.objectContaining({ maxConcurrentSubagents: 0 }),
  }));
});
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `npm exec vitest run src/pages/settings/__tests__/ModelsTab.test.tsx src/pages/settings/__tests__/OrchestrationTab.test.tsx`
Expected: FAIL with the current always-enabled context input or zero acceptance.

- [ ] **Step 3: Implement bounded controls and accurate copy**

Add a stable test id to the context input, disable it when automatic mode is on, show the effective window if the model catalog provides one, and change Temperature copy to describe the full `0-2` range. Add a `min` prop to `NumberField`; pass `1` to concurrency and `0` only to fields where unlimited is intentional.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `npm exec vitest run src/pages/settings/__tests__/ModelsTab.test.tsx src/pages/settings/__tests__/OrchestrationTab.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pages/settings/ModelsTab.tsx src/pages/settings/OrchestrationTab.tsx src/entities/setting/settingsRegistry.ts src/pages/settings/__tests__
git commit -m "fix: clarify model and orchestration setting bounds"
```

### Task 4: Add update configuration controls

**Files:**
- Modify: `src/pages/settings/UpdatesTab.tsx`
- Modify: `electron/updateIpc.ts:50-100`
- Modify: `electron/updateManager.ts:660-700`
- Modify: `src/pages/settings/__tests__/UpdatesTab.test.tsx`
- Modify: `electron/tests/updateIpc.test.ts`

**Interfaces:**
- Add IPC methods `updates.setConfigPatch(patch: Partial<UpdateConfig>): Promise<UpdateConfig>` while retaining `setStrategy` and `setChannel` compatibility.
- UpdatesTab renders all eight `UpdateConfig` fields, with advanced fields inside `AdvancedSection`.

- [ ] **Step 1: Write failing renderer and IPC tests**

```tsx
it('renders rollback, schedule, privacy, and cache controls', async () => {
  render(<UpdatesTab />);
  expect(await screen.findByTestId('updates-rollback-window')).toBeInTheDocument();
  expect(screen.getByTestId('updates-check-interval')).toBeInTheDocument();
  expect(screen.getByTestId('updates-telemetry')).toBeInTheDocument();
});
```

```ts
it('persists a validated update config patch', async () => {
  await updateManager.setConfigPatch({ checkIntervalHours: 12 });
  expect((await configManager.getConfig()).checkIntervalHours).toBe(12);
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `npm exec vitest run src/pages/settings/__tests__/UpdatesTab.test.tsx electron/tests/updateIpc.test.ts`
Expected: FAIL because the controls and patch method are absent.

- [ ] **Step 3: Implement validated partial update IPC**

Add a main-process method that reads the current validated config, merges the patch, calls `ConfigManager.setConfig`, and returns the resulting config. Reuse `ConfigManager.validateConfig`; do not create a second URL or numeric validator. Expose the method through preload and the typed Electron API.

- [ ] **Step 4: Implement the advanced update UI**

Use number inputs with explicit bounds, a HTTPS-only server URL field, telemetry toggle, cache retention field, and explanatory apply-mode labels. Show an inline error if IPC rejects the patch. Keep “check now” transient and do not persist its result as a setting.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `npm exec vitest run src/pages/settings/__tests__/UpdatesTab.test.tsx electron/tests/updateIpc.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/pages/settings/UpdatesTab.tsx src/pages/settings/__tests__/UpdatesTab.test.tsx electron/updateIpc.ts electron/updateManager.ts electron/preload.ts electron/tests/updateIpc.test.ts
git commit -m "feat: expose complete update configuration"
```

### Task 5: Add gateway restart-required feedback and save errors

**Files:**
- Modify: `src/widgets/settings/GatewayCard.tsx`
- Modify: `src/shared/api/settingsClient.ts`
- Modify: `src/entities/setting/storage.ts`
- Modify: `src/widgets/settings/__tests__/GatewayCard.test.tsx`

**Interfaces:**
- Gateway save displays `restart_required` returned by `gatewayApi.updateConfig`.
- Settings persistence rejects on backend failure instead of silently treating a failed write as success; local optimistic state is marked stale or rolled back.

- [ ] **Step 1: Write failing tests**

```tsx
it('shows restart-required feedback after gateway save', async () => {
  gatewayApi.updateConfig.mockResolvedValue({ ok: true, restart_required: true });
  render(<GatewayCard platform="telegram" />);
  await saveGatewayForm();
  expect(screen.getByText(/重启后端/)).toBeInTheDocument();
});
```

```ts
it('surfaces failed preference persistence', async () => {
  mockInvoke.mockRejectedValueOnce(new Error('backend unavailable'));
  await expect(settingsClient.setPreference('permission_mode', 'prompt')).rejects.toThrow(
    'backend unavailable',
  );
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `npm exec vitest run src/widgets/settings/__tests__/GatewayCard.test.tsx src/entities/setting/__tests__/storage.test.ts`
Expected: FAIL because restart feedback and rejected persistence are not asserted/implemented.

- [ ] **Step 3: Implement visible save status**

Render three explicit states: saved, saved-but-restart-required, and failed. Preserve token masking behavior. For settings persistence, keep the synchronous local cache but reject the returned promise when the remote write fails; callers can show the error without breaking local boot fallback.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `npm exec vitest run src/widgets/settings/__tests__/GatewayCard.test.tsx src/entities/setting/__tests__/storage.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/widgets/settings/GatewayCard.tsx src/shared/api/settingsClient.ts src/entities/setting/storage.ts src/widgets/settings/__tests__
git commit -m "fix: report settings persistence and gateway restart status"
```

### Task 6: Split the overloaded General tab into stable user-facing groups

**Files:**
- Create: `src/pages/settings/BasicTab.tsx`
- Create: `src/pages/settings/MemoryKnowledgeTab.tsx`
- Create: `src/pages/settings/ToolsConnectionsTab.tsx`
- Modify: `src/pages/settings/GeneralTab.tsx`
- Modify: `src/pages/settings/Settings.tsx`
- Modify: `src/pages/settings/settingsSearchIndex.ts`
- Modify: `src/pages/settings/__tests__/Settings.test.tsx`

**Interfaces:**
- Existing deep links and `general` localStorage values remain valid; `general` resolves to the new Basic tab.
- New tab keys are `basic`, `memory-knowledge`, and `tools-connections`.
- Existing `MemoryTab`, `McpTab`, and `NetworkTab` remain available during migration; wrappers must not duplicate API writes.

- [ ] **Step 1: Add failing navigation tests**

```tsx
it('routes basic, memory, and tools search results to the new groups', () => {
  render(<Settings />);
  search('自动记忆');
  expect(screen.getByTestId('settings-search-item-autoMemory')).toHaveTextContent('记忆与知识');
  search('主题');
  expect(screen.getByTestId('settings-search-item-theme')).toHaveTextContent('基础');
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `npm exec vitest run src/pages/settings/__tests__/Settings.test.tsx`
Expected: FAIL because the new navigation groups do not exist.

- [ ] **Step 3: Extract components without changing persistence**

Move only rendering and event wiring. Keep `useSettings`, `settingsClient`, `gatewayApi`, `mcpClient`, and `network` APIs in their existing owners. `GeneralTab` becomes a compatibility wrapper rendering `BasicTab` and links to the new groups rather than owning a second copy of the controls.

- [ ] **Step 4: Add AdvancedSection around dense controls**

Default-collapse orchestration result limits, retry chains, Scratch/Worktree, topic detection, Bash configuration, diagnostics, and update security/privacy controls. Keep security-critical permission/network controls visible with concise warnings.

- [ ] **Step 5: Run focused and existing settings tests**

Run: `npm exec vitest run src/pages/settings/__tests__ src/widgets/settings/__tests__`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/pages/settings src/widgets/settings/__tests__
git commit -m "refactor: organize settings into user-facing groups"
```

### Task 7: Make settings search metadata-driven and target-specific

**Files:**
- Modify: `src/pages/settings/settingsSearchIndex.ts`
- Modify: `src/pages/settings/Settings.tsx`
- Modify: setting controls to add `data-setting-key` attributes
- Modify: `src/pages/settings/__tests__/Settings.test.tsx`

**Interfaces:**
- `SettingsSearchEntry` gains `settingKey` and optional `targetId`.
- `jumpToItem(entry)` changes tab, clears query, then scrolls `document.querySelector([data-setting-key="..."])` into view and applies a short highlight class.

- [ ] **Step 1: Write failing target-location test**

```tsx
it('scrolls the selected setting into view', () => {
  const scrollIntoView = vi.fn();
  HTMLElement.prototype.scrollIntoView = scrollIntoView;
  render(<Settings />);
  search('最大并发子任务数');
  fireEvent.click(screen.getByTestId('settings-search-item-orch.maxConcurrentSubagents'));
  expect(scrollIntoView).toHaveBeenCalled();
});
```

- [ ] **Step 2: Run test and verify RED**

Run: `npm exec vitest run src/pages/settings/__tests__/Settings.test.tsx`
Expected: FAIL because search entries only identify Tabs.

- [ ] **Step 3: Generate entries from registry**

Retain hand-authored category aliases where needed, but derive key, label, description, visibility and apply mode from `settingsRegistry`. Exclude `internal` entries and secrets. Add `data-setting-key` to controls and implement target scrolling/highlighting with a timeout cleanup.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `npm exec vitest run src/pages/settings/__tests__/Settings.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pages/settings
 git commit -m "feat: target individual settings from search"
```

### Task 8: Introduce metadata-driven storage routing and status feedback

**Files:**
- Modify: `src/shared/api/settingsClient.ts`
- Modify: `src/entities/setting/storage.ts`
- Create: `src/entities/setting/settingsAdapter.ts`
- Create: `src/entities/setting/__tests__/settingsAdapter.test.ts`
- Modify: existing settings callers incrementally

**Interfaces:**
- `readSetting<T>(key: string): Promise<T | null>`
- `writeSetting<T>(key: string, value: T): Promise<void>`
- `resetSetting(key: string): Promise<void>`
- Adapter routes by metadata storage backend while preserving existing `getPreference`, `setPreference`, `loadSettings`, and Electron IPC methods.

- [ ] **Step 1: Write adapter routing tests**

```ts
it('routes preference metadata to KV APIs', async () => {
  await writeSetting('permission_mode', 'prompt');
  expect(mockSetPreference).toHaveBeenCalledWith('permission_mode', 'prompt', expect.any(String));
});

it('routes Electron metadata to update IPC', async () => {
  await writeSetting('updates.channel', 'beta');
  expect(mockSetUpdateConfig).toHaveBeenCalledWith({ channel: 'beta' });
});
```

- [ ] **Step 2: Run tests and verify RED**

Run: `npm exec vitest run src/entities/setting/__tests__/settingsAdapter.test.ts`
Expected: FAIL because the adapter does not exist.

- [ ] **Step 3: Implement storage routing**

Use `storageKey` for nested app settings and Electron field mapping. Reject unknown/internal keys and validator failures before writes. Return the original underlying error so UI can show actionable feedback. Do not move credentials or change backend whitelist behavior.

- [ ] **Step 4: Migrate only settings-page callers**

Migrate General, Network, Orchestration, and Updates controls one group at a time. Leave unrelated API consumers unchanged. Verify each migration preserves category arguments and secret masking.

- [ ] **Step 5: Run adapter and settings tests**

Run: `npm exec vitest run src/entities/setting/__tests__ src/pages/settings/__tests__ src/widgets/settings/__tests__`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/shared/api/settingsClient.ts src/entities/setting src/pages/settings src/widgets/settings
 git commit -m "refactor: route settings through metadata adapter"
```

### Task 9: Add complete settings contract and documentation coverage

**Files:**
- Create: `src/entities/setting/__tests__/settingsContract.test.ts`
- Modify: `src/pages/settings/__tests__/settingsRegistry.test.ts`
- Create: `docs/user-manual/18-settings.md`
- Modify: `docs/user-manual/README.md`

**Interfaces:**
- Contract tests compare registry keys with `DEFAULT_SETTINGS`, update config fields, and the documented preference whitelist.
- Documentation describes storage-independent behavior and apply modes without exposing secrets.

- [ ] **Step 1: Add contract assertions**

```ts
it('keeps update registry fields aligned with UpdateConfig', () => {
  const configFields = [
    'updateStrategy', 'channel', 'rollbackWindowDays',
    'autoRollbackThreshold', 'checkIntervalHours', 'updateServerUrl',
    'enableTelemetry', 'cacheRetentionDays',
  ];
  expect(configFields.map((field) => `updates.${field}`)).toEqual(
    expect.arrayContaining(Object.keys(settingsRegistry).filter((key) => key.startsWith('updates.'))),
  );
});

it('does not expose internal credentials in searchable metadata', () => {
  expect(SETTINGS_SEARCH_INDEX.some((entry) => /api.?key|token|secret/i.test(entry.label))).toBe(false);
});
```

- [ ] **Step 2: Run contract tests and fix drift**

Run: `npm exec vitest run src/entities/setting/__tests__/settingsContract.test.ts src/pages/settings/__tests__/settingsRegistry.test.ts`
Expected: PASS with no registry/default/storage drift.

- [ ] **Step 3: Document the settings groups**

Write the user manual with a table containing setting group, default, apply mode, and warning. Explicitly document: auto versus manual context, gateway restart status, update rollback/privacy controls, and reset exclusions.

- [ ] **Step 4: Run the complete frontend validation**

Run: `npm run build` and `npm exec vitest run src/pages/settings src/entities/setting src/widgets/settings`
Expected: build succeeds and all focused settings tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/entities/setting/__tests__ src/pages/settings/__tests__ docs/user-manual
 git commit -m "test: enforce settings contracts and document behavior"
```

## Final Verification Checklist

- [ ] `npm run build` succeeds.
- [ ] All focused settings tests pass.
- [ ] Electron update tests pass.
- [ ] No `console.log` added in modified production files.
- [ ] No credentials appear in registry labels, search entries, summaries, or docs.
- [ ] `git diff --check` succeeds.
- [ ] Run `git status --short` and verify unrelated pre-existing changes were not modified.
- [ ] Run code review on the complete diff before declaring completion.
