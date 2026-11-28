# PPT Master 集成（SVG → 原生可编辑 PPTX）

> 2026-11-28 新增。把 ppt-master 技能的确定性工程层（SVG 质量门禁 + SVG → DrawingML 转换）接入 Sage，作为 Office 工作台的「SVG → 可编辑 PPT」能力。Phase 1 只含后端服务与前端对话框，不含 AI 创作与模板系统（见文末路线图）。

## 背景与目标

Sage 的 Office 工作台已经覆盖 Word / Excel / 文档解析，但缺少演示文稿的「可编辑」产出——用截图或位图拼出的 PPT 无法在 PowerPoint 里改字改色。ppt-master 提供了一条确定性链路：把一组 SVG 幻灯片经过质量门禁后，转换为**原生可编辑**的 DrawingML PPTX（文字是文本框、形状是形状）。

集成的目标是把这条链路变成 Sage 的本地能力：

- 对话或智能体产出的 SVG，用户可以直接在桌面端转成可编辑 PPTX；
- 转换前强制执行质量门禁，阻塞问题存在时**不产出文件**，让用户修复后重试；
- 不捆绑 ppt-master 源码，原位调用官方技能目录（原因见下）。

## 架构

采用「后端服务化」方案：前端只负责收集 SVG 与展示结果，全部工程转换在后端子进程中完成。

| 组件 | 文件 | 职责 |
|------|------|------|
| 编排服务 | `backend/services/presentation_service.py` | 组装临时项目、先质量门禁后转换、归一化结果 |
| 适配器 | `backend/services/ppt_master_adapter.py` | 定位技能目录、子进程调用 `attribution_guard.py` / `svg_quality_checker.py` / `svg_to_pptx.py` |
| API 路由 | `backend/api/presentation_routes.py` | `/api/v1/presentation/*` 三个端点、workspace 与产物路径校验 |
| 前端对话框 | `src/features/presentation/PresentationDialog.tsx`、`QualityReport.tsx` | SVG 导入/粘贴、页序调整、质量报告展示、任务中心登记 |
| API 客户端 | `src/shared/api/presentationApi.ts` | 认证传输（`backendRequest`），禁止裸 `fetch` |

### 为什么原位调用而不是拷贝脚本

ppt-master 的 `scripts/attribution_guard.py` 会**相对技能根目录**校验 `SKILL.md` 元数据、`LICENSE` 的 sha256、`SPONSORS` 文件以及各闸门脚本。把脚本拷进 Sage 仓库会让守卫失败（非零退出），脚本随后拒绝运行。因此适配器必须指向一份完整的官方技能目录（含 `scripts/` 与 `SKILL.md`），通过 `subprocess` 调用，**禁止拷贝**。

技能根解析优先级：

1. `PptMasterAdapter(skill_root=...)` 显式参数；
2. 环境变量 `SAGE_PPT_MASTER_ROOT`；
3. 默认位置 `~/project/ppt-master/skills/ppt-master`、`/opt/agent-skills/ppt-master`。

环境变量/默认位置既可以指向技能目录本身，也可以指向其上层仓库根——每个候选会再尝试追加 `skills/ppt-master`，只要目录内存在 `scripts/attribution_guard.py` 即命中。

调用解释器优先取 `SAGE_PPT_MASTER_PYTHON`，否则用当前后端进程的 `sys.executable`。

## 数据流

### render-svgs（一组 SVG 字符串 → PPTX）

```
入参 svg_slides[]（按顺序，每项一页）
  -> 写入临时项目 <work>/proj/svg_output/NN.svg（NN 从 01 起）
  -> svg_quality_checker.py --quick-generate --canonical-authoring --stage final --json
       报告固定落在 <proj>/validation/svg_quality_report.json
  -> blocking.count > 0 ? 中止，不转换
  -> svg_to_pptx.py --quick-generate -o <output.pptx>
  -> 返回 {success, output_path, quality_passed, blocking_errors, warnings, summary, message}
```

临时目录在请求结束后删除（`finally` 中 `shutil.rmtree`），产物按调用方给定的 `workspace_path/filename` 写出。

### render-project（已有 ppt-master 项目目录 → PPTX）

对已经存在的 ppt-master 项目目录（必须含 `svg_output/`）执行同样的「质量门禁 → 转换」，适用于高级用户手工准备项目的场景。

## 质量门禁语义

质量报告由 `svg_quality_checker.py` 产出，适配器把它归一为三层结果：

- **是否通过**：以 `categories.blocking.count == 0` 为准；该字段缺失时回退 `summary.errors`；
- **阻塞问题**：`categories.blocking.issues[]`，存在则**不转换**；
- **非阻塞警告**：`categories.introduced.issues[]` + `categories.inherited.issues[]`，不影响通过。

质量门禁不通过是**正常业务结果**，不是 HTTP 错误：端点返回 HTTP 200、`success=false`、`quality_passed=false`、携带 `blocking_errors`，且**不产生输出文件**。前端据 `quality_passed` 区分「质量门禁未通过」与「转换阶段失败」（后者 `quality_passed=true` 但 `success=false`）。

## API 契约

| 方法 | 路径 | 用途 |
|------|------|------|
| GET | `/api/v1/presentation/environment` | 技能完整性自检（`attribution_guard`） |
| POST | `/api/v1/presentation/render-svgs` | 一组 SVG 字符串 → PPTX |
| POST | `/api/v1/presentation/render-project` | 已有 ppt-master 项目目录 → PPTX |

