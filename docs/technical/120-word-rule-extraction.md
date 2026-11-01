# 120 — Word 规范/范本文档规则抽取（M3a）

> 日期：2026-11-01 · 分支：`feat/word-rule-extract`
> 方案：`docs/plans/2026-10-31_word-document-intelligence.md`（M3）、`docs/plans/2026-11-01_word-rule-extract-m3a.md`

## 1. 定位

把“规范/范本文档 → 可执行规则包”做成确定性闭环：

- **spec**：从 `.docx/.txt/.md` 识别页面、页边距、正文字体字号、行距、首行缩进、
  页码、标题编号、必含章节、题注编号等条文，生成候选规则；
- **template**：从 `.docx` 范本的 `DocumentProfile` 统计页面/字体/正文段落格式主导值，
  按分布比例给出置信度；
- 去重、冲突标记、来源强制；**不调用 LLM、不写文件**。

规则包保存仍走既有 `/office/word/rulepacks` 存储层；审校/修复直接使用抽取结果。

## 2. 数据模型

- `WordRuleCandidate`：`rule`、`confidence`（0–1）、`source_excerpt`、`conflict_group`；
- `WordRuleConflict`：`kind`、`rule_ids`、`message`；
- `WordRuleExtractionResult`：`source_path`、`file_type`、`pack`、`candidates`、
  `conflicts`、`warnings`、`summary`。

每条生成规则都带 `source`（文件 + 段落号或“范本主导值”统计依据）。

## 3. 接口

```http
POST /api/v1/office/word/rulepacks/extract
POST /api/v1/office/word/rulepacks/extract/save
```

抽取请求：

```json
{
  "workspace_path": "/ws",
  "file_path": "/ws/spec.docx",
  "file_type": "spec",
  "pack_id": "journal-spec",
  "pack_name": "期刊规范",
  "max_size_bytes": 52428800
}
```

保存请求：`{workspace_path, pack}`；保存前：

- 每条规则 `source` 必须非空，否则 422（“以下规则缺少来源，不能保存”）；
- 调用既有 `validate_rulepack`（规则数/唯一 id/已知 kind）与工作区规则包存储校验。

## 4. 规范抽取（spec）

| kind | 识别模式 | 置信度 |
|---|---|---|
| `page.size` | `A4`、`210×297`、`Letter/信纸` | 0.85–0.90 |
| `page.orientation` | 页面/纸张 + 横向/纵向 | 0.75 |
| `page.margins` | 上/下/左/右边距 + mm/cm（同段可合并） | 0.55 + 0.1×边数 |
| `style.font` | 正文/仿宋/宋体/黑体/楷体 + 三号/小四/字号 pt | 0.85 |
| `style.paragraph` | 行距固定值 pt / 倍数；首行缩进 cm/mm/字符 | 0.80–0.85 |
| `page.page_number` | 页码 + 页脚/页眉；阿拉伯/罗马 | 0.80 |
| `structure.heading_sequence` | 标题编号 + `1.1`/`1.1.1` | 0.75 |
| `structure.required_headings` | 应包括/必须包含：A、B、C | 0.70 |
| `content.caption_sequence` | 图/表题注 + 编号/连续/顺序 | 0.70 |

- “首行缩进 N 字符”在识别到正文字号后按 `N × 字号 × 2.54/72` 换算为 cm；
  无法识别字号时跳过该候选并返回 `char_indent_unconverted` warning；
- 数字 `pt/磅` 解析会排除“行距/间距/段前/段后”前缀，避免把行距当字号。

## 5. 范本抽取（template）

- 页面尺寸/方向/页边距取第一节；
- `Normal` 样式字体（ascii/eastAsia/字号）；
- 正文段落（level=0、Normal/Body/正文）统计：
  - 行距：固定值（pt）与倍数分组，取样本量更大的一组的主导值；
  - 首行缩进：直段属性缺失时回退到 Normal 样式级格式；
  - 对齐：主导占比 ≥60% 才生成规则；
- 任一节有页码域 → `page.page_number`；
- 置信度 = 主导值占比，clamp 到 0.5–0.95；
- 无正文样本 / 多节页面尺寸不一致 → warning。

## 6. 去重与冲突

- `page.margins` / `style.font` / `style.paragraph`：按字段合并同 kind 候选；
  同一字段不同值 → 标记 `conflict_group=conflict/<kind>`，保留所有候选并返回冲突；
- 其他 kind：参数完全相同的候选合并（保留置信度高者）；
  参数不同 → 全部保留并标记冲突；
- 冲突消息列出冲突字段，`rule_ids` 指向涉及规则。

## 7. 限制（后续）

- LLM 语义候选与条文分段（M3b）；
- 规则复核 UI（来源原文、置信度、样例、启停、测试）（M3c）；
- 规则包版本对比与导出/导入（后续）；
- 规范中的表格/附件条文暂不扫描。

## 8. 测试

- `backend/tests/unit/office/test_word_rule_extract.py`（9）：
  spec 全类型抽取与来源/置信度、可复现、重复合并、冲突标记、字符缩进换算与缺字号 warning、
  范本主导值、无正文样本 warning、txt 规范、非法类型拒绝；
- `backend/tests/integration/test_office_word_extract_routes.py`（4）：
  抽取→保存→列表、范本端点、无来源保存拒绝、超限/越界/非法范本类型拒绝；
- ruff 0.4.4、py38 兼容、architecture、import-linter 通过。
