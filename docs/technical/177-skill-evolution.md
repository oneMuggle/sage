# 技能整理优化与去重进化机制

> 2026-11-25（对应 PR #3299 主实现 / #3304 win7 同步）。为技能系统引入四个递进层次：**结构化去重（M1）→ 质量评分与分层（M2）→ 渐进式发现（M3）→ 执行反馈自进化（M4）**。对标 Claude Tool Search 的延迟加载、LangChain Progressive Disclosure、GATE 图演化、SkillFocus 能力演化与 BabyAGI 反思循环，同时保留 Sage「建议 → 人工批准」的可审计契约。

---

## 1. 背景与问题

改造前技能系统已有生命周期三态（active/stale/archived）、LLM 巡检（`consolidator.py` 产出 merge/archive/revise 建议）、审计台账与 pin，但存在五个缺口：

| # | 缺口 | 影响 |
|---|------|------|
| P1 | 去重纯靠 LLM 文本分析 | 准确率依赖 prompt 质量，无结构化证据 |
| P2 | 无多维质量评分 | 只有原始 `use_count`，无成功率/满意度/新鲜度 |
| P3 | 技能全量注入上下文 | 技能增多后 token 浪费，选型准确率下降 |
| P4 | 巡检建议后全靠人工发现 | 无执行反馈驱动的闭环 |
| P5 | 无渐进式加载 | 完整 SKILL.md 一次性加载 |

---

## 2. M1 结构化去重

**模块**：`backend/skills/similarity.py` — `SkillSimilarityService`

- 向量化输入：`description + when_to_use + triggers` 拼接
- 首选 embedding：复用项目既有 embedding HTTP 端点（`wiki/embeddings.py` 的 `build_embed_request` / `parse_embed_response`），余弦相似度（纯 Python，维度不符返回 0）
- 降级：embedding 不可用或全部失败 → TF-IDF（sklearn，`importorskip` 语义）；sklearn 未安装返回空列表
- 阈值：默认 `0.85`；embedding 向量 LRU 缓存（`EMBEDDING_CACHE_SIZE=200`）
- 接入：`ConsolidationService.scan()` 新增 `similarity_service` 可选参数——预筛结果作为「先验证据」注入 LLM prompt，merge 建议附加 `similarity_evidence` 字段。API 路由与定时调度器均已传入

---

## 3. M2 质量评分与热/冷分层

**模块**：`backend/skills/scoring.py` — `SkillScoringService`

综合评分（0–100，权重可用 `SAGE_SKILL_SCORING_WEIGHTS="key=val,..."` 覆盖）：

```
overall = 0.30*usage_freq + 0.25*success_rate + 0.20*satisfaction
        + 0.15*freshness + 0.10*description_quality
```

| 维度 | 计算 |
|------|------|
| usage_freq | `use_count / max(all use_counts) * 100` |
| success_rate | `success_count / (success+fail) * 100`，无数据默认中性 50 |
| user_satisfaction | 暂无显式反馈，以成功率近似 |
| freshness | 指数衰减（半衰期 14 天）；从未使用 0 |
| description_quality | 规则评估：描述≥20 字 +40、when_to_use≥30 字 +40、含动作动词 +20 |

**分层**：`hot`（overall≥70 且 7 天内有使用）/ `warm`（overall≥40 或 30 天内有使用）/ `cold`。评分结果内存缓存 1 小时。

---

## 4. M3 渐进式发现

**模块**：`backend/skills/progressive_loader.py` — `ProgressiveSkillLoader`

三级加载（借鉴 LangChain Progressive Disclosure）：

| 级别 | 内容 | 时机 |
|------|------|------|
| Level 1 | name + description + triggers | 会话启动注入 |
| Level 2 | 完整 SKILL.md body | 技能被选中 |
| Level 3 | scripts/ references/ | 执行时按需 |

- `build_context()`：按 M2 分层在 token 预算（默认 2000）内生成摘要——hot 行含触发词、warm 行仅名称+描述、超预算截断；cold 只计数
- `search_cold_skills()`：关键词匹配（中文整词 + 前缀近似）实现冷路径按需检索
- `load_full_skill()`：Level 2 加载

---

## 5. M4 执行反馈自进化

**模块**：`backend/skills/evolution.py` — `SkillFeedbackStore` + `SkillEvolutionService`

- **反馈采集**：`record(skill_name, {success, error, user_thumbs, token_cost})`；聚合出 `use_count / success_count / fail_count / user_satisfaction / avg_token_cost`
- **触发条件**（任一）：
  - 成功率 < 60% 且执行次数 ≥ 5 → `low_success_rate`（建议 `revise_content`）
  - 满意度 < 50% 且执行次数 ≥ 10 → `low_satisfaction`（建议 `revise_description`）
- **产出**：`EvolutionProposal{skill_name, trigger, evolution_type, reason, stats}`，走审计台账 → 前端面板人工批准/拒绝
- 当前 `SkillFeedbackStore` 为**内存实现**（进程重启丢失），SQLite 持久化待后续迭代

---

## 6. API 与前端

| 端点 | 用途 |
|------|------|
| `GET /skills/scores` | 全量技能评分 |
| `GET /skills/{name}/score` | 单技能评分 |
| `GET /skills/context` | 渐进式上下文摘要（hot/warm/cold 计数 + token 估算） |
| `POST /skills/search?query=&top_k=` | 技能搜索（含冷路径） |
| `POST /skills/evolution/check?skill_name=` | 进化检查（空参数 = 全量） |
| `POST /skills/feedback` | 记录执行反馈（`SkillFeedbackBody`） |

Electron：`electron/commandRoutes/skills.ts` 注册 6 条 IPC（`skills_scores` / `skill_score` / `skills_context` / `skills_search` / `skills_evolution_check` / `skills_feedback`），改动后需重跑 `npm run ipc:manifest`。

前端：`skillsApi.getScores/getScore/getContext/searchSkills/checkEvolution/recordFeedback`；组件 `SkillScoreBadge`（绿/黄/灰分层徽章）与 `SkillEvolutionPanel`（审阅/批准/拒绝面板）已交付，**尚未挂载到技能页**（集成留待后续）。

---

## 7. 测试与验证（win7 / py38）

- 新增 60 个后端单测（similarity 16 / scoring 22 / progressive 10 / evolution 12）；既有 26 个 consolidator 测试不受影响
- py38 环境：86 通过，3 skipped（sklearn 未装，TF-IDF 降级路径被跳过）
- win7 适配：新代码全部使用 `from __future__ import annotations`，无 3.8 不兼容语法；pydantic v1 兼容（纯 typing 注解）
- CI 坑位：新 IPC 命令必须重跑 manifest（ipc-contract 门禁）；`backend/scheduler/evolution.py` 增长需按棘轮更新基线（win7 2670）；函数内 import 块也受 ruff I001 检查

---

## 8. 待办

- [ ] `SkillFeedbackStore` 持久化到 SQLite
- [ ] `SkillScoreBadge` / `SkillEvolutionPanel` 挂载到技能页（`SkillCard` / `Skills.tsx`）
- [ ] 进化批准后自动修订 SKILL.md（接入既有 draft-approve 流程）
- [ ] 冷路径搜索升级为 BM25/embedding（当前为关键词匹配）
