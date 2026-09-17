# Font Customization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 General > 外观中提供 UI/代码字体族与 10–24px 字体大小的即时、持久化配置。

**Architecture:** `FontProvider` 在 AppProviders 中提供唯一共享状态，启动时从 preference KV（失败时 localStorage）加载并将合法值映射为 document 根 CSS 变量；设置页通过 `useFontSettings` 消费上下文。Tailwind 字号使用 CSS 变量比例而非改变 html 根字号，以免影响布局 spacing。

**Tech Stack:** React 18, TypeScript, Tailwind CSS, Vitest, Python 3.10 backend (settings whitelist).

**Spec:** `docs/superpowers/specs/2026-09-15-font-customization-design.md`（实施时以本计划的校正为准：不改变 html font-size；Tailwind 字号明确映射变量）。

## Global Constraints

- 字体仅使用系统字体 fallback，不新增字体包或远程字体。
- UI 与代码字体独立；合法字体 ID 只能来自选项常量。
- 字号为整数，范围 10–24px；无效/缺失 preference 回退默认值。
- 不修改 `html` 的 `font-size`，避免改变 rem-based spacing/layout。
- release/win7 分支不参与本功能；实现基于 main，保持 Python 3.10 环境。
- 不提交 secrets；后端测试使用 `/home/fz/anaconda3/envs/sage-backend/bin/python`。

## File Map

- Create: `src/entities/font/fontOptions.ts` — UI/code font option IDs, stacks, labels, defaults, validation.
- Create: `src/entities/font/fontStorage.ts` — preference/localStorage load/save and input normalization.
- Create: `src/entities/font/useFontSettings.ts` — FontContext/FontProvider/useFontSettings shared state and CSS application.
- Create: `src/entities/font/__tests__/fontStorage.test.ts` — persistence and normalization tests.
- Create: `src/entities/font/__tests__/useFontSettings.test.tsx` — provider CSS/state behavior tests.
- Modify: `src/shared/api/settingsClient.ts:23-37` — add four preference keys.
- Modify: `backend/data/settings_repo.py:18-63` — whitelist four keys.
- Modify: `src/index.css:18-190,450-465` — default typography CSS variables and code font variable.
- Modify: `tailwind.config.js:65-69` — variable-backed families and UI-relative font-size tokens (`text-xs`, `text-sm`, etc.).
- Modify: `src/app/providers/AppProviders.tsx:9-47` — mount FontProvider once inside ThemeProvider.
- Modify: `src/pages/settings/GeneralTab.tsx:382-401` — render font controls in appearance section.
- Modify: `src/widgets/system/BackendStatusBanner.css:1-12` — replace fixed 14px with UI variable if this style is intentionally UI text.
- Modify: `src/pages/settings/__tests__/GeneralTab.test.tsx` — add control rendering and update behavior tests.

## Task 1: Preference Contract and Pure Font Definitions

**Files:** modify settings client/backend; create `fontOptions.ts`, `fontStorage.ts` tests.

- [ ] Write tests first for all five option IDs, defaults, `normalizeFontSize` clamping/flooring, invalid ID fallback, and storage remote/local fallback.
- [ ] Run `npm test -- src/entities/font/__tests__/fontStorage.test.ts` and observe expected missing-module failures.
- [ ] Implement `FontSettings`, `FontFamilyId`, `FontOption`, `FONT_DEFAULTS`, `UI_FONT_OPTIONS`, `CODE_FONT_OPTIONS`, and pure `normalizeFontSettings`.
- [ ] Implement keys `font_ui`, `font_code`, `font_size_ui`, `font_size_code` in `PreferenceKey` and `SettingsRepository.KEYS`.
- [ ] Implement storage constants `sage-font-settings`, serialization of numbers as strings, remote-first load with local fallback, and local cache update only after valid values are normalized.
- [ ] Run focused tests and backend whitelist test using `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest ...`; expected PASS.
- [ ] Commit `feat: add font preference definitions`.

## Task 2: Shared Provider and CSS Application

**Files:** create `useFontSettings.tsx` and tests; modify `AppProviders.tsx`, `index.css`, `tailwind.config.js`.

- [x] Write failing provider tests that mount `FontProvider`, await remote values, assert CSS properties, update one field without changing the other, reset defaults, and ignore stale initial load after a user update.
- [x] Run the focused Vitest file and confirm failure because provider is absent.
- [x] Implement `FontProvider` with one context state, cancellation/version guard for async initialization, CSS variable application (`--font-ui`, `--font-code`, `--font-size-ui`, `--font-size-code`), and serialized async loads and saves.
- [x] Mount provider once in `AppProviders`; direct hook/provider imports used.
- [x] Add root defaults in `:root`, body `font-family: var(--font-ui)` and `font-size: var(--font-size-ui)`, and code block variables. Replace only typography hardcodes; do not add global selectors.
- [x] Configure Tailwind families and each relevant font-size token using `calc(var(--font-size-ui) * ratio)` so defaults preserve current sizes; keep layout spacing unchanged.
- [x] Run provider tests and typecheck; PASS.
- [ ] Commit `feat: apply shared font preferences`.

## Task 3: Settings Controls

**Files:** modify `GeneralTab.tsx` and its tests.

- [x] Write failing tests asserting UI font/code font selects have accessible labels, 10/24 bounds, current values, reset control, and updates call shared provider state.
- [x] Run focused tests and observe failures for missing controls.
- [x] Add a compact `FontSettingsSection` using existing `SettingRow`, native select with option preview style, range input paired with integer number input, explicit min/max/step, and reset button; show fallback note that unavailable system fonts fall back.
- [x] Insert it in existing 外观 section before streaming; do not create a new settings tab or independent state.
- [x] Run GeneralTab tests, full frontend test suite, and typecheck. Focused: 68 passed; typecheck/build passed. Full suite: 2261 passed, 1 failed (`TemplateFillDialog.memory` corrupt-storage case, outside font changes), 3 skipped.
- [ ] Commit `feat: add font controls to general settings`.

## Task 4: Verification and Desktop Smoke Test

**Files:** no planned source changes unless verification exposes a defect; tests may be extended only with a failing reproduction first.

- [ ] Run `npm run build` and focused/full Vitest suites.
- [ ] Run backend settings tests in sage-backend environment.
- [ ] Start isolated Vite using `.env.local` (frontend 1433), then launch Electron with `SAGE_PYTHON=/home/fz/anaconda3/envs/sage-backend/bin/python ./node_modules/.bin/electron --no-sandbox .`; do not hand-start an unmatched backend.
- [ ] Verify General > 外观: changing UI font/size updates surrounding UI, changing code font/size affects code independently, 10 and 24 boundaries work, reset restores defaults, restart preserves settings.
- [ ] Inspect `git diff`, run review checks, and record any blocked browser evidence rather than claiming success.
- [ ] Commit only if verification fixes were required, using a focused conventional message.
