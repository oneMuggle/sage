# 记忆质量改进 Phase 1–4 的 main 分支移植方案

> 创建日期：2026-11-05
> 来源分支：`release/win7`（PR #2878 已 squash 合入，commit `92c957a71`）
> 目标分支：`main`
> 关联归档：`docs/technical/132-memory-quality-optimization.md`（win7 侧）
> 状态：**评估中**（待 main 侧 feature 分支开干）

---

## 1. 背景

win7 侧 PR #2878 一次性交付了记忆质量改进的四个 Phase：

| Phase | 内容 |
|---|---|
| 1 | 提取门槛升级（对话长度 / 重要性评分）+ 否定词 NOOP 修复 |
| 2 | 冲突消解 `aremember_with_conflict_check` + 已知事实过滤 |
| 3 | 主题簇巩固 + 低质量软失效 + `MemoryQualityScorer` |
| 4 | 质量可视化 / 批量清理 / 来源会话 / 反馈 / 使用提示 |

由于这些功能最初是在 `release/win7` 上开发的，main 侧目前**完全没有**这些能力。
按项目"双分支功能对齐"原则（CLAUDE.md §"核心规则 #2"），main 需要单独 port。

### 早期担忧：win7-only 模块阻塞

Memory `sage-memory-quality-phase4-pr2878.md` 原记录："main 分支缺少 `lifecycle.py` / `hooks.py` / `embedding_queue.py`，不能简单 cherry-pick"。

实际调查后发现这三个 win7-only 模块**都不是** Phase 1–4 代码的直接依赖：

- `lifecycle.py` 是 win7 独有的、包裹 `MemoryManager` 的高层封装；main 侧没有等价物，但 Phase 1–4 的底层 API（`memorize_with_conflict_check` / scorer / feedback store）都不依赖它
- `hooks.py` 仅被 `lifecycle.py` 调用
- `embedding_queue.py` 仅被 `lifecycle.py` 调用
- `aremember_with_conflict_check`（唯一的 async 版本）只在 `lifecycle.py:382` 一处被调用；main 侧用同步的 `memorize_with_conflict_check` 即可

→ **结论：main port 比预期干净得多**。不需要搬运 lifecycle/hooks/embedding_queue 三件套。

---

## 2. 调研细节

### 2.1 两侧代码尺寸对比（2026-11-05 实测）

| 文件 | main | win7 | 差异说明 |
|---|---:|---:|---|
| `backend/memory/conflict.py` | 266 | 459 | win7 多 Phase 2 冲突消解逻辑（~193 行） |
| `backend/memory/extractor.py` | 199 | 407 | win7 多 Phase 1 提取门槛 + 否定词过滤（~208 行） |
| `backend/memory/consolidation.py` | 212 | 213 | 几乎一致，win7 多 1 行主题簇巩固 |
| `backend/api/legacy_memory_list_routes.py` | 414 | 566 | win7 多 Phase 4 `_enrich_memory_records` 的 quality_score 注入（~152 行） |
| `backend/memory/manager.py` | 735 | 952 | win7 多 `aremember_with_conflict_check` + lifecycle 集成（~217 行）；main 不需要 |
| `backend/scheduler/evolution.py` | 1586 | 2204 | win7 多 618 行，但绝大部分是 lifecycle/hooks 集成；main 只需最小切 `preference_labels` |

### 2.2 win7 新增、main 缺失的纯新文件

| 文件 | 行数 | 用途 | main port 需要？ |
|---|---:|---|---|
| `backend/memory/quality_scorer.py` | 256 | `MemoryQualityScorer`：五维评分（importance/recency/uniqueness/clarity/specificity） | ✅ 必须 |
| `backend/memory/feedback_store.py` | 139 | `memories_feedback` 表 + `attach_feedback()` / `get_feedback()` | ✅ 必须 |
| `backend/memory/preference_labels.py` | 72 | 机器 preference key → 中文标签的纯显示映射 | ✅ 必须（`scheduler/evolution.py` 用） |
| `backend/api/legacy_memory_quality_routes.py` | (新增) | `/memory/quality-candidates` + `/memory/batch-delete` | ✅ 必须 |
| `backend/api/legacy_memory_feedback_routes.py` | (新增) | `/memory/{id}/feedback` | ✅ 必须 |
| `backend/memory/lifecycle.py` | 465 | win7 独有高层封装 | ❌ 跳过 |
| `backend/memory/hooks.py` | 110 | 仅被 lifecycle.py 调用 | ❌ 跳过 |
| `backend/memory/embedding_queue.py` | 96 | 仅被 lifecycle.py 调用 | ❌ 跳过 |
| `src/widgets/memory/MemoryUsageHint.tsx` | (新增) | 记忆库使用说明卡片 | ✅ 必须 |
| `src/widgets/memory/useSessionInfo.ts` | (新增) | 来源会话标题 + 相对日期 hook | ✅ 必须 |