`RenderSvgRequest`：`workspace_path`、`filename`、`svg_slides[]`（均为必填，字符串非空）。

`RenderResponse`：

```json
{
  "success": true,
  "output_path": "/abs/path/presentation.pptx",
  "quality_passed": true,
  "blocking_errors": [],
  "warnings": [],
  "summary": {"total": 3, "passed": 3, "warnings": 0, "errors": 0},
  "message": "生成成功"
}
```

`EnvironmentResponse`：`{ready, skill_root?, python?, error?}`。

状态码约定：

| 场景 | 状态码 |
|------|--------|
| 正常渲染（含质量门禁不通过） | 200 |
| 入参非法（页数/大小/文件名越界、workspace 不合法） | 400 |
| 环境不可用时渲染 | 200 + `success=false`（`environment` 端点以 `ready=false` 提前暴露） |

端点为同步 `def`，由 FastAPI 放入线程池执行，避免阻塞事件循环（子进程调用是阻塞的）。

## 安全与边界约束

- **无 shell**：子进程以参数列表传入，杜绝命令注入；工作目录固定为技能根；
- **超时**：单次调用默认 180 秒，超时抛 `PptMasterRunError`；
- **编码**：stdout/stderr 统一 UTF-8 解码、`errors="replace"`，避免 Windows 控制台编码崩溃；
- **路径围栏**：`workspace_path` 经 `validate_workspace` 校验，产物路径经 `resolve_within` 约束在 workspace 内；`filename` 只允许文件名、必须以 `.pptx` 结尾；
- **资源上限**：单次最多 200 页、单页 SVG ≤ 5 MB、空页直接拒绝。

## 环境配置与排障

| 变量 | 作用 | 默认 |
|------|------|------|
| `SAGE_PPT_MASTER_ROOT` | 技能目录或其仓库根 | 先试 `~/project/ppt-master/skills/ppt-master`，再试 `/opt/agent-skills/ppt-master` |
| `SAGE_PPT_MASTER_PYTHON` | 调用技能脚本的解释器 | 后端进程的 `sys.executable` |

依赖：`python-pptx==0.6.23`（转换核心）。`XlsxWriter` / `skia-pathops` / `uharfbuzz` 为可选增强；`PyMuPDF` 仅在 pdf_to_md 工具校验流程中使用（AGPL），因此**不捆绑**技能，只做原位调用。

常见错误对照：

| 现象 | 原因 | 处理 |
|------|------|------|
| `environment` 返回 `ready=false`，提示“未找到 ppt-master 技能目录” | 技能目录缺失或路径未设 | 设置 `SAGE_PPT_MASTER_ROOT` |
| `ready=false`，提示“完整性校验失败” | 技能目录被改动/不完整 | 恢复完整官方技能目录（守卫按相对路径校验） |
| `ready=false`，提示解释器不可用 | `SAGE_PPT_MASTER_PYTHON` 指向不存在 | 修正解释器路径 |
| 运行时报 `ModuleNotFoundError: pptx` | 解释器环境缺 `python-pptx` | 在该解释器环境安装依赖或改用后端环境 |

> 技能脚本要求 Python ≥ 3.9。若用较低版本的解释器调用（例如 `release/win7` 的 Python 3.8 后端），技能脚本会因运行时语法不兼容而失败，须把 `SAGE_PPT_MASTER_PYTHON` 指向 ≥ 3.9 的解释器。

## 前端

Office 页新增「SVG → 可编辑 PPT」区块，点「打开」弹出 `PresentationDialog`（`size="xl"`）：

- **每次打开重新自检环境**——技能目录/解释器可能被移动或卸载，同时清空上一轮产物与错误；
- **导入方式**：多选 `.svg` 文件（按添加顺序即页序），或在「或粘贴 SVG 源码」中粘贴含 `<svg>` 的文本；
- **页序管理**：每页可上移/下移/移除，显示文件名与大小；
- **文件名**：默认 `presentation.pptx`，未以 `.pptx` 结尾时自动补全；
- **提交**：需绑定工作区、至少一页、环境 `ready` 才可点击「生成 PPTX」；
- **任务中心**：渲染期间注册 `presentation:render` 任务，成功/失败如实回写；
- **质量报告**：`QualityReport` 显示状态标签（生成成功 / 生成未完成 / 质量门禁未通过）、页数统计、阻塞问题与警告（各最多显示 50 条），成功时给出产物路径。

若未绑定工作区，对话框提示“请先绑定工作区后再生成演示文稿”。

## 测试

- 后端 36 个：适配器 13、服务 13、路由 9、真实冒烟 1。真实冒烟需要真实技能目录（`SAGE_PPT_MASTER_ROOT`），不具备时自动 SKIP；
- 前端 7 个：对话框导入/校验/提交/质量报告渲染。

## 已知限制与路线图

**Phase 1（已完成）**

- SVG 由对话/智能体或手工产出，本集成不做 AI 创作；
- 只走 `--quick-generate` 快速导出路径，模板系统未接入；
- 不支持 PDF/图片直接转 PPT。

**Phase 2（规划）**

- 模板系统：SQLite 存储模板、管理 API、模板选择器、内置模板库。

**Phase 3（规划）**

- 编辑美化、图片转 PPT、音频旁白、动画。
