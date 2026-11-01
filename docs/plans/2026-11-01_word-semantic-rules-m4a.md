# Word M4a：确定性语义规则

> 日期：2026-11-01 · 分支：`feat/word-semantic-rules`
> 基线：`origin/main` = `9f859497a`（M3b 合并后）
> 上游方案：`docs/plans/2026-10-31_word-document-intelligence.md`（M4）

## 1. 目标

在现有规则包引擎中补充三类**不依赖 LLM 的语义级检查**，直接复用 M2 的
issue/锚点/修复/前端面板链路：

- `content.date_format`：全文日期格式一致性（默认以出现最多的格式为准，也可显式配置允许格式）；
- `content.terminology`：术语表统一（同义词/缩写指向首选术语）；
- `content.required_phrases`：必备表述（如结语、称谓、声明）。

本阶段不实现原生 track-changes；修订写入留给 M4b。

## 2. 规则契约

| kind | params | 行为 | 锚点 |
|---|---|---|---|
| `content.date_format` | `allowed?: ["cn"\|"iso"\|"slash"\|"dot"]` | 无 allowed → 统计全文主导格式；非允许/非主导格式逐段报 warning | paragraph |
| `content.terminology` | `pairs: [{preferred, variants:[...]}]` 或 `[[preferred,[...]]]` | 段落中出现 variant → 报 issue，expected=preferred，可标记 fixable | paragraph |
| `content.required_phrases` | `phrases: [string]`, `match?: contains\|exact` | 全文缺失短语 → 文档级 issue | document |

日期样式：`cn=YYYY年M月D日`、`iso=YYYY-MM-DD`、`slash=YYYY/M/D`、`dot=YYYY.M.D`。
参数非法（未知样式、空 pairs/phrases、非对象 pair）→ 422。

内置 `general-quality` 增加 `content/date_format`（warning，默认主导格式推断）。

## 3. 实施步骤

- [x] 引擎：三类检查器 + 注册表
- [x] 内置包：general-quality 增加日期格式规则
- [x] 测试：日期主导/允许列表、术语锚点、必备表述、参数校验、内置规则
- [x] 文档：119 检查器表/测试/限制更新 + README
- [x] 门禁：ruff / py38 / architecture / pytest / CI

## 4. 验收

- 混合日期格式文档能定位到少数派段落；
- 术语 variant 命中段落并能定位，expected 为首选术语；
- 缺失必备表述产生文档级 issue；
- 现有审校/修复/前端面板无需改动即可展示与过滤新规则；
- 旧规则行为不变。

## 5. 非目标

- LLM 语义判断（如“结语是否得体”“章节语义完整性”）；
- 原生 track-changes / 批注式修订写入（M4b）；
- 金额大小写、引用格式等更复杂语义规则；
- 规则参数在线编辑 UI。
