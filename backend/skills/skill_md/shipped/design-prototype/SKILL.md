---
name: design-prototype
description: 生成 HTML/CSS 原型页的完整工作流——设计系统与模板的显式选择、建项目与首版生成、以用户反馈为驱动力的多轮迭代、产物导出。当用户要做落地页、官网原型、后台界面、产品界面草图、网页 mockup 时使用。
license: Apache-2.0
compatibility: 需要 design 工具面（design_list_systems / design_list_templates / design_generate / design_iterate / design_export），且 DesignStudio 已初始化
when_to_use: 当用户要做一个网页原型、落地页、landing page、官网首页、产品界面草图、后台界面 mockup，或用"做个页面看看""搭个原型""设计个首页""画个界面"等表达时使用
allowed-tools: design_list_systems design_list_templates design_generate design_iterate design_export read_file todo_write ask_user_question
triggers: []
---

# HTML/CSS 原型页生成

> shipped 基础版。`triggers` 留空——靠 `when_to_use` 语义判断激活。
> 与 ppt-making 的分工：ppt-making 管 `.pptx` 演示文稿；本技能管 **HTML/CSS
> 原型页**。两者的 `kind` 分别是 `prototype` 与 `deck`，不可混用。

## 触发条件

- "给我们的 SaaS 做个落地页原型"
- "搭一个产品官网首页，先看看效果"
- "这个后台管理系统长什么样，出个原型"
- "按之前聊的三个板块设计一个活动页"（→ 三个板块直接进 brief）
- "把这份需求文档变成一个可看的界面草图"（→ 先 `read_file` 读需求再写 brief）

## 工具契约（先记住参数，勿凭直觉猜）

| 工具 | 参数 | 说明 |
|---|---|---|
| `design_list_systems` | 无 | 返回 `systems[]`：`id` / `name` / `description` / `category` |
| `design_list_templates` | 无 | 返回 `templates[]`：`id` / `name` / `kind` / `description`；**工具本身不接过滤参数**，`kind` 要在返回值里自行筛 |
| `design_generate` | `name`、`kind`、`system_id`、`template_id`、`brief` —— **五个全必填** | 建项目 + 生成 v1；`kind` 固定 `"prototype"` |
| `design_iterate` | `project_id`、`feedback` | 基于最新产物生成下一个版本 |
| `design_export` | `project_id` —— 只有这一个参数 | 返回最新产物的 `html_content` 与 `file_path`；**没有 `format` 参数** |

漏掉任何必填参数返回 `missing_required_parameters`；模板 ID 不存在返回
`generation_failed`。系统 ID / 模板 ID **只能用 `design_list_systems` /
`design_list_templates` 返回值里的 ID，不要凭空编**。

## 工作流（五步）

### 1. 选设计系统（让用户选，不替他选）

`design_list_systems` 拉清单，把 `id` + `name` + `description` 原样列给用户，用
`ask_user_question` 请他挑。随包发布的是 `minimal` 与 `corporate`：

- `minimal` —— 中性、留白多，适合内容驱动或还没定型的产品；
- `corporate` —— 稳重、有明确栅格与层级，适合对外正式场合。

**不要**用户没表态就替他默认一个。设计系统决定整套配色 / 间距 / 字阶，
选错等于后面每一轮迭代都在错误的底座上返工。用户明确说"你定"时才自行决定，
并说明选了什么、为什么。

用户先甩了需求文档或竞品截图，就用 `read_file` 读进来，brief 里要引用得到。

### 2. 选模板 + 写 brief

`design_list_templates` 拉全量，在返回值里筛出 `kind == "prototype"` 的条目，
同样让用户选。两个决定合起来写成一份 `brief` 再进下一步，brief 至少覆盖：

- **页面形态**：落地页 / 首页 / 后台界面 / 表单页；
- **必备区块**（逐条列，例：Hero 主标题 + 副标题 + 主 CTA、三张特性卡、
  常见问题、页脚）——区块清单直接决定生成结果的结构；
- **主色或风格倾向**（用户给过才写，没给就不写，别硬编）；
- **响应式断点与移动端优先级**。

`template_id` / `system_id` 用刚才用户选的返回值，`name` 取项目主题
（例："SaaS 官网落地页 2026"）。多轮任务用 `todo_write` 建清单
（选系统 / 选模板 / 生成 / 迭代 / 导出）。

### 3. 首次生成

`design_generate` 一次性完成**建项目 + 出 v1**，没有单独的建项目步骤。
返回的 `project_id` 记下来，后续每一步都要它。

- 这是 LLM 阻塞调用，耗时长，返回前不要并发发别的工具；
- 返回 `artifact_version: 1` 与 `file_path`（产物落盘位置）；
- brief 越具体，第一次成稿越接近预期——首轮就写长 brief，
  不要靠"先出个大概再调"省事。

### 4. 迭代（正常路径，不是例外）

原型页**几乎不存在一次成稿**。用户看完 v1 给反馈是标准流程，不是需求没写清。

`design_iterate(project_id, feedback)` 基于最新产物出新版本，
`artifact_version` 递增，旧版本仍在可随时回看。反馈写法：

- 说清**位置 + 现状 + 期望**，例："首屏主标题字号偏小、右侧留白太多，
  希望标题更硬气，并把主 CTA 挪到副标题下方"；
- 一轮处理一个主题（区块顺序、配色、间距、文案语气分开轮次），
  多个主题并发会让每次修改都只改到一半；
- 用户说"再高级一点"这类模糊反馈，用 `ask_user_question` 追问方向，
  **不要**自己猜一个方向改五轮。

每次返回后把版本号与改动复述给用户，认可了再进下一轮。

### 5. 导出交付

用户认可后 `design_export(project_id)` 取最新产物，交付时给出：

- `file_path`（产物按 `design/<project_id>/v<N>.html` 落盘）；
- `html_content`——需要贴给用户或做后续处理时用这份；
- 当前版本号，并说明继续提反馈会走 `design_iterate` 生成新版本、旧版本保留。

## 不做的事（YAGNI）

- ❌ 不替用户默选设计系统或模板（用户明确授权除外）
- ❌ 不编造模板 ID 或系统 ID——只能用两个 list 工具的返回值
- ❌ 不在 brief 里编造数据、指标、客户名（缺失就问用户）
- ❌ 不给 `design_export` 传 `format`——该工具没有这个参数
- ❌ 不做演示文稿（`kind="deck"` 走 design-deck 技能）
- ❌ 不为"看起来更好"自行添加用户没要求的区块
