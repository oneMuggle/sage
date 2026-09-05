# 50 · main ↔ release/win7 分支对齐状态

> 目的：跟踪 `main` 与 `release/win7` 之间代码/文档的差异状态、已完成的 cherry-pick 批次、未 cherry-pick 的合理理由，以及后续对齐策略。
>
> 维护人：`main` 上的 PR 涉及跨分支兼容时，必须先看本表确认是否在 win7 也需要落地。

---

## 1. 顶层状态（2026-09-05 截止）

| 分支 | 角色 | Python | Electron | EOL |
|------|------|--------|----------|-----|
| `main` | 主开发分支 | 3.10 + pydantic 2.x | 21.4.4 + Chromium 106 | 持续维护 |
| `release/win7` | Win7 LTS 维护分支 | 3.8 + pydantic 1.x | 21.4.4 + Chromium 106 | 2027-12-13 |

**双向 diff 概况**（`git log --oneline A..B` 中 main-only 数 | win7-only 数）：
- `git log origin/release/win7..origin/main --oneline` → **21 个 main-only commit**（其中 20 个功能等价 cherry-pick 已通过独立链路在 win7；1 个真正未对齐）
- `git log origin/main..origin/release/win7 --oneline` → **3 个 win7-only commit**（d7339901 本地开发环境助手 cherry-pick、PR #420/win7 特定修复等，故意保留）
- 工作树层 diff：`git diff --shortstat origin/main origin/release/win7` → 400+ 文件 / ±30K 行（E2E tier 差异 + 故意保留的架构 drift）

---

## 2. 已完成的 cherry-pick 批次

| PR    | 时间 | commit 数 | 主题                                            | 合并 SHA      |
| ----- | ---- | --------- | ----------------------------------------------- | ------------- |
| #417  | 2026-09-04 | 6     | Office CRUD 闭环（profile whitelist + archive/restore + pre-edit snapshot + chat @ref + write_file binary guard + win7 同步） | a2fbb098 (win7 merge) |
| #420  | 2026-09-04 | 1     | 本地开发环境助手（main 上 8d250206 的独立 cherry-pick 到 win7） | d7339901 (win7) |
| #424  | 2026-09-04 | 6     | Phase 1.7 alignment 第二批（worktree infra + CLAUDE.md worktree 登记 + sqlite-fast-pragma + ci paths-ignore + .coveragerc + CLAUDE.md Python 3.10 对齐） | bd2a3384 (win7 merge) |
| #427  | 2026-09-05 | 1     | PR #400 cherry-pick: conda env python 直调 + LLM error envelope 翻译 | b4fe3eba (win7 merge) |

---

## 3. main-only commits 现状（按主题分类）

### 3.1 功能等价 cherry-pick 已进入 win7

