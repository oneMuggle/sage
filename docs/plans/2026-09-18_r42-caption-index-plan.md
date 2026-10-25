# 图目录/表目录（TOF 域 + SEQ 题注升级）Round 42 实施计划

> 日期: 2026-09-18 · 分支: `feat/word-caption-index` · 基于 main @ eeb1c6bb
> 系列: Word/Office 写作能力增强第 43 轮（R39-R41 TOC 真页码故事线的姊妹篇）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 依赖: 零新增。

## 背景

期刊论文/正式报告常要求"插图清单/表格清单"。R7 的题注是字面文本
"图N　标题"——Word 的题注收录机制（`TOC \c "图"`）只认含 SEQ 域的
题注段，字面文本无法被收录。本轮两步走：题注升级为 SEQ 域（视觉与
回读完全兼容），再支持插入图目录/表目录域（R39 的 COM 刷新通道顺带
获得真页码）。

## 批次任务

### A. 题注 SEQ 域化（`word_layout.add_caption`）

- 段落结构：label run + SEQ 复杂域（begin + instrText
  ` SEQ 图 \* ARABIC ` + separate + 缓存编号 run + end）+ 间隔标题 run，
  全部 9pt——fldChar/instrText 在 run 内、缓存编号是普通 run，
  python-docx 回读文本与既有字面形态完全一致（lint 的
  caption/sequence 规则零改动即可通过）。
- Word 语义：含 SEQ 的段落被识别为题注条目；F9/COM 重执行 SEQ 按
  文档顺序重编号（与"无题注不占号"口径一致）。

### B. 图目录/表目录域（`word_layout.insert_tof_field` + 模型 + word.py）

- `WordIndexSpec(BaseModel)`：heading_text（默认 图目录/表目录，
  max 50）+ placeholder_text（域未更新占位提示）。
- `WordFormatSpec.figure_index / table_index: Optional[WordIndexSpec]`。
- `insert_tof_field(doc, spec, label, entries)`：标题段（加粗居中 16pt，
  非 Heading 样式——不被自我收录/不参与编号检查）+ fldChar 复杂域
  ` TOC \h \z \c "图" ` + 缓存条目行（图N　标题，无页码——与 R29 目录
  缓存同思路）+ end + 分页。
- `word.py`：`images_by_position`/`trailing_images` 计算前置；目录之后
  依次插入图目录、表目录（条目按正文编号顺序预收集——图题注跨段落
  位置+文末钳制两段循环复刻，表题注按 req.tables 顺序）。

### C. COM 刷新扩展（`toc_refresh.py`）

- TOC 逐个 Update 后追加 `doc.Fields.Update()`——SEQ 重编号 + TOF
  收录条目与页码一次完成；结果模型不变（信息性扩展不进摘要）。

### D. Lint 兼容（`word_lint.py`）

- 目录/图目录缓存条目行文本形如"图N　标题"，会被 caption/sequence
  规则误判为正文题注重复——`_check_captions` 改用
  「复杂域缓存内容跳过」迭代器（追踪 fldChar begin/end，域内段落
  不参与规则；begin/end 段自身文本为空不受影响）。

### E. 契约同步

- `office_create_tool` schema：format_spec 新增 figure_index/table_index
  对象（镜像 bibliography 形态）。
- `types.ts`：WordFormatSpec + WordIndexSpec 接口同步（前端契约）。
- report-writing SKILL.md：插图清单/表格清单一句话说明。
- 技术文档 79 号、README 索引、CHANGELOG。

## 验证

- 单测：SEQ 题注（fldChar×4 + 缓存编号 + 回读文本不变）、TOF 插入
  （instr 含 \c "图"、缓存条目、空占位）、word.py 端到端（figure_index
  生成 → 域与条目在场）、lint 跳过域内缓存行、toc_refresh Fields.Update
  被调用、schema 键。
- office word 家族回归 + ruff。

## Round 43 候选

- office_update 接 section_breaks/figure_index（修订面补齐）
- 前端 COM 徽章细分（需协调）
- TOC/section_breaks 的 schema 属性漂移卫生修复
