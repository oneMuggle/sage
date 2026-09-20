# Skill Runtime and Registration Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Sage skills reliably discoverable and executable with the Sage backend runtime, while preserving explicit directory boundaries, script approval, and cross-platform packaging behavior.

**Architecture:** Separate skill registration roots from script execution allowed roots. The adapter will load user-discovered skills plus shipped skills, but only user-discovered roots will authorize external script paths. The backend will expose its selected Python interpreter through a non-secret runtime environment variable and use that information for shell-facing skill guidance/diagnostics without exposing capability tokens. SKILL.md automatic activation remains explicit through `when_to_use`; no implicit parsing of prose or arbitrary directory recursion will be added.

**Tech Stack:** Python 3.10 backend (Python 3.8-compatible shared paths where required), FastAPI, pytest, TypeScript/Electron, Vitest/tsc.

**Spec:** Existing approved design in conversation; supporting references: `docs/technical/24-skills-system.md`, `docs/user-manual/04-skill-md-authoring.md`, and `docs/superpowers/specs/2026-06-29-agentskills-io-spec-conformance-design.md`.

## Global Constraints

- Do not modify `release/win7` or `backend/requirements-py38.txt` from this main-based worktree.
- Do not recursively scan arbitrary filesystem paths; skill roots remain `$SAGE_SKILLS_DIR`, `$CWD/skills`, and `~/.sage/skills`.
- Shipped skill directories may be registered but must not be added to `ScriptRunner.allowed_roots` for external script authorization.
- Script execution remains fail-closed through `SAGE_SKILL_SCRIPT_ALLOWLIST` and the existing permission gate.
- Never pass `SAGE_LOCAL_AUTH_TOKEN`, `SAGE_BACKEND_OWNERSHIP_TOKEN`, provider keys, or other secrets into skill subprocesses.
- Run Python tests with `/home/fz/anaconda3/envs/sage-backend/bin/python`.
- Add tests before implementation for each behavior change; preserve Python 3.8 syntax in shared backend files.

---

### Task 1: Establish runtime and registration regression tests

**Files:**
- Modify: `backend/tests/unit/test_skill_md_loader.py`
- Modify: `backend/tests/integration/test_skill_md_integration.py`
- Modify: `backend/tests/unit/test_skill_md_loader_gating.py`
- Create or modify: `backend/tests/unit/test_skill_runtime_context.py`
- Modify: `backend/tests/unit/test_inproc_lifecycle.py` or the nearest existing inproc adapter test module

**Interfaces:**
- Tests consume the existing `discover_skill_md_dirs`, `register_skill_md_skills`, `InprocSkillAdapter`, `SubprocessSandboxAdapter`, and `BashTool` seams.
- Tests produce executable expectations for later implementation: shipped skills are visible in a real adapter; shipped roots are not script-authorized; a configured runtime path is non-secret and propagated; existing gating only evaluates explicit `requires` metadata.

- [ ] **Step 1: Add a failing adapter-level shipped regression test**

  Construct `InprocSkillAdapter` with a temporary user skills root and assert that a known shipped skill such as `academic-search` is present in `list_skills()`. Patch the singleton/database lifecycle dependencies as existing tests do so the test is deterministic.

- [ ] **Step 2: Add a failing allowed-root separation test**

  Assert that the adapter's `ScriptRunner` allowed roots contain the discovered user root but not `backend/skills/skill_md/shipped`, while the registry still contains the shipped skill.

- [ ] **Step 3: Add a failing runtime-context test**

  Assert that the runtime context exposes only the selected interpreter path and does not include `SAGE_LOCAL_AUTH_TOKEN`, `SAGE_BACKEND_OWNERSHIP_TOKEN`, or provider credentials. Use a fake backend launch environment so the test does not depend on the host installation.

- [ ] **Step 4: Add a failing external skill contract test**

  Build a temporary `storage-analyzer`-shaped SKILL.md with `when_to_use`, `user-invocable`, and a script. Assert that it is discoverable under an explicit `SAGE_SKILLS_DIR`, auto-activation uses `when_to_use`, slash listing includes it, and no implicit Python gating occurs when `requires` is absent.

- [ ] **Step 5: Run only the new tests and record the expected failures**

  Run:
  ```bash
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
    backend/tests/unit/test_skill_md_loader.py \
    backend/tests/integration/test_skill_md_integration.py \
    backend/tests/unit/test_skill_runtime_context.py -q
  ```
  Expected: the new adapter/runtime assertions fail against the current implementation; existing tests should remain collected and any unrelated baseline failure must be recorded separately.

---

### Task 2: Separate shipped registration roots from script authorization roots

