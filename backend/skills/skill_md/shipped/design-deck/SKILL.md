---
name: design-deck
description: 生成 HTML 幻灯片 deck 的完整工作流——先查可用模板、再定叙事节拍与设计系统、建项目生成首版、以叙事顺序或侧重为反馈多轮迭代、产物导出。当用户要做网页版幻灯片、在线 deck、演示页、路演/发布会页面时使用。
license: Apache-2.0
compatibility: 需要 design 工具面（design_list_systems / design_list_templates / design_generate / design_iterate / design_export），且 DesignStudio 已初始化；随包发布 `pitch-deck` 模板（kind="deck"）。design_* 五件套仅在 **coordinator（primary）** profile 的白名单里（backend/agents/profiles.py 的 DESIGN_TOOLS），子代理 profile 看不到这些工具——子代理被要求出 deck 时，交回主对话由本流程执行
when_to_use: 当用户要做网页版幻灯片、在线 deck、演示页、路演页面、发布会页面，或用"做个网页版的 slides""做成在线演示""做套网页 deck"等表达时使用
allowed-tools: design_list_systems design_list_templates design_generate design_iterate design_export read_file todo_write ask_user_question
triggers: []
---

# HTML 幻灯片 deck 生成

> shipped 基础版。`triggers` 留空——靠 `when_to_use` 语义判断激活。
> 与 ppt-making 的分工：ppt-making 产出 `.pptx` 文件走 Office 工具面；
> 本技能产出 **HTML 幻灯片**（`kind="deck"`），走 design 工具面。
> 与 design-prototype 的分工：landing page、后台界面等页面形态走
> design-prototype（`kind="prototype"`），不要用 deck 硬套。

## 触发条件

- "把这份方案做成一套网页版幻灯片"
- "做个在线 deck 讲清楚我们这个季度的三个判断"
- "发布会想放一个网页版的 slides 页面"
- "路演材料先出个大纲，用网页形式给我看"（→ 先定节拍，见第 2 步）
- "把这些图表串成一套演示页"（→ 先 `read_file` 读素材再排节拍）

## 工具契约（先记住参数，勿凭直觉猜）

| 工具 | 参数 | 说明 |
|---|---|---|
| `design_list_systems` | 无 | 返回 `systems[]`：`id` / `name` / `description` / `category` |
| `design_list_templates` | 无 | 返回 `templates[]`：`id` / `name` / `kind` / `description`；**工具本身不接过滤参数**，`kind` 要在返回值里自行筛 |
| `design_generate` | `name`、`kind`、`system_id`、`template_id`、`brief` —— **五个全必填** | 建项目 + 生成 v1；`kind` 固定 `"deck"` |
| `design_iterate` | `project_id`、`feedback` | 基于最新产物生成下一个版本 |
| `design_export` | `project_id` —— 只有这一个参数 | 返回最新产物的 `html_content` 与 `file_path`；**没有 `format` 参数** |

漏掉任何必填参数返回 `missing_required_parameters`；系统 ID / 模板 ID **只能用
`design_list_systems` / `design_list_templates` 返回值里的 ID，不要凭空编**。
模板 ID 不存在、或 `kind` 与模板不匹配，后端都返回 `generation_failed`，冒号后
是具体原因（见下表）。

### 错误码对照

| 错误码 | 触发条件 | 怎么办 |
|---|---|---|
| `missing_required_parameters` | 任一必填参数没传 | 按上表补齐参数 |
| `design_studio_not_initialized` | DesignStudio 未初始化（后端未起） | 环境问题，不是参数问题；如实告知用户，不要重试刷参数 |
| `generation_failed: <原因>` | 模板 ID 不存在 / `kind` 与模板实际 kind 不匹配 / LLM 输出无法解析 | 看冒号后的原因：`not found` → 模板 ID 编错了，回第 1 步用 `design_list_templates` 的返回值；`kind` 不匹配 → 换同 kind 的模板或改 `kind` |
| `iteration_failed: <原因>` | `design_iterate` 阶段失败（无历史产物 / LLM 失败） | 先确认已经跑过一次 `design_generate`（没有产物就没法迭代） |
| `no_artifacts_found` | `design_export` 时该项目还没有任何产物 | 先 `design_generate` 出 v1 再导出 |
| `export_failed: <原因>` | `design_export` 阶段失败 | 如实转述冒号后的原因 |

> **子代理看不到 design 工具。** design_* 五件套只在 coordinator（primary）profile
> 白名单里。子代理被要求"做个 deck"时不要让子代理自己去调 design_*，交回主对话执行。

## 工作流（五步）

### 1. 先查 deck 模板，再谈别的（可能直接终止）

deck 生成**强依赖一个已安装的 `kind="deck"` 模板**——`template_id` 是必填项，
且模板不存在、或模板 kind 不是 `deck`，都会直接报错。所以第一步无条件先跑
`design_list_templates`，在返回值里筛出 `kind == "deck"` 的条目。

**随包发布 `pitch-deck`**（id 与 `kind` 均为 `pitch-deck`，见下表），deck 的
默认起点。用户没有特殊要求就直接用它，把 `id` / `name` / `description` 报给
用户确认后继续第 2 步。

- **筛选结果里有 `pitch-deck`** → 默认用它；用户想要别的主题（比如教学课件、
  产品发布会、季度复盘）就问一句要不要换，**别默认就给**，也**别反复问**；
- **用户明确要另一套 deck 形态**（比如带讲者备注页、带图表页的模板）→ 见下方
  "换一套 deck 模板"；
