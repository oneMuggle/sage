# LaTeX 编译与红字版（L3b）实施计划

> 日期：2026-10-31 · 分支：`feat/latex-l3b`
> 基线：`origin/main` = `38d1179d1`（PR #2700 合并后）
> 前置：`docs/plans/2026-10-31_latex-audit.md`（L3a 已完成）
> 范围：**可选外部引擎编译 + latexdiff 红字版**；不捆绑 TeX，不做完整 OS 级沙箱（见安全边界）。

## 1. 目标

- 检测本机 TeX 引擎（latexmk/xelatex/lualatex/pdflatex）；
- 在临时目录编译 `.tex` 项目为 PDF，输出到工作区；
- 编译前**强制运行 L3a 审计**：存在 error（含危险命令）即拒绝编译；
- 检测 `latexdiff`，生成 `diff.tex`（可选编译 `diff.pdf`）；
- REST + Agent 工具 + 能力探测；
- 无引擎/无 latexdiff 时返回可读降级信息。

## 2. 安全边界（重要）

本阶段**不是完整沙箱**，只做“最小安全编译”：

- 编译前审计拒绝：`\write18`、`\openin`、`\openout`、管道/绝对路径 include 等；
- 子进程参数固定：`-no-shell-escape -interaction=nonstopmode -halt-on-error`；
- `openin_any=p`、`openout_any=p`；临时 `TEXMFHOME/TEXMFVAR/TEXMFCACHE`；
- 只复制项目目录内文件到临时目录；超时/大小/文件数限制；
- 不联网、不下载宏包、不捆绑 TeX；
- **Win7/无 OS 隔离环境仍存在风险**：编译视为“可信文档 + 显式用户操作”的可选功能；
  后续如需处理不可信文档，必须接入容器/低权限用户等 OS 级隔离。

## 3. 文件

```
backend/office/latex/compile.py     # 引擎探测、编译、能力位
backend/office/latex/diff.py        # latexdiff 适配
backend/office/latex/service.py     # compile/diff workspace 入口
backend/api/office_latex_routes.py  # /compile、/diff
backend/tools/office_latex_compile_tool.py
backend/tools/office_latex_diff_tool.py
```

## 4. 契约

`POST /api/v1/office/latex/compile`

```json
{
  "workspace_path": "/ws",
  "file_path": "/ws/paper/main.tex",
  "output_filename": "main.pdf",
  "engine": "latexmk",
  "timeout_s": 60
}
```

响应：

```json
{
  "ok": true,
  "engine": "latexmk",
  "pdf_path": "paper/main.pdf",
  "returncode": 0,
  "log_tail": "...",
  "duration_ms": 1234
}
```

`POST /api/v1/office/latex/diff`

```json
{
  "workspace_path": "/ws",
  "original_path": "/ws/paper/v1.tex",
  "revised_path": "/ws/paper/v2.tex",
  "output_filename": "diff.tex",
  "compile_pdf": false
}
```

响应 `{ok, diff_path, pdf_path?, latexdiff_available}`。

## 5. 实施步骤

- [x] 引擎/工具探测与编译适配器（测试用 stub，不依赖本机 TeX）
- [x] 编译前 audit gate + 临时目录复制 + 超时/输出限制
- [x] latexdiff 适配
- [x] REST + 集成测试
- [x] Agent 工具 + profile/bundle 同步
- [x] 文档（技术 105、用户手册 27）
- [x] ruff / py38 / architecture / typecheck / tests

## 6. 验收

- 无引擎时返回明确降级信息，不写文件；
- 审计 error 时拒绝编译，原文件不变；
- stub 引擎成功时 PDF 复制到工作区，输出路径无覆盖；
- latexdiff 缺失时降级；成功时生成 diff.tex；
- 命令参数含 `-no-shell-escape`、`openin_any=p`、`openout_any=p`；
- 相关测试全绿。

## 7. 非目标

- 不捆绑 TeX Live/MiKTeX/Tectonic；
- 不做容器/OS 级沙箱（L4 或部署层）；
- 不做 PDF 版式/字体/页数审计（可后续基于渲染结果）；
- 不自动修复源码。

## 8. 实施记录（2026-10-31）

已完成：

- `compile.py`：引擎探测（latexmk/xelatex/lualatex/pdflatex）、强制 audit gate、临时目录复制、
  `-no-shell-escape` / `openin_any=p` / `openout_any=p`、超时与日志尾部；
- `diff.py`：latexdiff 适配，生成 `diff.tex`，可选编译红字版 PDF；
- REST `/office/latex/compile`、`/diff`、`/capabilities`；
- Agent 工具 `office_compile_latex` / `office_latexdiff`（WRITE_LOCAL、workspace 围栏）；
- 前端 `LatexBuildPanel`（Office 页：编译 PDF / 生成红字版）+ `latexApi` 能力探测；
- 测试：L3b 相关 32 项 + 全量 LaTeX 回归；前端构建/审校/模板/Office/fontScaleGate；
- 文档：技术 105、用户手册 27。

未做：容器/OS 级沙箱、PDF 版式/字体/页数审计、自动修复。编译能力依赖本机 TeX 引擎；
无引擎/无 latexdiff 时返回可读降级信息。