### 2.3 manager.py 的处理策略

win7 `manager.py` 比 main 多 ~217 行，主体是：
1. `aremember_with_conflict_check` async 方法
2. lifecycle 集成钩子（emit 事件、写 history）

main **没有 lifecycle.py**，所以：
- `aremember_with_conflict_check` → 不 port（main 不需要 async 版本）
- lifecycle 钩子 → 不 port
- 但 Phase 2 的"已知事实过滤"对 `memorize_with_conflict_check`（同步版本）的增强需要 port

→ **只 port 同步路径的增强，不 port async 方法**。

---

## 3. 范围

### ✅ 要 port

后端（main 侧，py3.10 / pydantic 2.x）：

1. **新增** `backend/memory/quality_scorer.py`（直接 cherry-pick，pydantic 2.x 兼容）
2. **新增** `backend/memory/feedback_store.py`（直接 cherry-pick）
3. **新增** `backend/memory/preference_labels.py`（直接 cherry-pick）
4. **新增** `backend/api/legacy_memory_quality_routes.py`（直接 cherry-pick）
5. **新增** `backend/api/legacy_memory_feedback_routes.py`（直接 cherry-pick）
6. **修改** `backend/memory/conflict.py` —— cherry-pick Phase 2 冲突消解 additions
7. **修改** `backend/memory/extractor.py` —— cherry-pick Phase 1 门槛 + 否定词修复
8. **修改** `backend/memory/consolidation.py` —— cherry-pick 1 行主题簇巩固
9. **修改** `backend/api/legacy_memory_list_routes.py` —— cherry-pick `_enrich_memory_records` 的 quality_score 注入
10. **修改** `backend/memory/manager.py` —— 仅 port `memorize_with_conflict_check`（同步）的已知事实过滤增强
11. **修改** `backend/scheduler/evolution.py` —— 仅 cherry-pick `preference_labels` 的最小引用（不动其他 600 行差异）
12. **修改** `backend/api/legacy_routes.py` 或等价注册点 —— 注册新增的两个 router
13. **修改** `backend/data/database.py`（或 `memories_feedback` 表的 migration 点）—— 新建 feedback 表

前端（与分支无关，直接 cherry-pick 即可）：

14. **新增** `src/widgets/memory/MemoryUsageHint.tsx`
15. **新增** `src/widgets/memory/useSessionInfo.ts`
16. **修改** `src/widgets/memory/MemoryBrowser.tsx` —— 质量条 / 选择模式 / 反馈按钮 / 来源会话渲染
17. **修改** `src/shared/api/memoryApi.ts` —— 新增 `getQualityCandidates` / `batchDeleteMemories` / `submitMemoryFeedback`
18. **修改** `src/shared/api/types.ts` —— 新增 `MemoryQualityCandidate` / `BatchDeleteResponse` 等类型
19. **修改** `src/pages/Memory.tsx` —— 挂载 `MemoryUsageHint`
20. **修改** i18n `settingsUi.ts`（zh/en） —— 新增 `memory.usage_hint` / `memory.quality_*` / `memory.feedback.*` 等 key

测试：

21. **新增** `backend/tests/unit/test_memory_quality_scorer.py`
22. **新增** `backend/tests/unit/test_preference_labels.py`
23. **新增** `backend/tests/integration/test_memory_quality_enrichment.py`
24. **新增** `backend/tests/integration/test_memory_feedback_routes.py`
25. **新增** `backend/tests/integration/test_memory_quality_pipeline.py`（Phase 3 集成）
26. **新增** `backend/tests/unit/test_aremember_with_conflict_check.py` —— **不 port**（main 无 async 版本）；对应改为在 `test_memory_conflict_semantic.py` 里加同步路径的已知事实过滤用例