- **一条 deck 模板都没有**（被人删了 / 换了安装目录）→ **如实告诉用户：当前
  找不到任何 deck 模板**，并把后果讲清楚——`template_id` 是必填且会被校验的，
  没有模板就没法启动 deck 生成。给两个真实选项：
  1. 改做原型页 / 落地页（`kind="prototype"`，走 design-prototype 技能，
     随包发布 `landing-page` 模板可用）；
  2. 装回一个 deck 模板——见下方 "换一套 deck 模板"。

  **不要**编一个模板名硬传（必然 `generation_failed`），也**不要**把 prototype
  模板当 deck 模板用——后端会按 kind 拦下（`kind` 不匹配），且模板里的结构
  要求与 deck 形态本来就冲突。

#### 换一套 deck 模板

装一个新 deck 模板：在
`backend/design/content/templates/deck/<template-id>/` 下建目录，放一份
`SKILL.md`（可选再放 `example.html` 做参考样例），frontmatter 至少要有：

```yaml
---
name: <template-id>        # 这个值就是模板 ID
kind: deck                 # 必须
description: 一句话说明这套模板的形态
---
```

**frontmatter 的 `name` 字段就是模板 ID**（后端 `parsed.get("name") or
目录名`，以 `name` 为准），所以目录名和 `name` 保持一致最省心——不一致的话
调用时要传 `name` 那个值。装好后用 `design_list_templates` 确认它出现在
`kind == "deck"` 的结果里，再让用户挑。

### 2. 选设计系统 + 定叙事节拍

`design_list_systems` 拉清单（随包发布 `minimal` 与 `corporate`），让用户选，
不替他默认——deck 的投屏场景对对比度比页面更敏感，选错影响更大。

deck 的真正难点是**叙事结构**，不是配色。在写 brief 之前先和用户敲定节拍，
用纯文本逐页列出，每页一行：

```
第N页 [页型] 标题（一句断言）—— 本页唯一 takeaway
```

- 页型：封面 / 议程 / 分区页 / 要点页 / 数据页 / 对比页 / 结论页；
- 标题写**断言句**（"三季度增速回落 12 个百分点"），不写名词短语——
  观众扫一眼标题就该带走结论；
- 一页只承载**一个论点**，塞不下就拆页；常见汇报 8-15 页；
- 用户没确认节拍不要生成。多轮未确认就整稿重做是反模式。

节拍确认后把这些结构要求写进 brief 的"必备区块"，连同受众、场合、时长
（时长决定页数）一起交给生成步骤。用户甩了素材先用 `read_file` 读进来，
数据缺口在 brief 里标出来问用户，**不编造指标**。

多轮任务用 `todo_write` 建清单（查模板 / 选系统 / 定大纲 / 生成 / 迭代 / 导出）。

### 3. 首次生成

`design_generate` 一次性完成**建项目 + 出 v1**，没有单独的建项目步骤。传
`kind="deck"`、第 1 步选定的 `template_id`、第 2 步选定的 `system_id`，
以及含节拍清单的 `brief`；`name` 取项目主题（例："Q3 业务复盘 deck"）。

- 这是 LLM 阻塞调用，耗时长，返回前不要并发发别的工具；
- 返回 `artifact_version: 1` 与 `file_path`，记下 `project_id` 备用。

### 4. 迭代（反馈多半是叙事，不是像素）

deck 的修改意见通常落在**叙事顺序**和**强调重点**上，而不是视觉打磨——
用户看完一轮的真实反馈往往是"第三页放太早"、"结论要提前"、"这条数据才是
关键，别埋在中间"。这类意见直接照写进 feedback：

- 说清**页码 + 现状 + 期望**，例："现状是第 4 页才给结论，但前面三页都在
  铺背景，希望结论提前到第 2 页，后面改成支撑"；
- 语气与信息密度也归这里管（"第 3 页文字太满，一页只留一句结论"）；
- 视觉类意见（配色、字号、留白）同样可以提，但别指望一轮改到位——
  优先确认叙事，视觉留到后面几轮；
- "再有点气势"这类模糊反馈用 `ask_user_question` 追问方向，别猜。

`design_iterate(project_id, feedback)` 出新版本，`artifact_version` 递增，
旧版本保留可回看。每次返回后把版本号与改了什么复述给用户。

### 5. 导出交付

用户认可后 `design_export(project_id)` 取最新产物，交付时给出：

- `file_path`（产物按 `design/<project_id>/v<N>.html` 落盘）；
- `html_content`——需要贴给用户或做后续处理时用这份；
- 当前版本号，并说明继续提反馈走 `design_iterate` 生成新版本、旧版本保留；
- 如果用户其实要 `.pptx` 文件，明确告知应改走 ppt-making 技能
  （本技能只产出 HTML，不做格式转换）。

## 不做的事（YAGNI）

- ❌ 不编造模板 ID——只用两个 list 工具的返回值里 `kind == "deck"` 的 ID
- ❌ 不把 prototype 模板当 deck 模板用（后端按 kind 校验，必然 `generation_failed`）
- ❌ 不替用户默选设计系统（用户明确授权除外）
- ❌ 不在未确认节拍大纲时生成
- ❌ 不在 brief 里编造数据、指标、客户名（缺失就问用户）
- ❌ 不做 landing page / 后台界面（走 design-prototype，`kind="prototype"`）
- ❌ 不做 `.pptx` 导出与格式转换（走 ppt-making 技能）