**Files:**
- Modify: `backend/adapters/out/skill/inproc.py:82-124`
- Modify: `backend/skills/skill_md/loader.py:561-607` only if a small helper is needed
- Modify: `backend/tests/unit/test_skill_md_loader.py`
- Modify: `backend/tests/integration/test_skill_md_integration.py`

**Interfaces:**
- Consumes `discover_skill_md_dirs()`, `_discover_shipped_dir()`, `register_skill_md_skills()`, and `ScriptRunner`.
- Produces an adapter where `list_skills()` includes shipped skills by default, while `ScriptRunner.allowed_roots` remains limited to user-discovered roots.

- [ ] **Step 1: Add a pure helper or explicit effective-root construction**

  Keep `discover_skill_md_dirs()` unchanged as the user/script-safe root discovery API. In adapter initialization, compute `user_skill_dirs = discover_skill_md_dirs()` and `registration_dirs = user_skill_dirs + shipped_dir_if_present`, deduplicated by resolved path.

- [ ] **Step 2: Pass only registration roots to the loader and only user roots to ScriptRunner**

  Construct `ScriptRunner(..., allowed_roots=list(user_skill_dirs))`. Call `register_skill_md_skills(..., dirs=[str(path) for path in registration_dirs], gating_ctx=build_gating_context_for_dirs(registration_dirs), script_runner=...)`. This preserves shipped skill loading while allowing their body/prompt use without authorizing shipped scripts.

- [ ] **Step 3: Keep rescan behavior explicit and safe**

  Rescan user roots only, update `self._skill_dirs` and `ScriptRunner._allowed_roots` from `discover_skill_md_dirs()`, and do not accidentally duplicate shipped skills or widen script roots during rescan.

- [ ] **Step 4: Run focused loader and adapter tests**

  Run:
  ```bash
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
    backend/tests/unit/test_skill_md_loader.py \
    backend/tests/integration/test_skill_md_integration.py \
    backend/tests/unit/test_inproc_lifecycle.py -q
  ```
  Expected: shipped registration and root separation tests pass.

- [ ] **Step 5: Commit the isolated registration fix**

  ```bash
  git add backend/adapters/out/skill/inproc.py backend/skills/skill_md/loader.py backend/tests
  git commit -m "fix: restore shipped skill registration in adapter"
  ```

---

### Task 3: Carry the selected Sage Python runtime into shell-facing skill execution

**Files:**
- Modify: `electron/backendLauncher.ts:364-376` and the spawn environment assembly in `electron/main.ts`
- Modify: `backend/tools/shell_resolver.py` or add a focused runtime helper under `backend/tools/`
- Modify: `backend/tools/bash_tool.py` only where runtime metadata is decorated
- Modify: `backend/adapters/out/skill_script/subprocess_sandbox.py` only if it needs to consume the explicit runtime variable safely
- Test: `electron/__tests__/backendLauncher.test.ts` (existing or create at the nearest launcher test path)
- Test: `backend/tests/unit/test_tools_bash.py` or nearest Bash test module
- Test: `backend/tests/unit/test_skill_runtime_context.py`

**Interfaces:**
- Consumes the backend launch plan's selected Python command.
- Produces a non-secret environment value such as `SAGE_RUNTIME_PYTHON` containing the absolute interpreter path where available, with no change to auth-token handling.
- Bash result metadata/skill runtime guidance must distinguish the Sage runtime from generic PATH runtimes; no automatic execution of arbitrary command text is introduced.

- [ ] **Step 1: Add failing launcher tests**

  For dev override, conda direct, packaged Windows, and packaged Linux plans, assert `SAGE_RUNTIME_PYTHON` is set to the selected executable. For broken-installer plans, assert it is absent. Assert existing `PYTHONPATH` and token behavior remains unchanged.

- [ ] **Step 2: Add failing backend runtime-context tests**

  With `SAGE_RUNTIME_PYTHON` set, assert a helper returns the validated absolute path only when it is a regular executable file. With the variable absent or invalid, assert the helper returns no runtime path and does not fall back to secret-bearing variables.

- [ ] **Step 3: Implement the minimal runtime context helper**

  Add a small backend helper that reads `SAGE_RUNTIME_PYTHON`, validates it as an executable regular file, and returns a structured non-secret runtime description. Do not make it search arbitrary PATH entries or execute the interpreter during every Bash call.

- [ ] **Step 4: Propagate the launch variable from Electron**

  Set `SAGE_RUNTIME_PYTHON` in every successful `resolveBackendLaunchCommand()` branch to the exact selected Python command. Preserve existing environment merge order and do not add bundled Python directories globally unless tests demonstrate that shell command compatibility requires it.

