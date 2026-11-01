# Word M3b：LLM 语义候选抽取

> 日期：2026-11-01 · 分支：`feat/word-rule-llm-extract`
> 基线：`origin/main` = `ad153b0eb`（M3c 合并后）
> 上游方案：`docs/plans/2026-10-31_word-document-intelligence.md`（M3）

## 1. 目标

在 M3a 确定性抽取之上增加可选的 LLM 语义候选，但**不放松确定性约束**：

- 只在规范文档（spec）上启用；范本走确定性统计；
- 条文分段（≤40 条、≤12,000 字符）后单次 LLM 调用，要求输出 JSON 候选；
- 每条 LLM 候选必须引用 `clause_id`，并经过严格 kind/params 白名单校验；
- 校验失败的候选丢弃并计数；LLM 无配置/调用失败/解析失败均降级为确定性结果；
- 结果与确定性候选一起走既有去重/冲突/来源逻辑，来源标注 `（LLM）`；
- `llm_used` 字段告知前端是否实际走通 LLM 路径。

## 2. 涉及文件

| 文件 | 作用 |
|---|---|
| `backend/office/word_rule_extract_llm.py` | 分段、prompt、JSON 解析、参数白名单、候选生成 |
| `backend/office/word_rule_extract.py` | `_extract_raw` / `_build_result` 拆分 + `extract_word_rules_async` |
| `backend/api/office_word_audit_routes.py` | `use_llm` 请求字段 + 异步分支（`asyncio.run`） |
| `src/shared/api/wordAuditTypes.ts` / `officeWordAuditApi.ts` | `llm_used` / `use_llm` |
| `src/features/office/WordRuleExtractionPanel.tsx` | 「LLM 补充」复选框与「LLM 已参与」徽章 |
| `electron/commandRoutes/office.ts` | 透传 `use_llm`（路径不变） |

## 3. LLM 候选约束（确定性后校验）

允许 kind 与参数范围：

- `page.size`：A4 / Letter；
- `page.orientation`：portrait / landscape；
- `page.margins`：`*_cm` 0–20；
- `page.page_number`：required/format（decimal/upperRoman/lowerRoman）；
- `style.font`：Normal + ascii/eastAsia/字号 5–50pt/bold/italic/underline/颜色；
- `style.paragraph`：行距 0.5–5、固定行距 5–100pt、缩进 0–5cm、对齐白名单；
- `structure.heading_sequence`：层级 1–9、require_prefix；
- `structure.required_headings`：2–20 字标题、最多 12 个、match 强制 contains；
- `content.caption_sequence`：标签 1–4 字、最多 10 个。

LLM 置信度 clamp 到 0.3–0.85；确定性候选在同参数合并时保留更高置信度。

## 4. 降级与安全

- 无 LLM 配置 → `llm_unavailable` warning，仅确定性结果；
- 调用异常 → `llm_failed` warning；
- 响应非 JSON → `llm_parse_failed` warning；
- 非法候选 → `llm_candidate_rejected` warning（计数）；
- 范本 + `use_llm` → `llm_template_unsupported` warning；
- 规范条文只作为用户数据进入 prompt，不提供工具/函数调用能力。

## 5. 实施步骤

- [x] LLM 候选模块（分段/JSON/白名单）
- [x] 抽取主入口异步化 + 结果 `llm_used`
- [x] 路由 `use_llm` 分支
- [x] 前端复选框/徽章/请求透传
- [x] 测试：LLM 单元 8 项 + 路由分支 1 项 + 面板新增 1 项
- [x] 文档：120 增补 LLM 章节 + README
- [x] 门禁：ruff / py38 / architecture / tsc / eslint / vitest / CI

## 6. 验收

- 配置 LLM 时，规范文档可补充确定性未识别的规则；
- 未配置 LLM 或调用失败时，行为与 M3a 完全一致（仅多 warning）；
- 非法 kind/参数/未知 clause 的候选全部被丢弃；
- 每条 LLM 规则来源带 `（LLM）` 且可追溯段落；
- 前端可选启停「LLM 补充」，结果显示是否参与。

## 7. 非目标

- 多轮分段抽取/超长规范分批（当前单次、有界截断）；
- LLM 候选的参数在线编辑；
- 规则复核 UI 的“试运行”；
- 模板的 LLM 语义抽取。