### ❌ 跳过（win7-only，main 不需要）

- `backend/memory/lifecycle.py`
- `backend/memory/hooks.py`
- `backend/memory/embedding_queue.py`
- `backend/memory/manager.py` 中的 `aremember_with_conflict_check` 与 lifecycle 集成块
- `backend/tests/unit/test_lifecycle_known_facts.py`（测 lifecycle 集成）
- `backend/tests/unit/test_env_memory.py` 中 lifecycle 相关部分

### ⚠️ 谨慎处理

- `scheduler/evolution.py`：win7 比 main 多 618 行，但绝大部分是 lifecycle 集成。**只 port `preference_labels` 的最小切**（约 10-20 行修改），其余差异不动。
- `architecture-baseline.json`：每个修改的文件都要同步更新 main 侧的基线行数。
- pydantic 2.x 兼容：main 用 pydantic 2.x，`Field(pattern=, max_length=)` 直接可用，不需要 win7 的 `pydantic_compat.py` monkey-patch。**port 时去掉 win7-only 的 compat 包装**。

---

## 4. 实施步骤

每个步骤独立可验证、独立可提交。按依赖排序。

- [x] S1 建立 main 侧 feature 分支
- [x] S2 port `quality_scorer.py` + 单测
- [x] S3 port `feedback_store.py` + 表 migration
- [x] S4 port `preference_labels.py` + 单测
- [x] S5 port `conflict.py` 的 Phase 2 additions
- [x] S6 port `extractor.py` 的 Phase 1 门槛
- [x] S7 port `consolidation.py` 的 1 行主题簇巩固
- [x] S8 port `manager.py` 同步路径增强
- [x] S9 port 4 个新路由 + 注册 + 集成测试（`test_memory_quality_pipeline.py` 跳过：依赖 win7-only `MemoryLifecycleManager`；同步路径覆盖已在 `test_memory_conflict_semantic.py` 中）
- [ ] S10 port `scheduler/evolution.py` 最小切
- [ ] S11 port 前端
- [ ] S12 architecture-baseline 同步
- [ ] S13 PR + CI + 合并

### S1. 建立 main 侧 feature 分支

```bash
cd /home/fz/project/sage
scripts/worktree.sh new feat/memory-quality-main-port
# 自动从 main 切出，分配 8766/1421 端口
cd .worktrees/feat-memory-quality-main-port
```

### S2. port `quality_scorer.py` + 单测

- cherry-pick win7 的 `backend/memory/quality_scorer.py`（commit `19629a2da` 附近）
- cherry-pick `backend/tests/unit/test_memory_quality_scorer.py`
- 移除 win7 的 `from __future__ import annotations` 之外的 py3.8 shim（main 是 py3.10，不需要）
- 验证：`pytest backend/tests/unit/test_memory_quality_scorer.py` 绿
- 提交：`feat(memory): port MemoryQualityScorer to main`

### S3. port `feedback_store.py` + 表 migration

- cherry-pick `backend/memory/feedback_store.py`
- 修改 `backend/data/database.py` 加 `memories_feedback` 表的 migration（参考 win7 `database.py` 的 diff）
- 验证：`python -c "from backend.data.database import Database; Database()"` 不报错
- 提交：`feat(memory): port feedback_store + memories_feedback migration to main`

### S4. port `preference_labels.py` + 单测

- cherry-pick `backend/memory/preference_labels.py`
- cherry-pick `backend/tests/unit/test_preference_labels.py`
- 验证：pytest 绿
- 提交：`feat(memory): port preference_labels to main`

### S5. port `conflict.py` 的 Phase 2  additions

- 从 win7 `conflict.py` 提取 Phase 2 冲突消解 additions（约 193 行新增）
- 应用到 main `conflict.py`（注意 main 266 行 vs win7 459 行）
- cherry-pick `backend/tests/unit/test_memory_conflict_semantic.py` 的 additions
- 验证：pytest 绿
- 提交：`feat(memory): port conflict resolution additions to main`

