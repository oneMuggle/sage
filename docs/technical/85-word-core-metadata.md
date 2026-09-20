# 85 — 文档核心属性（WordMetadataSpec → docx core properties，Round 49）

> 日期: 2026-09-18 · 分支: `feat/word-core-metadata`
> 系列: Word/Office 写作能力增强第 50 轮（小轮）

## 1. 定位

期刊投稿/公文归档常要求文档属性（作者/主题/关键词）——Word「文件 →
信息」面板可见的 core properties。此前 office_create 不写任何属性
（title 空、author 留 python-docx 模板默认）。

## 2. 变更

- `WordMetadataSpec`（author/subject/keywords/comments/category，全
  Optional、extra=forbid）+ `OfficeWordGenerateRequest.metadata`
  （request 级——文档属性不是版式，不进 format_spec）。
- generate：`core.title = req.title` 恒写；其余显式传入才写（不臆造
  作者——无 metadata 时保留模板默认）。
- 契约：office_create schema content.properties 增 metadata（注意：
  content 层而非 format_spec 层——R43 全等门禁会拦层级错放）；types.ts
  增 `WordMetadataSpec` + `OfficeWordGenerateRequest.metadata?`；
  paper-writing SKILL 第 4 步 JSON 补 metadata 示例。

## 3. Win7 对齐与测试

新功能不 cherry-pick 到 release/win7（31-win7-lts.md §2）；零新增依赖。
`test_word_core_metadata.py` 2 项：全字段回读、缺省仅 title。
