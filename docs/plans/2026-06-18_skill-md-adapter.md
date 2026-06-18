# 2026-06-18 — SKILL.md 适配层（v1）

> 完整设计文档见 `/home/fz/.claude/plans/federated-moseying-dusk.md`。
> 本文档是项目内精简镜像，按 `feature-development.md` 规则放在 `docs/plans/`，完工后并入技术手册并删除。

## 背景与目标

Sage 现有 4 个 Python 内置技能（`search` / `writer` / `coder` / `travel`）走 `BaseSkill` → `SkillRegistry` 自定义管道，与外部生态（Hermes Agent、OpenClaw、Claude Skills 都在用的 AgentSkills 开放规范 agentskills.io）不兼容。新增 opt-in 的 SKILL.md 适配层，让用户可以拖入 markdown 形式的技能包，与 4 个 builtin 共存。

## 涉及的文件与模块

**新建**：
- `backend/skills/skill_md/__init__.py`
- `backend/skills/skill_md/frontmatter.py`
- `backend/skills/skill_md/skill.py`
- `backend/skills/skill_md/loader.py`
- `backend/skills/skill_md/validation.py`
- `backend/tests/unit/test_skill_md_frontmatter.py`
- `backend/tests/unit/test_skill_md_skill.py`
- `backend/tests/unit/test_skill_md_loader.py`
- `backend/tests/integration/test_skill_md_integration.py`

**修改**：
- `backend/skills/__init__.py`
- `backend/adapters/out/skill/inproc.py`
- `backend/api/legacy_routes.py`
- `src/shared/api/api.ts`
- `src/widgets/skills/SkillCard.tsx`
- `docs/technical/24-skills-system.md`

## 技术方案

- 新增 `SkillMdHotLoader` 镜像 `backend/tools/skill.py::SkillHotLoader` 模式（哈希 + 目录遍历 + 热重载）
- 新增 `SkillMdSkill(BaseSkill)` 包装类，镜像 `backend/mcp/tool.py::McpTool` 的"单资源包装类"模式
- 解析 frontmatter 用现成 `pyyaml==6.0.1`（`requirements.txt:23`，照搬 `backend/main.py:41-48` 的 `yaml.safe_load` 模式）
- `InprocSkillAdapter.__init__` 末尾追加 try/except guarded 调用 `register_skill_md_skills` —— 现有测试不破坏
- 路由层 `_skill_to_dict` 扩展 4 个关键字参数；前端 `Skill` interface 加 5 个可选字段
- 路径遍历防御镜像 Rust 版 `validate_wiki_path`（`archive/src-tauri-2026-06-13-main-migration/src/wiki/util.rs:9-30`）

## 实施步骤

- [ ] M1 — Frontmatter 解析器（`frontmatter.py`）
- [ ] M2 — `SkillMdDocument` + `SkillMdSkill`（`skill.py`）
- [ ] M3 — 路径校验工具（`validation.py`）
- [ ] M4 — `SkillMdHotLoader` + `discover_skill_md_dirs`（`loader.py`）
- [ ] M5 — 接入 `__init__.py` + adapter（`backend/skills/__init__.py`、`backend/adapters/out/skill/inproc.py`）
- [ ] M6 — 端到端集成测试
- [ ] M7 — 路由序列化器扩展（`legacy_routes.py`）
- [ ] M8 — 前端接口扩展（`api.ts` + `SkillCard.tsx`）
- [ ] M9 — 前端测试（vitest）
- [ ] M10 — 文档收尾
- [ ] M11 — 端到端验证（pytest + tsc + vitest + cargo check 全绿）

## 风险评估与依赖

- **依赖**：现有 `pyyaml==6.0.1` 已在 `requirements.txt:23`，无需新增依赖
- **风险 1**：SKILL.md body 含恶意 prompt injection — 由聊天层当作 system message 处理，文档化在 `24-skills-system.md`
- **风险 2**：路径遍历（`{baseDir}` 占位符滥用）— `validate_base_dir` 强制 base_dir 必须落在允许根
- **风险 3**：builtin 名字冲突（用户拖入 `name: search` 的 SKILL.md）— loader 跳过并记 WARNING
- **风险 4**：TypeScript `exactOptionalPropertyTypes` — 路由层 `_skill_to_dict` 在值为 None 时省略 key
- **不在范围**：`scripts/*.py` 执行、`references/`、`assets/`、`templates/`、gating 字段（v2 再做）