### S6. port `extractor.py` 的 Phase 1 门槛

- 从 win7 `extractor.py` 提取门槛升级 + 否定词 NOOP 修复（约 208 行）
- 应用到 main `extractor.py`（main 199 行 → 预计 ~400 行）
- cherry-pick `backend/tests/unit/test_memory_extractor.py` 的相关 additions
- 验证：pytest 绿
- 提交：`feat(memory): port extractor thresholds + negation NOOP fix to main`

### S7. port `consolidation.py` 的 1 行主题簇巩固

- cherry-pick 单行修改
- 验证：pytest `backend/tests/integration/test_memory_phase3_pipeline.py` 绿
- 提交：`feat(memory): port consolidation topic-cluster tweak to main`

### S8. port `manager.py` 同步路径增强

- 只 port `memorize_with_conflict_check` 的已知事实过滤增强（不动 `aremember_with_conflict_check`）
- 验证：pytest `backend/tests/unit/test_env_memory.py` 绿
- 提交：`feat(memory): port manager memorize known-facts filter to main`

### S9. port 4 个新路由 + 注册 + 集成测试

- cherry-pick `backend/api/legacy_memory_quality_routes.py`
- cherry-pick `backend/api/legacy_memory_feedback_routes.py`
- 修改 `backend/api/legacy_routes.py`（或 main 的注册点）注册两个新 router
- 修改 `backend/api/legacy_memory_list_routes.py` 加 quality_score 注入
- cherry-pick 集成测试：
  - `test_memory_quality_enrichment.py`
  - `test_memory_feedback_routes.py`
  - `test_memory_quality_pipeline.py`
- 移除测试里的 py3.8 shim（如 `# ruff: noqa: UP006, UP007, UP035`）
- 验证：pytest `backend/tests/integration/test_memory_*.py` 全绿
- 验证：`ruff check backend/api/legacy_memory_quality_routes.py backend/api/legacy_memory_feedback_routes.py backend/api/legacy_memory_list_routes.py`
- 提交：`feat(memory): port quality/feedback routes + list enrichment to main`

### S10. port `scheduler/evolution.py` 最小切

- 只 cherry-pick `preference_labels` 的引用修改（约 10-20 行）
- 不动 lifecycle 集成的 600 行差异
- 验证：pytest `backend/tests/unit/test_preference_learning_llm.py` + `backend/tests/test_preference_injection.py` 绿
- 提交：`feat(memory): wire preference_labels into scheduler/evolution.py on main`

### S11. port 前端

- cherry-pick 所有前端改动（与 py 版本无关）：
  - `src/widgets/memory/MemoryUsageHint.tsx`
  - `src/widgets/memory/useSessionInfo.ts`
  - `src/widgets/memory/MemoryBrowser.tsx` 修改
  - `src/shared/api/memoryApi.ts` + `types.ts`
  - `src/pages/Memory.tsx`
  - i18n `settingsUi.ts`
- 验证：`npm run build` 绿
- 验证：`tsc --noEmit` 绿
- 验证：`npm run test` 新增 MemoryBrowser / MemoryUsageHint 测试绿
- 提交：`feat(memory): port Phase 4 frontend to main`

### S12. architecture-baseline 同步

- 跑 `npm run count-lines`（或对应脚本）更新 main 的 `architecture-baseline.json`
- 提交：`chore(arch): update baseline after memory quality port`

### S13. PR + CI + 合并

- `git push -u origin feat/memory-quality-main-port`
- `gh pr create --title "feat(memory): Phase 1-4 记忆质量改进 main 侧 port" --body "..."`
- 监控 CI（`gh pr checks <N> --watch`）
- code review（用 `code-reviewer` agent）
- 用户 merge
- 清理分支

---

## 5. 风险

