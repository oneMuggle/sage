# Design Studio 内容库与 Craft 工艺规范

> 代码位置：`backend/design/`
> 内容位置：`backend/design/content/`

## 1. 架构总览

Design Studio 采用 **四平面可组合架构**：

| 平面 | 内容 | 加载器 |
|------|------|--------|
| 设计系统 | `content/systems/<id>/{manifest.json,DESIGN.md,tokens.css}` | `DesignSystemRegistry` |
| 模板 | `content/templates/<kind>/<id>/SKILL.md`（+ 可选 `example.html` / `assets/`） | `DesignTemplateRegistry` |
| 工艺规范 | `content/craft/*.md` | `CraftRuleRegistry` |
| 生成 | `PromptComposer` → `DesignGenerator` → `StandaloneBundler` | — |

`kind` 取值为 `prototype`（Web 原型）或 `deck`（幻灯片）。

## 2. Prompt 组装顺序

`PromptComposer.compose()` 按下列顺序拼接：

1. 基础指令（输出 `<artifact>` 包裹的完整 HTML）
2. 品牌设计规范（`DESIGN.md`）
3. CSS 变量（`tokens.css`）
4. 模板生成指令（`SKILL.md`）
5. **工艺规范（`## 工艺规范（必须遵守）`）** — 按 `priority` 升序逐个注入
6. 用户需求（brief）
7. 迭代上下文（仅 `iterate` 时追加当前 HTML + 用户反馈）

Craft 段仅在传入 `craft_rules` 时出现；未传入时 prompt 与旧版逐字一致。

## 3. Craft 规则格式

```markdown
---
id: anti-ai-slop
name: Anti-AI-Slop
description: Reject the visual tells of machine-generated design.
applies_to: both        # both | prototype | deck
priority: 0             # 升序注入
---

# 正文（Markdown）
```

`CraftRuleRegistry.rules_for_kind(kind)` 返回 `applies_to` 为 `both` 或等于该 kind 的规则，并按 `priority` 升序排列。

内置 5 条规范：

| id | 作用 |
|----|------|
| `anti-ai-slop` | P0 拒绝项：默认 indigo、信任渐变、emoji 图标、捏造指标 |
| `typography-hierarchy` | 乘法字阶、字重对比、行高与字距 |
| `color-usage` | 70-20-10 结构、强调色节制、对比度下限 |
| `animation-discipline` | 动效何时成立、时长与缓动、`prefers-reduced-motion` |
| `checklist` | 交付前 P0/P1/P2 自检清单 |

## 4. 注入链路

```
main.py (lifespan)
  └─ CraftRuleRegistry(content_dir)
       └─ DesignStudio(craft_rules=registry)
            ├─ _craft_for(template) → registry.rules_for_kind(template.kind)
            └─ DesignGenerator.generate(..., craft_rules=rules)
                 └─ PromptComposer.compose(..., craft_rules=rules)
```

`craft_rules` 参数在 `DesignStudio` / `DesignGenerator` / `PromptComposer` 三处均为可选，默认 `None`，因此现有调用方与测试无需改动。

## 5. 健壮性约定

- 单个 craft 文件不可读（非 UTF-8 / IO 错误）→ 跳过该文件，不抛异常。
- frontmatter `priority` 非整数（如 `high`）→ 回退为 `99`（排在最后）。
- 多个文件的 frontmatter `id` 重复 → 以 `id` 去重，只保留一个。
- 正文开头的 H1 若重复 `name` 会被剥离，避免 prompt 中出现重复标题。
- 空 frontmatter（`---\n---`）→ 使用文件名 stem 作为 id。

## 6. 内容清单（2026-11-11 扩充后）

| 类型 | 数量 | 条目 |
|------|------|------|
| 设计系统 | 7 | corporate, minimal, editorial, tech-dark, academic, startup, data-report |
| Deck 模板 | 5 | pitch-deck, editorial-magazine, swiss-grid, tech-sharing, weekly-report |
| 原型模板 | 4 | landing-page, dashboard, pricing, docs-page |
| Craft 规范 | 5 | 见上表 |

## 7. 扩展方式

- **新增设计系统**：在 `content/systems/<id>/` 放置 `manifest.json`（含 `id/name/category/description/tags`）+ `DESIGN.md` + `tokens.css`，无需改代码。
- **新增模板**：在 `content/templates/<kind>/<id>/` 放置 `SKILL.md`（frontmatter 必含 `name/kind/description/design_system_required`），可选 `example.html` 与 `assets/*.css|*.js`。
- **新增 craft 规则**：在 `content/craft/` 放置 `<id>.md`，frontmatter 必含 `id/name/applies_to/priority`。正文会整体进入 prompt，建议单文件 < 2KB；若某规则只适用于某类产物，用 `applies_to: deck|prototype` 缩小注入面。

## 8. 测试

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_craft_loader.py \
  backend/tests/unit/test_prompt_composer.py \
  backend/tests/unit/test_design_generator.py \
  backend/tests/unit/test_design_studio.py \
  backend/tests/unit/test_design_routes.py \
  backend/tests/unit/test_design_tools.py -q
```

`test_craft_loader.py` 覆盖：frontmatter 解析、缺省/空 frontmatter 回退、非法与带引号的 priority、H1 去重、按 priority 排序、缺失目录、按 kind 过滤、不可读文件跳过、id 去重、缓存行为。

## 9. 来源说明

系统/模板/craft 内容为原创撰写，遵循 OpenDesign 的四平面架构模式，未逐字复制其文本，故未附加 Apache 2.0 NOTICE。
