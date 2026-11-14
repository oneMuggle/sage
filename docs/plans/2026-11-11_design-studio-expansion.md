# Design Studio 能力扩充方案

> 日期：2026-11-11
> 分支：`feat/design-studio-expansion`
> 参考项目：`/home/fz/project/open-design`（Apache 2.0）

## 背景与目标

Sage 的 Design Studio（`backend/design/`）架构已与 OpenDesign 同构（DesignSystemRegistry + TemplateRegistry + PromptComposer + DesignGenerator + StandaloneBundler + DesignStudio 编排器），但内容库严重不足：

| 维度 | Sage 现状 | OpenDesign | 差距 |
|------|----------|------------|------|
| 设计系统 | 2（corporate/minimal） | 151 | 149 |
| Deck 模板 | 1（pitch-deck） | 36+ | 35+ |
| Web 原型模板 | 1（landing-page） | 10+ | 9+ |
| Craft 工艺规范 | 无 | anti-ai-slop 等 8 个 | 整层缺失 |
| 导出 | HTML only | HTML/PDF/PPTX/ZIP/MD | 缺 4 种 |

**目标**：分阶段扩充内容库 + 补全 Craft 层 + Deck 运行时协议，使 Design Studio 产出质量从"能看"提升到"品牌级"。

## 决策记录

1. **设计系统内容来源**：从 OpenDesign 移植（Apache 2.0 允许，保留署名）→ 逐步原创替换核心系统
2. **Deck 渲染**：统一到 Design Studio（HTML-first），.pptx 导出作为可选后处理
3. **前端入口**：后续在 Office 页或独立页面添加"设计工作室"入口（本方案不涉及 UI）

## 涉及的文件与模块

### 新增文件
- `backend/design/content/systems/editorial/` — 编辑/杂志风设计系统
- `backend/design/content/systems/tech-dark/` — 技术分享暗色风
- `backend/design/content/systems/academic/` — 学术论文/答辩风
- `backend/design/content/systems/startup/` — 创业路演风
- `backend/design/content/systems/data-report/` — 数据报告风
- `backend/design/content/templates/deck/editorial-magazine/` — 杂志风 deck
- `backend/design/content/templates/deck/swiss-grid/` — 瑞士国际风 deck
- `backend/design/content/templates/deck/tech-sharing/` — 技术分享 deck
- `backend/design/content/templates/deck/weekly-report/` — 周报 deck
- `backend/design/content/templates/prototype/dashboard/` — 仪表盘
- `backend/design/content/templates/prototype/pricing/` — 定价页
- `backend/design/content/templates/prototype/docs-page/` — 文档页
- `backend/design/content/craft/` — 工艺规范（5 个 .md 文件）
- `backend/design/craft_loader.py` — Craft 规范加载器

### 修改文件
- `backend/design/prompt_composer.py` — 注入 Craft 规范
- `backend/design/models.py` — Craft 相关模型
- `backend/design/__init__.py` — 导出 Craft loader

## 实施步骤

### Phase 1：设计系统扩充（5 个新系统）

- [x] 1.1 `editorial` — 衬线标题 + 大留白 + 编辑级排版
- [x] 1.2 `tech-dark` — 暗色背景 + 等宽字体 + 代码块友好
- [x] 1.3 `academic` — 学术论文/答辩风（serif + 保守配色）
- [x] 1.4 `startup` — 渐变 + 大胆排版 + 创业路演感
- [x] 1.5 `data-report` — 表格/图表优先 + 数据密度高

### Phase 2：Deck 模板扩充（4 个新模板）

- [x] 2.1 `editorial-magazine` — 10 版式池 + 5 调色板 + 键盘翻页
- [x] 2.2 `swiss-grid` — 网格锚定 + 单色点缀 + 国际风
- [x] 2.3 `tech-sharing` — 代码块 + 架构图 + 数据对比
- [x] 2.4 `weekly-report` — 数据卡 + 进度条 + 待办

### Phase 3：Web 原型模板扩充（3 个新模板）

- [x] 3.1 `dashboard` — KPI 仪表盘
- [x] 3.2 `pricing` — 定价对比页
- [x] 3.3 `docs-page` — 文档页（侧边栏 + 搜索 + 代码块）

### Phase 4：Craft 工艺规范层

- [x] 4.1 创建 `craft/` 目录 + 5 个规范文件
- [x] 4.2 实现 `craft_loader.py`
- [x] 4.3 修改 `prompt_composer.py` 注入 Craft 规范

### Phase 5：验证

- [x] 5.1 确认所有新系统/模板可被 Registry 发现
- [x] 5.2 确认 PromptComposer 正确组装含 Craft 的 prompt
- [x] 5.3 后端测试

## 实施结果（2026-11-11）

| 维度 | 扩充前 | 扩充后 |
|------|--------|--------|
| 设计系统 | 2 | **7**（+editorial/tech-dark/academic/startup/data-report） |
| Deck 模板 | 1 | **5**（+editorial-magazine/swiss-grid/tech-sharing/weekly-report） |
| Web 原型模板 | 1 | **4**（+dashboard/pricing/docs-page） |
| Craft 规范 | 0 | **5**（anti-ai-slop/typography/color/animation/checklist） |

**Craft 注入链路**：`CraftRuleRegistry(content/craft/*.md)` → `DesignStudio._craft_for(template)` 按 `template.kind` 过滤 → `DesignGenerator.generate(craft_rules=...)` → `PromptComposer.compose(craft_rules=...)` 生成「## 工艺规范（必须遵守）」段。

**内容来源**：所有系统/模板/craft 为原创撰写，遵循 OpenDesign 的四平面架构模式（Plugins/Skills/Design Templates/Design Systems），未逐字复制其文本，故无需附加 Apache 2.0 NOTICE。

**测试**：`backend/tests/unit/test_craft_loader.py`（6 例）+ `test_prompt_composer.py`（新增 2 例）全绿；`test_design_routes.py`/`test_design_tools.py`/`test_design_studio.py`/`test_design_generator.py` 全部通过（85 passed）。

## 风险评估

- **内容版权**：OpenDesign 使用 Apache 2.0，移植需保留 NOTICE 和署名。每个移植的系统/模板在 `manifest.json` 中标注来源。
- **质量风险**：移植的系统/模板需适配 Sage 的 PromptComposer 格式，不能直接照搬（OpenDesign 的 prompt 组合链更复杂）。
- **棘轮风险**：新增 .md 文件会增加 `PromptComposer` 拼装的 prompt 长度，需控制每个 Craft 文件 < 2KB。
