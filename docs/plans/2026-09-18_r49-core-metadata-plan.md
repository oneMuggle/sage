# 文档核心属性（WordMetadataSpec → docx core properties）Round 49 实施计划

> 日期: 2026-09-18 · 分支: `feat/word-core-metadata` · 基于 main @ 28310ddd
> 系列: Word/Office 写作能力增强第 50 轮（小轮）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 依赖: 零新增。

## 背景

期刊投稿/公文归档常要求文档属性（作者/主题/关键词等）——Word「文件
→ 信息」面板可见的 core properties。当前 office_create 不写任何属性
（author 留空、title 空）。本轮补 request 级 `metadata`。

## 批次任务

### A. 模型与生成器

- `WordMetadataSpec`（author/subject/keywords/comments/category，全
  Optional、extra=forbid）；
- `OfficeWordGenerateRequest.metadata: Optional[WordMetadataSpec]`
  （request 级——文档属性不是版式，不进 format_spec）；
- generate：`core.title = req.title` 恒写；其余字段显式传入才写
  （不臆造作者）。

### B. 契约

- office_create schema：content 增 metadata 对象（properties + 描述）；
- types.ts：`WordMetadataSpec` 接口 + `OfficeWordGenerateRequest.metadata?`；
- SKILL.md（paper-writing 第 4 步 JSON 补 metadata 示例一行）。

### C. 测试与账目

- 生成含 metadata → core_properties 回读；缺省仅 title；
- 技术文档 85 号、CHANGELOG。

## 验证

- 新测试 + word 家族回归 + ruff。

## Round 50 候选

- Excel 侧 core properties 对称支持
- Word COM 前端徽章细分（需前端协调）