- [ ] **Step 5: Expose runtime metadata to Bash/skill diagnostics**

  Add the validated interpreter path to structured tool metadata or the skill execution context, so the LLM can use the Sage interpreter explicitly rather than infer that Python is absent from a failed `python3` lookup. Keep command output and existing shell behavior compatible.

- [ ] **Step 6: Run focused TypeScript and Python tests**

  Run:
  ```bash
  npm exec vitest run electron/__tests__/backendLauncher.test.ts
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_skill_runtime_context.py backend/tests/unit/test_tools_bash.py -q
  ```
  Expected: all focused tests pass.

- [ ] **Step 7: Commit the runtime propagation fix**

  ```bash
  git add electron backend/tools backend/adapters/out/skill_script backend/tests
  git commit -m "fix: expose Sage runtime to skill execution diagnostics"
  ```

---

### Task 4: Make the external skill contract executable and diagnosable

**Files:**
- Modify: `docs/user-manual/04-skill-md-authoring.md`
- Modify: `docs/technical/24-skills-system.md`
- Modify: `backend/skills/skill_md/loader.py` or API serialization only if diagnostic fields are missing
- Modify: `backend/api/legacy_routes.py` only if rescan/import must expose a stable reason
- Test: `backend/tests/integration/test_skill_md_integration.py`
- Test: `src/widgets/skills/__tests__/Skills.test.tsx` or existing skill list tests if UI copy/fields change

**Interfaces:**
- Consumes the explicit `when_to_use`, `requires`, `user-invocable`, and `script` contracts.
- Produces documentation and API behavior that clearly distinguish registration, automatic activation, slash prompt loading, and explicit script execution.

- [ ] **Step 1: Add failing contract tests**

  Assert that a skill with `when_to_use` auto-activates, a skill without it does not, slash execution returns body without executing a script, and explicit `script` execution is the only path reaching `ScriptRunner`.

- [ ] **Step 2: Implement only missing diagnostics or stable serialization**

  Preserve current semantics; add structured fields only where the current API cannot tell the caller whether a skill was skipped for `missing bin`, not discovered, or loaded successfully. Do not infer dependencies from arbitrary Markdown prose.

- [ ] **Step 3: Update authoring and technical documentation**

  Document that:
  - external roots must be configured/imported;
  - `description` is not an auto-activation trigger;
  - `when_to_use` is required for A16 natural-language activation;
  - `compatibility` is informational;
  - `requires.bins` checks PATH only;
  - explicit script dispatch uses Sage's backend interpreter and allowlist;
  - slash commands return prompt bodies unless a script parameter is explicitly supplied.

- [ ] **Step 4: Run focused integration and UI tests**

  Run:
  ```bash
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_skill_md_integration.py -q
  npm exec vitest run src/widgets/skills src/widgets/chat
  ```

- [ ] **Step 5: Commit the contract and documentation changes**

  ```bash
  git add backend docs src
  git commit -m "docs: clarify skill discovery and runtime contracts"
  ```

---

### Task 5: Full verification and review

**Files:**
- No new files unless verification uncovers a focused regression.

- [ ] **Step 1: Run Python skill and runtime test suites**

  ```bash
  /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
    backend/tests/unit/test_skill_md_loader.py \
    backend/tests/unit/test_skill_md_loader_gating.py \
    backend/tests/unit/test_skill_md_integration.py \
    backend/tests/integration/test_skill_import.py \
    backend/tests/unit/test_skill_runtime_context.py -q
  ```

- [ ] **Step 2: Run TypeScript checks and focused Electron tests**

  ```bash
  npm exec vitest run electron/__tests__ src/widgets/skills src/widgets/chat
  npm run typecheck --if-present
  ```

- [ ] **Step 3: Run formatting/lint checks for changed files**

  ```bash
  /home/fz/anaconda3/envs/sage-backend/bin/python -m ruff check backend/tests backend/skills backend/adapters backend/tools
  npm run lint --if-present
  ```

- [ ] **Step 4: Inspect the final diff and verify no unrelated changes**

  ```bash
  git diff --check
  git status --short
  git diff --stat
  ```

- [ ] **Step 5: Run the mandatory code review agents**

  Review the final diff with the Python reviewer, TypeScript reviewer, general code reviewer, and security reviewer. Resolve CRITICAL/HIGH findings before completion; specifically verify that runtime propagation does not leak auth tokens or widen script roots.

- [ ] **Step 6: Report worktree branch, commits, tests, and remaining limitations**

  State explicitly whether full tests passed, which checks were unavailable, and that no changes were merged into `main`.
