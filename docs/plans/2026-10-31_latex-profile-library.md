# LaTeX 期刊规范档案库与指南抽取（L5a）实施计划

> 日期：2026-10-31 · 分支：`feat/latex-profile-library`
> 基线：`origin/main` = `312f163b2`（L4d PR #2718 合并后）
> 前置：`docs/plans/2026-10-31_latex-compliance.md`
> 范围：规范档案的保存/加载/删除 + 从作者指南启发式抽取候选档案。

## 1. 目标

L4d 的合规档案只能手工填写。本阶段把档案变成可复用资产：

- 保存到工作区 `.sage/latex-profiles/<name>.json`；
- 合规面板可选择已保存档案并自动填充字段；
- 从 PDF/DOCX/TXT/MD 作者指南抽取候选档案（带原文证据），人工核对后保存；
- 支持删除与刷新。

## 2. 存储格式

```json
{
  "version": 1,
  "name": "ieee-2026",
  "profile": {
    "required_sections": ["Introduction", "Conclusion"],
    "required_metadata": ["title", "abstract"],
    "allowed_page_sizes": ["A4"],
    "required_min_pages": null,
    "required_max_pages": 20,
    "require_embedded_fonts": true,
    "min_image_dpi": 300,
    "forbidden_commands": []
  },
  "source": "guidelines/ieee.pdf",
  "evidence": [
    {"field": "required_max_pages", "value": 20, "snippet": "Maximum 20 pages", "source": "guidelines/ieee.pdf", "page": 2, "line": 7}
  ],
  "updated_at": "2026-10-31T09:00:00+00:00"
}
```

名称：`[A-Za-z0-9][A-Za-z0-9._-]{0,63}`；文件 ≤256 KiB；路径必须落在工作区内（符号链接逃逸拒绝）。

## 3. 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/office/latex/profiles?workspace_path=` | 列表（无效文件返回 warnings） |
| GET | `/api/v1/office/latex/profiles/{name}?workspace_path=` | 加载 |
| POST | `/api/v1/office/latex/profiles` | 保存/覆盖 `{workspace_path,name,profile,source?,evidence?}` |
| DELETE | `/api/v1/office/latex/profiles/{name}?workspace_path=` | 删除 |
| POST | `/api/v1/office/latex/profiles/extract` | 从指南抽取候选 `{workspace_path,source_path}` |

## 4. 抽取规则（启发式）

支持 `.pdf`（PyMuPDF 文本层）、`.docx`（python-docx）、`.txt/.md`。

- 页数：`maximum/no more than/不超过 … N pages`、`at least/不少于 … N pages`、`8-12 pages`
- 页面尺寸：`A4`、`Letter`、`8.5 x 11`、`Legal`
- 字体嵌入：`embed all fonts`、`font embedding`、`嵌入字体`
- 图片 DPI：`300 dpi`（72–1200 范围）
- 必需章节：短行精确匹配 Introduction/Methods/Results/Conclusion 等，或在 `must include/必须包含` 语句中出现
- 必需元数据：`must include abstract/keywords`、`title page`、`author information`

每条结果带 `evidence[{field,value,snippet,source,page,line}]`；结果始终 `needs_review=true`，未识别项给出 warning。

## 5. 文件

```
backend/office/latex/profile_store.py     # 存储/列表/加载/保存/删除
backend/office/latex/profile_extract.py   # 文本抽取 + 启发式规则
backend/office/latex/service.py           # 服务包装
backend/api/office_latex_routes.py        # /profiles CRUD + /profiles/extract
src/shared/api/latexApi.ts                # 档案 API/类型
src/features/office/LatexProfileLibraryPanel.tsx
src/features/office/LatexCompliancePanel.tsx  # 选择已保存档案
src/pages/Office.tsx
```

## 6. 安全与限制

- 只读取工作区内指南；PDF/DOCX 读取走现有 workspace 校验；
- 档案写入采用临时文件 + rename；拒绝路径穿越/符号链接逃逸；
- 抽取是启发式，不做 LLM 语义理解；错误/遗漏由用户核对 evidence 后修正；
- 不做期刊规则库自动下载。

## 7. 实施步骤

- [x] 档案存储 CRUD + 规范化 + 单测
- [x] 指南抽取（TXT/DOCX/PDF）+ 单测
- [x] service + REST + 集成测试
- [x] 前端档案面板 + 合规面板选择 + Vitest
- [x] 文档（技术 105、用户手册 27）
- [x] ruff / py38 / architecture / typecheck / tests

## 8. 非目标

- 不做 LLM 辅助抽取（后续可加，需原文引用与人工确认）；
- 不做档案市场/远程同步；
- 不做自动修改论文。
