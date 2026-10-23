# 89 — 分节页码格式与起始号（w:pgNumType，Round 53）

> 日期: 2026-09-18 · 分支: `feat/pgnum-format`
> 系列: Word/Office 写作能力增强第 54 轮

## 1. 定位

论文/正式报告页码惯例：前置部分（封面/目录）罗马数字（i/ii），正文
阿拉伯数字从 1 起算。页脚 PAGE 域渲染格式由所在节的 `w:pgNumType`
决定——缺该支持时全程 decimal 连续。

## 2. 变更

- `WordPageSetupSpec` 增 `page_number_format`（decimal/upperRoman/
  lowerRoman/upperLetter/lowerLetter）与 `page_number_start`（ge=0）；
- `_apply_page_setup_to_section`：写/改该节 `w:sectPr/w:pgNumType`
  的 fmt/start（两者都未指定时零触碰——既有产物零变化）；主节
  （format_spec.page）与分节新节（section_breaks.page_setup）同一路径；
- lint `page/numbering`：spec 声明时校验首节实际值（对偶）。

## 3. Win7 对齐与测试

新功能不 cherry-pick 到 release/win7；零新增依赖。
`test_pgnum_format.py` 4 项：主节写入、分节独立 fmt/start、lint 检出、
未声明零触碰。
