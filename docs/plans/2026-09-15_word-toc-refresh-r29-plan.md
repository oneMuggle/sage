# TOC 域静态缓存回填 Round 29 实施计划（"更新收尾"务实第一步）

> 日期: 2026-09-15 · 分支: `feat/word-toc-refresh` · 基于 main @ b8da0c90
> 系列: Word/Office 写作能力增强第 20 轮（R13 TOC 目录域 #670 的收口）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 零新增依赖（纯 oxml fldChar 复杂域）。冲突规避：不触碰 journal/media。

## 背景（Round 28 合并后再分析）

R13 的 TOC 域用 `fldSimple` + 占位提示（"按 F9 更新"）——用户打开文档
先看到一行提示而非目录，体验打折。"更新收尾"的 headless/COM 方案
（真页码）依赖外部渲染器且 LO 往返有格式风险，延后。本轮先做**务实
第一步**：改用 **fldChar 复杂域 + 静态缓存回填**——

- 复杂域结构（Word 原生目录即此形态）：
  `fldChar(begin)` + `instrText TOC \o "1-3" \h \z \u` + `fldChar(separate)`
  → 【缓存结果：按文档标题生成的静态目录行，逐行缩进】→ `fldChar(end)`
- 打开文档**即见目录内容**（标题层级列表；页码留待更新域后由渲染器
  计算——静态阶段刻意不放页码，避免给出错误页码）；
- 用户按 F9 / 右键更新域 → 渲染器用真实分页重算整个域。

## 批次任务

### A. word_layout.py

`insert_toc_field(doc, toc, headings)` 签名扩展：headings 为
`[(level, text)]` 列表（生成器收集）。复杂域写入：
- begin 段：`fldChar begin` + `instrText` + `fldChar separate`
- 缓存行：每个标题一段（缩进 = (level-1)*0.74cm，风格继承目录标题）
- end 段：`fldChar end`
- 空 headings（正文无标题）→ 退化为 R13 占位提示形态

### B. 生成器（word.py）

body 循环收集 headings（numbering 前缀后的最终文本 + 级别），TOC 插入
移到 body 循环**之后**（域插到文档末尾再移到目录位置不可行——改为：
先收集全部标题，TOC 段在正文写入前插入，缓存行由预收集的标题清单生成，
两步都用同一份 headings 列表，与最终文档一致）。目录标题段仍为普通
段落（不被自我收录、不参与编号）。

### C. 契约与文档

零 API 面变更（format_spec.toc 结构不变）；技术文档 72 记录 fldChar
形态与 Word 兼容性要点。

### D. 测试（追加 `test_office_word_toc.py`）

- 复杂域结构断言：begin/instrText/separate/end 顺序与 instr 内容
- 缓存行逐条对应标题（文本 + 级别缩进）
- 空标题文档退化为占位提示形态
- 既有 toc 用例（占位提示、位置）同步更新

## Round 30 候选

- TOC 页码版（headless/COM 通道）
- Word 横排分节 + 宽表组合场景文档
