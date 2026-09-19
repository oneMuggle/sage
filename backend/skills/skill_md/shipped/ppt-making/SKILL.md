---
name: ppt-making
description: 制作演示文稿（.pptx）的完整工作流——三要素澄清、逐页大纲契约、页型库与生成硬约束、品牌模板填充、matplotlib 统计图配图、回读自检与增量修订。当用户要做 PPT/幻灯片/课件/汇报deck 时使用。
license: Apache-2.0
compatibility: 需要 PPT 工具面（office_create 的 doc_type=ppt 与 slides[].layout/image/notes、office_fill_ppt_template / office_analyze_ppt_template、office_update 快照回滚）；统计图渲染需要本机 matplotlib
when_to_use: 当用户要制作 PPT、幻灯片、演示文稿、课件、汇报材料、路演 deck，或用"做套片子""做个汇报演示""把这些材料转成演示格式"等表达时使用
allowed-tools: read_file write_file memory_search office_list office_read office_create office_update office_restore office_archive office_analyze_ppt_template office_fill_ppt_template repl todo_write ask_user_question
triggers: []
---

# 演示文稿制作（.pptx）

> shipped 基础版。`triggers` 留空——靠 `when_to_use` 语义判断激活。
> 与 ppt-maker 角色的关系：角色 prompt 管**身份与红线**，本技能管
> **每一步怎么做**。Word 正式文档走 report-writing / writer，不在此列。

## 触发条件

- "把这份项目总结做成汇报 PPT"
- "给我做一套 15 页的季度复盘片子"
- "按公司模板做周例会演示"（→ 模板填充通路）
- "这份 Word 报告转成演示版"（→ Word 大纲映射为逐页大纲）

## 工作流（五步）

### 1. 三要素澄清 + 素材盘点

确认 **听众 / 场合 / 时长**。缺任一要素用 `ask_user_question` 问，不要猜：

- 页数估算：约 1 页 ≈ 1 分钟宣讲时间（10 分钟汇报 ≈ 10 页上下，
  封面/议程/分区页也计入）；
- 素材：用户点了文件就先 `read_file` / `office_read` 读全，
  散落在多处的先归拢；素材不足时列出缺口清单向用户要，**不编造**。

多页 deck 用 `todo_write` 建清单（大纲确认 / 逐章内容 / 配图 / 生成 /
自检五档即可），随推进更新。

### 2. 逐页大纲契约（交付门禁：未确认不生成）

先输出**纯文本逐页大纲**请用户确认，每页一行：

```
第N页 [页型] 标题（一句断言，≤20字）——本页唯一 takeaway 一句话
```

- 标题写**断言句**（"三季度增速回落 12 个百分点"），不写名词短语
  （"三季度业绩"）——观众扫一眼标题就该带走结论；
- 一页只承载**一个论点**；塞不下就拆页，deck 上限 100 页，
  常见汇报 8-15 页；
- 用户要改大纲就改到确认通过为止；**多轮未确认的整稿重做是反模式**，
  出稿后的修改一律走增量修订（第 5 步）。

### 3. 页型库（组织每页内容时按型取用）

| 页型 | layout | 内容组织 |
|---|---|---|
| 封面 | `title` | 主标题 + 副标题（场合/日期/汇报人）写进 title/bullets |
| 议程 | `title_content` | 分区列表，每项一行 |
| 分区页 | `title` | 章节名 + 一句话预告本节结论 |
| 要点页 | `title_content` | bullets ≤5 条、每条 ≤40 字、动词开头、去连接词 |
| 数据页 | `title_content` + `image` | 图为主、2-3 条 bullet 点解读，标注数据来源 |
| 对比页 | `title_content` | "现状 → 目标"或 A/B 各 2-3 条，左右语义对齐 |
| 结论页 | `title_content` | 行动项 + 负责人 + 时间点 |

- 引擎只认 `title` / `title_content` / `blank` 三种内置版式名；
  用品牌模板时先 `office_analyze_ppt_template`，把返回的**母版版式名**
  填进 `slides[].layout`（模板中找不到对应版式会回退默认几何）；
- **speaker notes 必填**：每页把讲稿要点写进 `notes`（≤2000 字），
  页面只留视觉骨架——"念页面"的 deck 是失败品；
- `blank` 只用于全图页（配图占满版心、文字进 notes）。

### 4. 生成（office_create doc_type=ppt）

- `content` 传结构化对象 `{"slides": [{title, bullets, notes, layout, image}]}`，
  不要把 deck 写成 markdown 长字符串交给引擎；
- 配图 `image.source` 传工作区 png 绝对路径或 `data:image/...` base64
  （≤10MB）；统计图用 `repl` 现渲：matplotlib 画图，**中文字体先设**
  （`plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]`、
  `axes.unicode_minus=False`），`dpi≥150`，存到工作区后再引用；
- 每页 bullets 硬约束 ≤5 条（引擎容忍 20 条，但那是截断余量不是设计空间）；
- 输出落工作区受管目录，文件名向用户确认过的主题靠拢。

### 5. 自检与交付（交付前必做）

- 生成成功后 `office_read` 回读：核对**页数、逐页标题**与确认过的大纲
  一致，检查 self_check 摘要与截断告警；
- 增量修订走 `office_update`：先 `dry_run=true` 预览变更清单，
  确认后应用；改前引擎自动快照，出错可 `office_restore` 回滚；
- 交付提醒：deck 在工作区 `office/ppt/` 受管目录下，可随时
  `office_list` / `office_read` 回看；需要打印版/防改版可另导出 PDF。

## 品牌模板通路

用户给了 .pptx 模板（工作区内路径或 doc_id）：

1. `office_analyze_ppt_template` 枚举母版版式名与占位符 idx/类型；
2. 二选一：
   - **填充**（模板已有内容骨架、只需换文案）：`office_fill_ppt_template`
     传 `fills=[{slide_number(1起), placeholder_idx, text}]` +
     `output_filename`（永远另存新文件，模板原件不动；任一页号/占位符
     越界整批拒绝——先小样验证再全量填）；
   - **生成**（模板只提供视觉版式）：`office_create` 的
     `slides[].layout` 直接引用模板版式名。

## 不做的事（YAGNI）

- ❌ 不编造数据与指标（缺失就问用户；图表必须能回溯到素材来源）
- ❌ 不做 Word 文档（正式报告/论文走 report-writing / paper-writing）
- ❌ 不在未确认大纲时出稿；不出稿后整稿重做（增量修订 + 快照回滚）
- ❌ 不往一页塞两论点、不写超过三层的长句 bullet——文字墙交给 notes
