# Curator 第二块 — pin 防归档 + LLM 巡检建议 Round 5 实施计划

> 日期: 2026-09-11 · 分支: `feat/curator-pin-consolidation` · 基于 main @ b107effc
> 来源: hermes-agent 对标分析（curator 第二块：pin + consolidation review）
> Win7 对齐: 全部为**新功能**，不 cherry-pick 到 release/win7（31-win7-lts.md §2）。

## 背景

Round 3 落地了技能审计台账与单条回滚（「事后审计」安全网）。本批补
hermes curator 的两个判断能力：

1. **pin（防归档）**：用户钉住的高价值技能不被后台/自动流程归档
   （hermes: pin 不参与 stale→archived 流转）。
2. **LLM 巡检建议（consolidation）**：hermes 支持定期用 LLM 审阅全部
   agent-created 技能，发现**重复/过时**并给出合并/归档建议。
   Sage 版产出「建议」写入审计台账（不自动动文件），人工审阅后走
   既有 archive / draft-approve 流程——闭环仍以人工闸口收口。

## 批次任务

### A. pin（`backend/skills/lifecycle.py` SkillLifecycleStore）

- 独立表 `skill_pins(name PK, created_at)`（不动既有表结构）
- `set_pinned(name, pinned)` / `get_pinned_names()` / `is_pinned(name)`
- `POST /skills/{name}/pin` REST；`archive_skill` 路由对 pinned 技能
  归档请求返回 409 `skill_pinned`

### B. LLM 巡检（`backend/skills/consolidator.py` 新）

- `ConsolidationService(llm_provider, model)`：输入 active 技能清单
  （name/description/when_to_use/usage/stale 标记），LLM 输出 JSON 建议：
  `{type: merge|archive|revise, skill_names: [...], reason}`
- 建议写入 Round 3 审计台账（action 扩展 `consolidation_note`，
  append-only），**不自动动文件**——人工审阅后走既有 archive/approve
- pinned 技能永不进 archive 建议；LLM 不可用 → 503（复用
  ReviewService 的 provider 注入，不自建 LLM 面）
- REST：`POST /skills/consolidation/scan`（触发扫描）、
  `GET /skills/consolidation/suggestions`（读台账建议）

### C. 测试

- `backend/tests/unit/test_skill_pins.py`（pin 全链 + archive 409）
- `backend/tests/unit/test_consolidator.py`（LLM JSON 解析/建议落台账/
  pinned 排除/provider 缺失 503）

## Round 6 候选

- execute_code RPC 工具调用 / docker 沙箱后端
- 消息网关 Telegram MVP / hex-legacy 双栈收敛
