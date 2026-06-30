# AgentSkills.io Spec Conformance Design

> **状态**: Design (待用户审核)
> **日期**: 2026-06-29
> **作者**: Claude (brainstorming)
> **目标分支**: main
> **影响模块**: `backend/skills/skill_md/`

## 背景与目标

### 背景

[AgentSkills.io](https://agentskills.io/) 是一个**跨 AI agent 工具的"技能"格式规范**。规范定义：

- 技能是包含 `SKILL.md` 文件的目录（必填 `SKILL.md` + 可选 `scripts/`、`references/`、`assets/`）
- `SKILL.md` 含 YAML frontmatter（`name` 必填、`description` 必填，外加可选 `license` / `compatibility` / `metadata` / `allowed-tools`）
- `name` 必须匹配父目录名
- `description` 1-1024 字符，含触发关键词
- 渐进式披露：metadata (~100 tokens) → instructions (<5000 tokens) → 资源按需加载

sage 项目的 `backend/skills/skill_md/` 模块在 2026 上半年已经实现了"SKILL.md 风格"系统，含 v1（基础解析/加载）和 v2（资源/门控/脚本执行）。但**未完全对齐 agentskills.io 规范**：缺失 3 个可选字段、未强制 name 父目录名约束、未支持单文件形态。

### 目标

让 `backend/skills/skill_md/` **完全符合** [agentskills.io 规范](https://agentskills.io/specification) 的必填字段 + 可选字段语义，**同时保留 sage 全部业务扩展**（`triggers` / `os` / `requires` / `always` / `command-dispatch` / `disable-model-invocation` / `user-invocable` / `templates/`）。

### 非目标

- 不改 `backend/agents/` 模块
- 不改 `src/widgets/skills/` 前端模块
- 不改 builtin skills（`backend/skills/builtin/`）
- 不引入新依赖（继续用 `pyyaml==6.0.1`）
- 不改 release 流程（独立 PR 后续触发 release）

## 当前状态

### 已有实现

| 文件 | 状态 | 角色 |
|---|---|---|
| `backend/skills/skill_md/__init__.py` | ✅ | 包导出 |
| `backend/skills/skill_md/frontmatter.py` | ✅ | YAML frontmatter 解析（v1+v2） |
| `backend/skills/skill_md/skill.py` | ✅ | `SkillMdDocument` / `SkillMdSkill` |
| `backend/skills/skill_md/loader.py` | ✅ | 热加载器（v1+v2 gating） |
| `backend/skills/skill_md/validation.py` | ✅ | 路径遍历防御 + 日志脱敏 |
| `backend/skills/skill_md/resources.py` | ✅ | v2 资源索引（scripts/references/assets/templates） |
| `backend/skills/skill_md/gating.py` | ✅ | v2 门控（requires/os/always） |
| `backend/skills/skill_md/sandbox.py` | ✅ | 脚本执行沙箱 |
| `backend/skills/skill_md/script_runner.py` | ✅ | v2 脚本执行器 |
| `backend/skills/skill_md/confirm.py` | ✅ | 用户确认 port |
| `backend/skills/skill_md/slash_registry.py` | ✅ | 斜杠命令注册 |

### 与 agentskills.io 规范的差距

| 规范要求 | sage 当前 | 状态 |
|---|---|---|
| `name` 1-64 字符 + 小写字母数字连字符 | ✅ slug 校验 | 兼容 |
| `name` 必须匹配父目录名 | ❌ 未强制 | **缺失** |
| `description` 1-1024 字符 | ❌ 无长度限制 | **缺失** |
| `description` 含触发关键词 | ❌ 未要求 | **缺失** |
| `license` 字段 | ❌ | **缺失** |
| `compatibility` 字段 (≤500 字符) | ❌（有 `os` 字段，语义不同） | **缺失** |
| `allowed-tools` 字段（实验性） | ❌ | **缺失** |
| 单文件 `<dir>/SKILL.md` 形态 | ❌ 只支持目录 | **缺失** |
| `scripts/` / `references/` / `assets/` | ✅ | 兼容 |
| `metadata` 字段 | ✅ | 兼容 |
| 渐进式披露 | 部分（body 已实现，资源按需未明确） | 部分 |

### sage 业务扩展（保留）

| 字段 | 用途 |
|---|---|
| `triggers` | 多触发词数组（默认 `[name.lower()]`） |
| `requires` | 前置依赖（bins / env / config） |
| `os` | 平台过滤（macos / linux / windows） |
| `always` | 跳过条件加载 |
| `command-dispatch` | 调度模式（auto / tool / prompt） |
| `disable-model-invocation` | 禁止 agent 自动调用 |
| `user-invocable` / `user-invocable-name` | 用户斜杠命令注册 |
| `templates/` 目录 | 模板资源（sage 扩展） |

## 技术方案

### 1. 架构与改动点

**改动文件**（共 3 个）：

```
backend/skills/skill_md/
├── frontmatter.py    ← 改: 加 3 个 _validate_*, 强化 _validate_name (≤64) /
│                       _validate_description (≤1024 + 关键词 warning)
├── skill.py          ← 改: SkillMdDocument 加 3 字段 (license/compatibility/allowed_tools)
└── loader.py         ← 改: 加 name==parent_dir.name warning,
                        加 allowed_tools 解析, 支持 dir/SKILL.md 单文件形态
```

**未改动**：`validation.py` / `resources.py` / `gating.py` / `sandbox.py` / `script_runner.py` / `confirm.py` / `slash_registry.py` / `__init__.py`

**改动点编号清单（10 个）**：

| # | 文件 | 函数 | 行为 |
|---|---|---|---|
| 1 | `frontmatter.py` | `_validate_name` | 加 `len(name) ≤ 64` 校验 |
| 2 | `frontmatter.py` | `_validate_description` | 加 `len(description) ≤ 1024` 校验 + 触发关键词 warning |
| 3 | `frontmatter.py` | 新增 `_validate_license` | 可选，字符串 |
| 4 | `frontmatter.py` | 新增 `_validate_compatibility` | 可选，≤500 字符 |
| 5 | `frontmatter.py` | 新增 `_validate_allowed_tools` | 可选，字符串 |
| 6 | `frontmatter.py` | `parse` | 在 v2 字段区后加 3 个新调用 |
| 7 | `skill.py` | `SkillMdDocument` | 加 `license: str \| None`、`compatibility: str \| None`、`allowed_tools: tuple[str, ...]` |
| 8 | `loader.py` | `_load_from_path` | 加 `name != path.parent.name` 时 logger.warning（不阻断）+ 解析 `allowed-tools` |
| 9 | `loader.py` | `scan_and_load` | 加 `dir / "SKILL.md"` 单文件形态扫描 |
| 10 | `loader.py` | 构造 `SkillMdDocument` | 传新 3 字段 |

### 2. 新字段语义与校验

#### 2.1 `license`（可选）

```yaml
license: MIT
```

- 类型：`str | None`
- 长度：无硬限制（SPDX identifier 通常 < 32 字符）
- 校验：仅当提供时必须为非空字符串
- 默认：`None`
- 持久化：`SkillMdDocument.license`

#### 2.2 `compatibility`（可选，≤500 字符）

```yaml
compatibility: "Requires Python 3.10+, network access for OpenAI API"
```

- 类型：`str | None`
- 长度：**≤ 500 字符**（规范硬约束）
- 校验：`len(value) <= 500`，超出抛 `SkillMdParseError`
- 默认：`None`
- 持久化：`SkillMdDocument.compatibility`

**与 sage `os` 字段关系**：
- 规范 `compatibility` 是**自由文本**（环境需求说明）
- sage `os` 是**枚举**（`macos` / `linux` / `windows`，平台过滤）
- **不合并**：两者职责不同。`os` 仍走门控（gating），`compatibility` 仅展示给 agent

#### 2.3 `allowed-tools`（可选，空格分隔字符串）

```yaml
allowed-tools: "Bash Read Write Edit Glob Grep"
```

- 解析：`.split()` 空格分隔；过滤空串；保持顺序
- 持久化：`SkillMdDocument.allowed_tools: tuple[str, ...] = ()`
- 用途：**预留**——当前 sage 不强制使用，但记录下来供未来工具网关（tool gateway）层做权限预审

#### 2.4 `name` 长度约束（强化现有）

```python
# _validate_name 加强
if not (1 <= len(name) <= 64):
    raise SkillMdParseError(
        f"frontmatter 'name' must be 1-64 chars, got {len(name)} chars: {name!r}"
    )
```

#### 2.5 `description` 长度 + 关键词约束（强化现有）

```python
# _validate_description 加强
if not (1 <= len(description) <= 1024):
    raise SkillMdParseError(
        f"frontmatter 'description' must be 1-1024 chars, got {len(description)} chars"
    )

# Warning: 建议含触发关键词
_TRIGGER_HINTS = ("use this", "when ", "use ", "用", "何时", "用来")
if not any(h in description.lower() for h in _TRIGGER_HINTS):
    logger.warning(
        "SKILL.md '%s' description lacks trigger keywords; "
        "agents may not recognize when to invoke this skill",
        name,
    )
```

#### 2.6 `name` 匹配父目录名（仅 warning，loader 层）

```python
# loader._load_from_path 末尾、registry.register 之前
parent_name = path.parent.name
if name != parent_name:
    logger.warning(
        "SKILL.md at %s declares name='%s' but parent dir is '%s'; "
        "agentskills.io spec recommends name matches parent dir",
        path, name, parent_name,
    )
```

**不阻断理由**：sage 历史 SKILL.md 经常把 `name` 写成 `coder-search` 而目录叫 `search`，强阻断会破坏所有现存 skill。给 warning 让生态工具可识别"不完全合规"，但保留业务灵活性。

### 3. 文件形态与加载器

**两种文件形态**：

```
skills/
├── search/                    # 形态 A: 目录 (v1 已有, 默认)
│   ├── SKILL.md
│   ├── scripts/
│   ├── references/
│   └── assets/
└── _root_skills/              # 形态 B: 单文件 (v1.1 新增)
    └── SKILL.md               # name 必须是 frontmatter.name,
                               # parent dir 名("_root_skills") 与 name 不一致 → warning
```

**加载逻辑**（loader.py `scan_and_load` 改造）：

```python
def scan_and_load(self) -> tuple[int, int]:
    loaded, skipped = 0, 0
    for d in self._dirs:
        if not d.is_dir():
            continue
        # 形态 A: 子目录形态 <dir>/<name>/SKILL.md
        for entry in sorted(d.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            skill_md = entry / "SKILL.md"
            if skill_md.is_file() and self._load_from_path(skill_md):
                loaded += 1
            elif skill_md.is_file():
                skipped += 1
        # 形态 B: 单文件形态 <dir>/SKILL.md
        root_skill_md = d / "SKILL.md"
        if root_skill_md.is_file():
            if self._load_from_path(root_skill_md):
                loaded += 1
            else:
                skipped += 1
    if loaded:
        logger.info("SkillMd scan: %d loaded, %d skipped", loaded, skipped)
    return loaded, skipped
```

**关键点**：
- 单文件形态下，`path.parent.name` 是 skills 根目录名，与 frontmatter `name` 必然不一致 → 触发**预期内 warning**（不是错误）
- 命名冲突：单文件形态与子目录形态可能冲突 → `loader._load_from_path` 的 `registry.exists(name)` 防御已覆盖
- 优先级：单文件形态**后**扫，子目录形态优先（符合 v1 行为）
- builtin 名称 > 子目录 SKILL.md > 单文件 SKILL.md（沿用 v1 优先级）

### 4. 错误处理

| 错误类型 | 处理 | 用户感知 |
|---|---|---|
| 必填字段缺失（`name` / `description`） | `SkillMdParseError` → loader skip + WARNING | skill 加载失败，日志清楚 |
| `name` 不是 slug 或长度超限 | `SkillMdParseError` → skip | 同上 |
| `description` 长度 > 1024 | `SkillMdParseError` → skip | 同上 |
| `compatibility` 长度 > 500 | `SkillMdParseError` → skip | 同上 |
| `name` != parent_dir.name | **WARNING**（不阻断） | skill 加载成功，生态工具可识别"不规范" |
| description 缺触发关键词 | **WARNING**（不阻断） | 同上 |
| builtin 名称冲突 | skip + WARNING（v1 行为） | 沿用 |
| YAML 语法错 | `SkillMdParseError` 包装 | 沿用 |
| 路径遍历 | `SkillMdSecurityError` | 沿用 |

### 5. 向后兼容矩阵

| 现有 SKILL.md | 新行为 | 兼容性 |
|---|---|---|
| 无 `license` | 加载成功，doc.license = None | ✅ 完全兼容 |
| 有 `license: MIT` | 加载成功，doc.license = "MIT" | ✅ 新能力 |
| `description` < 1024 字符 | 加载成功 | ✅ 完全兼容 |
| `description` > 1024 字符（极端） | skip + WARNING | ⚠️ 罕见，需要修复 |
| `name` 与父目录名不一致 | 加载成功 + WARNING | ✅ 完全兼容（仅 warning） |
| 目录形态 `<dir>/<name>/SKILL.md` | 加载成功 | ✅ 完全兼容 |
| 单文件形态 `<dir>/SKILL.md`（如有） | 加载成功 | ✅ 新能力 |
| 无 `allowed-tools` | 加载成功，doc.allowed_tools = () | ✅ 完全兼容 |
| 有 `allowed-tools: "Bash Read"` | 加载成功，doc.allowed_tools = ("Bash", "Read") | ✅ 新能力 |
| 全部 8 个 sage 扩展字段 | 行为不变 | ✅ 完全兼容 |

**回滚策略**：所有改动为前向兼容（仅追加），回滚 = `git revert <merge-commit>`，无副作用。

## 实施步骤

### 阶段 1: frontmatter.py 验证增强（独立提交）

- [ ] 加 `name` 长度 ≤ 64 校验
- [ ] 加 `description` 长度 ≤ 1024 校验
- [ ] 加 `_validate_license` / `_validate_compatibility` / `_validate_allowed_tools`
- [ ] 在 `parse()` 接入 3 个新验证
- [ ] 单元测试 14 个全过

### 阶段 2: skill.py 数据类扩展（独立提交）

- [ ] `SkillMdDocument` 加 3 字段
- [ ] dataclass 默认值：`license=None` / `compatibility=None` / `allowed_tools=()`
- [ ] 单元测试 3 个全过

### 阶段 3: loader.py 加载器增强（独立提交）

- [ ] `_load_from_path` 加 `name != parent_dir.name` warning
- [ ] `_load_from_path` 构造 `SkillMdDocument` 传新 3 字段
- [ ] `_load_from_path` 解析 `meta["allowed-tools"]` 为 tuple
- [ ] `scan_and_load` 加 `dir / SKILL.md` 单文件形态扫描
- [ ] 集成测试 10 个全过

### 阶段 4: E2E + 文档（独立提交）

- [ ] `tests/electron/skillmd-compliance.spec.ts` 新增
- [ ] `docs/technical/XX-skill-md-spec-conformance.md` 新增
- [ ] `docs/technical/07-skills.md` 增量更新引用
- [ ] CHANGELOG.md 增量条目

## 测试策略

### 单元测试（30+）

`backend/tests/skills/skill_md/test_frontmatter.py` 新增：

- `test_name_at_max_length_64`
- `test_name_over_max_length_raises`
- `test_description_at_max_length_1024`
- `test_description_over_max_length_raises`
- `test_license_optional`
- `test_license_non_empty_string`
- `test_compatibility_under_500_chars`
- `test_compatibility_over_500_raises`
- `test_allowed_tools_space_separated`
- `test_allowed_tools_empty_string`
- `test_allowed_tools_extra_spaces`
- `test_description_with_trigger_keyword_passes_silently`
- `test_description_without_trigger_keyword_warns`
- `test_full_spec_compliant_frontmatter`

### 集成测试（10+）

`backend/tests/skills/skill_md/test_loader_compliance.py`（新文件）：

- `test_load_directory_form_skill_md`
- `test_load_single_file_form_skill_md`
- `test_load_with_license_field`
- `test_load_with_compatibility_field`
- `test_load_with_allowed_tools_field`
- `test_name_mismatch_with_parent_dir_warns`
- `test_overlong_description_skips_skill`
- `test_overlong_compatibility_skips_skill`
- `test_existing_skills_still_load_compatible`
- `test_no_license_field_loaded_as_none`

### E2E 烟雾测试（1-2）

`tests/electron/skillmd-compliance.spec.ts`（新文件）：

- `agent_skills_compliant_skill_loads_in_chat`

### 回归测试

- 跑现有 `backend/tests/skills/skill_md/test_*.py` 全部 80+ 测试，零回归
- 跑 `backend/tests/skills/test_registry.py` / `test_base.py`
- 跑 `vitest` 确认前端 skills 模块未受影响

### 覆盖率目标

| 模块 | 当前 | 目标 |
|---|---|---|
| `frontmatter.py` | ~95% | ≥ 95% |
| `skill.py`（新字段） | — | 100% |
| `loader.py`（新形态 + 校验） | — | ≥ 85% |

### DoD（完成定义）

- [ ] 30+ 新单测全过
- [ ] 10+ 新集成测试全过
- [ ] 现有 80+ skill_md 单测零回归
- [ ] builtin 技能全部加载正常
- [ ] `pytest --cov` 显示新字段 100% 覆盖
- [ ] 至少 1 个 E2E 烟雾测试过
- [ ] 文档 + CHANGELOG 已更新

## 风险评估

| 风险 | 等级 | 缓解 |
|---|---|---|
| 现有 SKILL.md description > 1024 字符 | 低 | 极罕见；如发生，可临时 warning 而非 error |
| 现有 SKILL.md compatibility 字段未来超 500 字符 | 极低 | sage 尚无此字段，未来如需可加新字段 |
| 加载器支持单文件形态引入新 bug | 低 | 优先级：子目录形态优先；命名冲突靠 registry.exists 防御 |
| 触发关键词 warning 噪音过大 | 低 | 仅 warning，不阻断；CI/开发可忽略 |
| 改动 `frontmatter.py` 影响 builtin skills | 低 | builtin 走 `backend/skills/builtin/`，不经过 `skill_md/loader` |

## 文档更新

- 新建 `docs/technical/XX-skill-md-spec-conformance.md`：规范对齐说明 + 新字段参考 + 迁移示例
- 更新 `docs/technical/07-skills.md`：在 "SKILL.md 适配层" 章节加新字段小节
- 更新 `CHANGELOG.md`：在 Unreleased 段加 `feat(skills): conform to agentskills.io spec (license/compatibility/allowed-tools)`

## 依赖与约束

- **Python 环境**：所有改动必须在 `sage-backend` conda 环境（`/home/fz/anaconda3/envs/sage-backend`）内运行测试
- **测试命令**：
  ```bash
  conda activate sage-backend && \
    /home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
    backend/tests/skills/skill_md/ -v --cov=backend/skills/skill_md
  ```
- **新依赖**：无（继续用 `pyyaml==6.0.1`）
- **release/win7 分支**：不主动同步到 LTS；如后续需要可 cherry-pick

## 后续可能性（非本次范围）

- 把 `allowed-tools` 接入到 tool gateway 层做权限预审
- 编写 `SKILL.md` 校验 CLI 工具（`sage skills lint`）
- 在 `docs/user-manual/` 增加"如何为 sage 写 SKILL.md"教程
- 与 `release/win7` 同步（如有跨分支安全修复）
