# Word M3a：规范/范本文档规则抽取

> 日期：2026-11-01 · 分支：`feat/word-rule-extract`
> 基线：`origin/main` = `3d7fc5da5`（M2c 合并后）
> 上游方案：`docs/plans/2026-10-31_word-document-intelligence.md`（M3）

## 1. 目标

把“规范/范本文档 → 可执行规则包”打通为确定性闭环：

- **规范文档抽取**（spec）：从 `.docx/.txt/.md` 中识别页面、页边距、字体字号、
  行距、首行缩进、页码、标题编号、必含章节、题注编号等条文，生成候选规则；
- **范本抽取**（template）：从 `.docx` 范本的 `DocumentProfile` 统计主导值
  （页面、页边距、Normal 字体、正文字段行距/缩进/对齐），按分布比例给出置信度；
- **去重与冲突**：同 kind 同参数合并；同字段不同值标记 `conflict_group` 并返回冲突列表；
- **来源强制**：每条规则带 `source`（文件 + 段落/统计依据）；抽取保存端点拒绝无来源规则；
- **可复现**：纯确定性、无随机性；同输入同规则集（规则按 kind 固定顺序 + 段落顺序）。

非目标：LLM 语义候选、规则复核 UI（M3b/M3c 后续）；本阶段不调用 LLM。

## 2. 数据模型

- `WordRuleCandidate`：`rule` + `confidence` + `source_excerpt` + `conflict_group`；
- `WordRuleConflict`：`kind` + `rule_ids` + `message`；
- `WordRuleExtractionResult`：`source_path`、`file_type`、`pack`、`candidates`、`conflicts`、`warnings`、`summary`。

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
  "pack_name": "期刊规范"
}
```

`file_type`：`spec`（默认）或 `template`。

保存请求沿用规则包模型：`{workspace_path, pack}`；保存前校验每条规则 `source` 非空，
且调用既有 `validate_rulepack`（kind/规则数/id 唯一）。

## 4. 抽取规则（spec）

| kind | 识别模式 | 置信度 |
|---|---|---|
| `page.size` | `A4` / `210×297` / `Letter` | 0.90 |
| `page.orientation` | 横向/纵向页面 | 0.75 |
| `page.margins` | 上/下/左/右边距 + mm/cm | 0.55 + 0.1×已识别边数 |
| `style.font` | 正文 + 仿宋/宋体/黑体/楷体 + 三号/小四/字号 pt | 0.85 |
| `style.paragraph` | 行距固定值 pt / 倍数；首行缩进 cm/mm/字符 | 0.80–0.85 |
| `page.page_number` | 页码 + 页脚/页眉（阿拉伯/罗马） | 0.80 |
| `structure.heading_sequence` | 标题编号 + `1.1`/`1.1.1` | 0.75 |
| `structure.required_headings` | 应包括/必须包含：A、B、C | 0.70 |
| `content.caption_sequence` | 图/表题注 + 编号/连续 | 0.70 |

“首行缩进 N 字符”在能识别正文字号时换算为 cm；否则跳过并给 warning。

## 5. 抽取规则（template）

- 页面尺寸/方向/页边距取第一节；
- Normal 样式字体/字号；
- 正文段落（level=0、Normal/Body/正文）中行距、首行缩进、对齐的主导值；
- 页码域存在 → `page.page_number`；
- 置信度 = 主导值占比（clamp 0.5–0.95）；无正文样本/多节不一致给 warning。

## 6. 实施步骤

- [x] 模型：候选/冲突/结果
- [x] 引擎：`backend/office/word_rule_extract.py`
- [x] 路由：extract / extract/save
- [x] 测试：spec/template 抽取、去重、冲突、字符缩进换算、保存来源校验、路径/尺寸拒绝
- [x] 文档：`docs/technical/120-word-rule-extraction.md` + README
- [x] 门禁：ruff / py38 / architecture / pytest / CI

## 7. 验收

- 规范样本能抽出页面/页边距/字体/行距/页码/标题/必含章节/题注规则；
- 范本样本能抽出页面/字体/正文字段规则，置信度反映主导比例；
- 重复条文只保留一条；冲突字段产生 `conflict_group` 与冲突列表；
- 所有规则有来源；保存端点拒绝无来源规则；
- 同输入重复抽取结果一致。