| main SHA    | 主题                                                     | win7 等价 SHA | 验证方式 |
| ----------- | -------------------------------------------------------- | ------------- | -------- |
| `8d250206`  | 本地开发环境助手 Stage 0-6                               | `d7339901` (PR #420) | 文件清单 100% 一致；行数差 2 行（squash 微调） |
| `7620a26e`  | CLAUDE.md Python 版本 3.11→3.10 对齐                    | via PR #424  | grep 验证 |
| `312bfc42`  | Office CRUD 闭环技术文档 + 用户手册                      | via PR #424  | 文件存在 |
| `7aa24a15`  | write_file reject binary-extension                       | via PR #424  | tests/unit/ 验证 |
| `3b9d608d`  | chat @ ref filename lookup + persist_read_summary merge  | via PR #424  | 集成测试 |
| `014f2ab6`  | office archive/restore + pre-edit snapshot                | via PR #424  | office 模块 |
| `441db71d`  | profile whitelist wiring + legacy rename + PPT create fix | via PR #424  | profiles.py |
| `0b878e8d`  | sqlite-fast-pragma synchronous=OFF                       | via PR #424  | backend/data/ |
| `5ae8577b`  | .coveragerc 替换 pytest.ini                                | via PR #424  | repo root |
| `94a6d92b`  | ci paths-ignore + concurrency + cache                    | via PR #424  | .github/workflows/ |
| `1f83e1ae`  | CLAUDE.md 登记 worktree 基础设施                         | via PR #424  | .claude/CLAUDE.md |
| `72f10cd0`  | git worktree 并行开发基础设施                            | via PR #424  | scripts/worktree.sh |
| `9e919ec5`  | LLM 原地编辑与删除能力（office_update / office_delete）   | `15e9e105`   | office/tool_service.py |
| `6241c67d`  | agent profile migration recovery                          | via PR chain | profiles.py 含 LEGACY_TOOL_NAME_RENAMES |
| `f382e475`  | researcher http_download + primary 委派提示               | via PR chain | profiles.py 含 PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION |
| `d95c1165`  | Sage 品牌图标（favicon + BrandLogo）                      | via PR chain | public/sage.svg + favicon-16/32/512.png |
| `01af1960`  | local-auth token mismatch diagnostics + 401-aware UI     | via PR chain | probeBackendAuthForSkipBackend in electron/main.ts |
| `d6185b76`  | 内网 Web 访问（NetworkPolicy + http_download）            | via PR chain | backend/domain/network_policy.py + backend/tools/download_tool.py |
| `2cc6ca24`  | 修复 chat stream reasoning 重复累积                      | `a2fbb098` (win7) | backend/api/legacy_routes.py |
| `0848e589`  | skills 边界硬化 + dependency-audit-policy.json           | `5b0eba05` (PR #386) | .github/dependency-audit-policy.json |

### 3.2 真正未对齐 — PR #427 (cherry-pick 进行中)

| main SHA    | 主题                                                                | 状态                |
| ----------- | ------------------------------------------------------------------- | ------------------- |
| `c02471be`  | fix(electron): use conda env python directly in dev mode (avoid wrapper pid mismatch) | **✅ 已合并 PR #427** → `b4fe3eba` |

修复 dev-mode 「后端服务在 30 秒内未响应」dialog。win7 上 backendLauncher.ts 仍走 `conda run -n` 三层包装树，`ownsBackend` pid 检查始终失败。PR #427 把 `CONDA_PREFIX/bin/python` 直调分支 + `_parseUpstreamError` 中文错误翻译带入 win7。

### 3.3 不应 cherry-pick（架构/版本元数据）

| main SHA    | 主题                                              | 原因                                                |
| ----------- | ------------------------------------------------- | --------------------------------------------------- |
| `abb60582`  | chore(release): bump version to 0.4.9-alpha.30    | win7 用独立版本号（`v*-lts` 标签规则），不同步 |

### 3.4 未核查 / 待跟进

无 — main-only commit 全部分类完毕（见 §3.1、§3.2、§3.3）。

---

## 4. win7-only commits（故意保留）

| win7 SHA    | 主题                                          | 原因                                            |
| ----------- | --------------------------------------------- | ----------------------------------------------- |
| `d7339901`  | 本地开发环境助手（独立 cherry-pick from main） | PR #420 单独批次，与 PR #424 独立演进 |
| `5749b4f6`  | PR #407: alpha.12-win7 doctor 端口抢占修复     | win7 特定环境的端口/启动逻辑                       |
| `5b0eba05`  | PR #386: backport skills security hardening    | 早于 main #385 的 win7 cherry-pick              |
| `a2fbb098`  | fix: prevent duplicated reasoning in Win7 chat streams | win7 独立修复（main 2cc6ca24 的等价修复，但 win7 先做） |
| `26be63f8`  | feat(backend): 5 theme preset seeds             | win7 独立功能                                    |
| `0db08aae`  | fix(deps): 锁定 tauri-runtime 版本              | win7 不使用 tauri，但保留以防历史路径回退          |
| `313c2edd`  | fix(backend): 修复 assistant_message 引用        | win7 特定 assistant 调用链修复                    |

> 规则：win7-only 不主动同步到 main（除非是 P0 安全/正确性 bug）。若 main 需要某个 win7-only 功能，由 main 反向 cherry-pick。

---

## 5. 后续对齐策略

### 5.1 触发时机

- main 上每次 `feat:` / `fix:` / `refactor:` / `perf:` 合并后，**默认问一句**：是否需要同步到 win7？
- 同步判定标准（必须同时满足）：
  1. win7 上对应功能不存在等价实现
  2. 不依赖 main 独有依赖（pydantic 2 / Python 3.10 特性）
  3. 不依赖 e2e-pr-gate.yml（win7 CI 不跑 e2e）
  4. 修改文件 ≤ 6 个，diff ≤ 500 行

### 5.2 跳过对齐的合理理由

- **e2e-pr-gate.yml / e2e-nightly.yml**：win7 CI 不跑 e2e tier，跳过路径过滤器
- **Pydantic 2.x 特性**：`from_attributes`, `model_dump(mode='json')`, `Annotated[T, ...]` 等 → 不能直接 port
- **Python 3.10+ syntax**：`match` 语句, PEP 604 union `X | Y`, builtin generics → 不能直接 port
- **Backend 大型架构重构**：main 上 `memory/data/services/` 重写 — 故意不跟，win7 是维护分支

### 5.3 批次节奏

- 每 1-2 周一次小批次（3-6 commit）
- 每批独立 PR + 独立 CI 验证
- 每次合并后立即写 memory 记录（`sage-win7-phase-1-alignment-pr###.md`）

---

## 6. 验证方法

每批 cherry-pick 后必须验证：

```bash
# 1. TypeScript build（win7 同样有 frontend）
npx tsc --noEmit  # 0 error

# 2. 相关单元测试
npx vitest run <modified-paths>

# 3. push 后等 CI 全绿：
#    - Backend (Python 3.8, Win7 LTS) ← 必跑
#    - Electron build (ubuntu-latest, windows-latest) ← 必跑
#    - Frontend (TypeScript) ← 必跑
#    - Electron smoke (playwright-electron) ← 必跑

# 4. 重 base 检测
gh pr checks <N> --watch  # 5 个 check 全绿才能 merge
```

如果 `mergeable: CONFLICTING`：先 `git fetch origin release/win7 && git rebase origin/release/win7` + `--force-with-lease` + 等 CI 重跑。

---

## 7. 关联文档

- [31 Win7 LTS 维护](./31-win7-lts.md) — EOL 时间表 / Win7 用户迁移 / 真机烟测 SOP
- [47 Git Worktree 并行开发](./47-git-worktree-workflow.md) — 跨分支并行的基础设施
- [30 Release Tiers](./30-release-tiers.md) — `v*` vs `v*-lts` 标签规则
- `.claude/CLAUDE.md` → 「双分支长期共存策略（强制）」一节
- `.claude/projects/-home-fz-project-sage/memory/sage-win7-phase*-*.md` — 历史批次详情

---

_最后更新：2026-09-05（PR #427 已合并）_