# LaTeX 项目 zip 导入（L4a）实施计划

> 日期：2026-10-31 · 分支：`feat/latex-project-import`
> 基线：`origin/main` = `21659aaf9`（PR #2702 合并后）
> 前置：`docs/plans/2026-10-31_latex-compile.md`（L3b 已完成）
> 范围：**只做安全解压与主文件识别**；不执行/编译解压出的内容。

## 1. 目标

期刊/Overleaf 模板通常以 zip 分发。当前 L0–L3 面板要求用户先把项目解压到工作区。
本阶段提供：

- 安全解压 `.zip` 到工作区新目录；
- 识别主 `.tex`（含 `\documentclass`）；
- 返回项目目录/主文件/文件数/警告；
- 供后续 read/template/audit/compile 面板直接使用。

## 2. 安全约束

- 拒绝：绝对路径、`..` 越界、盘符、管道、加密 zip、符号链接条目；
- 拒绝 Windows 保留名/尾随点或空格/`:`（ADS）/控制字符/大小写冲突；
- 限制：压缩包 ≤100 MiB、解压总量 ≤200 MiB、单文件 ≤50 MiB、条目数 ≤2000；
- 压缩比异常（>200x 且解压 >10 MiB）拒绝（zip bomb 防护）；
- 只解压文档/资源白名单后缀；未知/脚本后缀跳过并 warning；
- 解压到工作区临时目录，成功后原子 rename 到目标目录；目标已存在拒绝覆盖；
- 不执行任何脚本、不编译 TeX。

## 3. 文件

```
backend/office/latex/project.py               # zip 校验/解压/主文件识别
backend/office/latex/service.py               # workspace 入口
backend/api/office_latex_routes.py            # /project/extract
backend/tools/office_latex_project_tool.py    # office_extract_latex_project
src/shared/api/latexApi.ts                    # extractLatexProject
src/features/office/LatexProjectImportPanel.tsx
src/pages/Office.tsx                          # 挂载面板
```

## 4. 契约

`POST /api/v1/office/latex/project/extract`

```json
{
  "workspace_path": "/ws",
  "zip_path": "/ws/downloads/ieee-template.zip",
  "output_dir_name": "ieee-template"
}
```

响应：

```json
{
  "ok": true,
  "project_dir": "ieee-template",
  "main_file": "ieee-template/main.tex",
  "main_candidates": ["ieee-template/main.tex"],
  "files_count": 42,
  "bytes_written": 1234567,
  "warnings": []
}
```

## 5. 实施步骤

- [x] zip 安全校验/解压/主文件识别 + 单元测试
- [x] service + REST + 集成测试
- [x] Agent 工具 + profile/bundle 同步
- [x] 前端导入面板 + Vitest
- [x] 文档（技术 105、用户手册 27）
- [x] ruff / py38 / architecture / typecheck / tests

## 6. 验收

- 正常 Overleaf zip 解压并识别主文件；
- `../evil`、绝对路径、符号链接、加密 zip、超限 zip 全部拒绝；
- 已存在输出目录拒绝覆盖；
- 无主文件时仍可解压但返回 warning；
- 未知后缀跳过并 warning；
- 相关测试全绿。

## 7. 非目标

- 不执行/编译解压出的内容；
- 不做 Overleaf API 直连下载；
- 不做 zip 内 git 历史/历史版本恢复；
- 不做病毒扫描（仅路径/大小/类型白名单）。