| 风险 | 缓解 |
|---|---|
| **pydantic 2.x vs 1.x 字段参数差异** | main 用 pydantic 2.x，`Field(pattern=, max_length=)` 直接可用；port 时**去掉** win7 的 `pydantic_compat.py` monkey-patch。集成测试里显式验证 pattern 校验生效 |
| **`scheduler/evolution.py` cherry-pick 冲突** | 618 行差异里大部分是 lifecycle 集成，必须**只挑** `preference_labels` 相关的小块。冲突时按 main 现状优先，手动 merge |
| **`manager.py` async/sync 路径混淆** | 严格只 port 同步路径增强。不引入 `aremember_with_conflict_check`（main 没有调用方） |
| **architecture-baseline 涨超 ratchet** | 新文件会新增 baseline 项；现有文件行数增长需同步更新。S12 单独一步处理 |
| **集成测试依赖 `client` fixture** | main 的 `client` fixture 与 win7 略有差异（main 无 lifecycle setup）。测试前确认 fixture 在 main 侧可用 |
| **cherry-pick 跨分支 hash 失效** | 用 `git format-patch` + `git am` 或手工 diff 应用；不直接 `git cherry-pick <hash>`（win7 和 main 历史已分叉） |

---

## 6. 不在范围内

- ❌ 不 port `lifecycle.py` / `hooks.py` / `embedding_queue.py`（main 无需求）
- ❌ 不 port `aremember_with_conflict_check`（main 无调用方）
- ❌ 不动 `scheduler/evolution.py` 除 `preference_labels` 之外的 600 行差异
- ❌ 不新增向量索引 / 嵌入模型（scorer 字面 bigrams 已够用）
- ❌ 不做五维雷达可视化（数字 + 颜色条足够）
- ❌ 不回灌 win7（本次是 main 单向 port，不回写）

---

## 7. 验收

- [ ] 所有 26 个 win7 侧新测试在 main 侧有对应等价物并绿
- [x] `pytest backend/tests/unit/test_memory_quality_scorer.py` 绿
- [x] `pytest backend/tests/unit/test_preference_labels.py` 绿
- [x] `pytest backend/tests/integration/test_memory_quality_enrichment.py` 绿
- [x] `pytest backend/tests/integration/test_memory_feedback_routes.py` 绿
- [x] `ruff check` 全绿（无 ERA001 / PT018 类新违规）
- [ ] `tsc --noEmit` 全绿
- [ ] `npm run build` 全绿
- [ ] `npm run count-lines`（architecture ratchet）全绿
- [ ] E2E smoke：本地 dev 启动桌面端，手工点一遍记忆库：
  - 使用提示显示/折叠 ✓
  - 来源会话标题显示（如"↳ 「用户配置偏好」· 3 天前"） ✓
  - 质量条颜色分级（绿/黄/红） ✓
  - 选多条低质量记忆批量删除 ✓
  - 👍 / 👎 反馈提交 ✓
- [ ] 用户 merge PR
- [ ] 清理 feature 分支
- [ ] 归档到 `docs/technical/` 新章节（编号取当前最大 +1，预计 §133）+ 更新 `docs/technical/README.md` 索引
- [ ] 删除本计划文档（按仓库规范：plan 归档后直接删除）

---

## 8. 预估工作量

| 步骤 | 预估时间 | 复杂度 |
|---|---|---|
| S1 | 5 min | 低 |
| S2 (scorer) | 30 min | 中（pydantic 2.x 适配） |
| S3 (feedback + migration) | 30 min | 中 |
| S4 (preference_labels) | 15 min | 低 |
| S5 (conflict.py) | 45 min | 高（193 行 additions 要仔细 merge） |
| S6 (extractor.py) | 45 min | 高（208 行 additions） |
| S7 (consolidation.py) | 10 min | 低 |
| S8 (manager.py sync path) | 30 min | 中 |
| S9 (routes + tests) | 60 min | 高（4 个新路由 + 3 个集成测试文件） |
| S10 (scheduler/evolution min-cut) | 30 min | 中（618 行差异里挑 20 行） |
| S11 (frontend) | 45 min | 中 |
| S12 (architecture baseline) | 15 min | 低 |
| S13 (PR + CI + merge) | 30 min + CI 时间 | 低 |
| **总计** | **~7 小时**（不含 CI 等待） | — |

建议拆成 2-3 个 PR 降低 review 成本：
- **PR A**：S2–S8（后端核心 + 单测）
- **PR B**：S9–S10（路由 + 集成测试 + scheduler min-cut）
- **PR C**：S11–S12（前端 + baseline）
