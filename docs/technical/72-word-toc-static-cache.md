# 72 — TOC 域静态缓存回填（Round 29：fldChar 复杂域）

> 日期: 2026-09-15 · 分支: `feat/word-toc-refresh` · 方案:
> `docs/plans/2026-09-15_word-toc-refresh-r29-plan.md`
> 系列: Word/Office 写作能力增强第 20 轮（R13 TOC 目录域 #670 的收口）

## 1. 问题与方案

R13 的 TOC 域用 `fldSimple` + 占位提示（"按 F9 更新"）——用户打开文档
先看到提示而非目录。本轮改为 **fldChar 复杂域 + 静态缓存回填**（Word
原生目录的 OOXML 形态）：

```
[fldChar begin][instrText TOC \o "1-N" \h \z \u][fldChar separate]
→ 缓存结果：按文档标题生成的静态目录行（逐级缩进，首级加粗）
[fldChar end]
```

打开文档**即见目录内容**（标题层级列表；页码留待更新域后由渲染器
计算——静态阶段刻意不放页码，避免给出错误页码）；用户 F9 / 右键更新
域后被真实带页码目录替换。headless/COM 通道（真页码）作为后续候选。

## 2. 语义要点

- 缓存行文本与正文标题**最终形态一致**：`numbering` 开启时含编号前缀
  （"1 引言"），关闭时为纯标题文本——两者由同一段预收集代码驱动；
- `toc.levels`（如 "1-3"）同时过滤缓存行与域开关（`TOC \o "first-last"`）；
- 目录标题段仍为普通段落（不被域自我收录、不参与编号检查）；
- begin 段与 end 段为空段落（Word 复杂域标准形态）；
- 零 API 面变更：`format_spec.toc` 结构不变。

## 3. 配套：Linter 对偶升级

`toc/presence` 检测升级为**双载体兼容**——fldSimple（R13 形态）与
fldChar 复杂域（本轮形态）均可检出，并抽出 `_document_has_toc_field`
供复用。

## 4. Win7 对齐与测试

零新增依赖；不 cherry-pick（31-win7-lts.md §2）。
`test_office_word_toc.py` 重写为 9 项：复杂域结构序列
（begin/separate/end）、instr 级别映射、缓存行与正文一致性、levels
过滤、空标题占位退化、零变化基线、Linter 正反例、技能广告。
word 全家族回归 81 项全绿。

## 5. Round 30 候选

TOC 真页码版（LibreOffice headless 宏 / Word COM 可选通道，需求评审
后立项）、Word 横排分节 + 宽表组合、Pillow 阈值配置化。
