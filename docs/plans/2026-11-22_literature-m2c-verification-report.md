# 文献调研 M2c 收尾：Rubric 评审与 IEEE 引用样式

> 状态：实施完成，待 PR（2026-11-22）
> 上游：M2c 核心已由并行会话合并（main `1e5841a55`，PR #3203：`ledger.py` / `support.py` / `report.py`）
> 关联总计划：`docs/plans/2026-11-21_literature-research-paper-pipeline.md` §M2

## 背景与目标

M2c 核心（语义 claim support 摄入、EvidenceLedger、四态核验报告）已在
`1e5841a55` 落地。M2 清单还剩两项：

1. **Rubric 评审**：方法 / 覆盖 / 逻辑 / 写作四维评分 + 问题清单，
   明确"模拟评审，非同行评审"。
2. **引用样式**：在 GB/T 7714 基础上至少补 IEEE。

本分支补齐这两项；跨子系统引用自动适配器与专用核验报告前端面板不在本分支
范围（前者依赖各子系统接口，后者等 artifact 面板稳定后再做）。

## 涉及文件与模块

| 文件 | 变更 |
|---|---|
| `backend/literature/rubric.py`（新） | 四维确定性评分 + Markdown/JSON 产物 |
| `backend/literature/gates.py` | `build_references` 支持 `ieee`；新增 `SUPPORTED_REFERENCE_STYLES` |
| `backend/literature/export.py` | `export_run(run, style="gbt7714")` |
| `backend/literature/run_store.py` | `run_status` 增加 `has_rubric_review` |
| `backend/literature/cli.py` | `rubric` 子命令；`export --style {gbt7714,ieee}` |
| `backend/tests/unit/test_literature_review.py`（新） | rubric / IEEE / CLI 测试 |
| README、SKILL.md、references/pipeline.md | 命令与产物说明 |

## 技术方案

### Rubric 评审（`rubric.py`）

- 完全确定性，不调 LLM；只读运行目录产物。
- 四维各 0–5 分，总分 20；`band`：≥16 优 / ≥12 良 / ≥8 及格 / 否则待改进。
- **方法**：检索次数（0/1–2/≥3）、被引文献证据覆盖率（<50% / ≥50% / ≥80%）、
  外部元数据核验通过比例（≥60%）。
- **覆盖**：文献量（<8 / ≥8 / ≥15）、被引比例（<50% / ≥50% / ≥80%）、
  来源站点多样性（≥3 个来源）。
- **逻辑**：大纲存在、草稿包含全部大纲章节、无 unsupported/unresolved claim、
  claims 非空。
- **写作**：正文体量（≥1200 / ≥3000 字）、引用密度（每千字 ≥1.5 / ≥4 条）、
  门禁通过。
- 产物：`export/rubric_review.json`（`generated_at` / `total_score` /
  `max_score` / `band` / `disclaimer` / `dimensions[]`）与 `.md`
  （总分表 + 每维问题清单）；`disclaimer` 明确"模拟评审，非同行评审"。

### IEEE 引用样式

- `build_references(draft, papers, style="ieee")`：
  `[n] A. Author, B. Author, and C. Author, "Title," Venue, Year.`
- 英文名缩写首字母（`John Smith` → `J. Smith`），三位作者用
  `A, B, and C`，超过三位用第一作者 + `et al.`；中文名保持原样。
- `export_run(run, style=...)` 透传样式；`references.json.style` 记录实际样式；
  CLI `export --style ieee`。

## 实施步骤

- [x] `rubric.py`：四维评分 + JSON/Markdown 产物
- [x] `gates.py`：IEEE 行格式与 `SUPPORTED_REFERENCE_STYLES`
- [x] `export.py` / `run_store.py` / `cli.py` 接线
- [x] 测试：`test_literature_review.py`（rubric 满分/空运行/部分覆盖、IEEE 格式、
      CLI rubric 与 export --style）
- [x] 文档：README、SKILL.md、references/pipeline.md、总计划勾选
- [x] 目标回归：文献相关 5 个测试文件
- [x] ruff 与 `check_py38_compat.py`
- [ ] PR → main，合并后同步 release/win7

## 验证记录

- `pytest backend/tests/unit/test_literature_{review,pipeline,claims,m2c,site_profiles}.py`
  → 91 passed（main 环境）。
- `ruff check backend/literature backend/tests/unit/test_literature_review.py` → 通过。
- `check_py38_compat.py backend/literature` → 0 violations。
- Python 3.8 端到端复跑在 win7 cherry-pick 后执行。

## 风险评估

| 风险 | 缓解 |
|---|---|
| Rubric 分数被误读为学术质量 | `disclaimer` 固定声明"模拟评审/写作自检"；文档与 SKILL 同步强调 |
| 阈值主观 | 常量集中在 `rubric.py`，可按评测集调整；issue 文案给出具体数值 |
| IEEE 对中文作者/机构不友好 | 中文名保持原样；IEEE 官方对中文期刊格式另有要求，留 CSL 评估 |
