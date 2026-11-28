# PPT Master 集成方案设计

> 日期：2026-11-28
> 状态：Phase 1 已交付（M1 后端 + M2 前端 UI + 浏览器 E2E 验证）
> 分支：feat/ppt-master-integration

---

## 1. 背景与目标

### 1.1 背景

sage 当前已有基础 PPT 生成能力（`backend/office/ppt.py`），但存在以下局限：

- 生成质量有限：LLM JSON → 基础 PPTX，缺少视觉设计能力
- 无模板系统：不支持 Brand/Style/Layout 等高级模板
- 无质量控制：缺少生成后的验证机制
- 无高级功能：不支持 PPT 编辑/美化、音频旁白、动画等

ppt-master 是一个成熟的 PPT 生成工作流，具备：
- SVG 中间表示：AI 生成 SVG → DrawingML 转换
- 模板系统：Brand/Style/Layout/Deck 四类模板
- 质量门禁：svg_quality_checker.py
- 丰富功能：图片转 PPT、美化、编辑、旁白等

### 1.2 目标

将 ppt-master 的核心能力集成到 sage，实现：

1. **高质量 PPT 生成**：通过 SVG 中间表示提升视觉质量
2. **模板复用**：支持用户自定义和品牌模板
3. **质量反馈**：生成后自动质量检查并展示报告
4. **渐进增强**：分阶段实施，快速交付核心价值

---

## 2. 架构设计

### 2.1 集成方式：服务封装

采用**方案 B：后端服务化**，将 ppt-master 脚本封装为 sage 后端服务。

> **关键决策（实测后修订）：原位调用，不拷贝。**
> `scripts/attribution_guard.py` 会相对技能根目录校验 `SKILL.md` 元数据、
> `LICENSE` 的 sha256、`SPONSORS*.md` 与各闸门脚本结构；把脚本拷到别处会让
> 守卫非零退出、脚本拒绝运行。因此适配器必须指向一份**完整的官方技能目录**，
> 通过 subprocess 原位调用（同时规避许可证再分发问题，并让上游升级独立生效）。

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend (React)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ PPT 生成对话框 │  │ 模板选择器    │  │ 质量报告面板     │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                     Backend (FastAPI)                        │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              PresentationService                      │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │  │
│  │  │ generate()  │  │ beautify()  │  │ edit()      │  │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  │  │
│  └──────────────────────────────────────────────────────┘  │
│                            │                                │
│                            ▼                                │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              PptMasterAdapter                         │  │
│  │   封装 ppt-master 脚本调用（subprocess）               │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    ppt-master scripts                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ svg_to_pptx  │  │ quality_check│  │ project_manager  │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 核心组件

| 组件 | 职责 | 文件位置 |
|------|------|----------|
| `PresentationService` | 业务逻辑编排 | `backend/services/presentation_service.py` |
| `PptMasterAdapter` | ppt-master 脚本调用 | `backend/services/ppt_master_adapter.py` |
| API Routes | HTTP 端点 | `backend/api/presentation_routes.py` |
| 前端对话框 | 用户交互 | `src/features/presentation/` |

### 2.3 数据流

Phase 1 交付的是**确定性工程层**（SVG → PPTX），不含 AI 创作。AI 生成 SVG
的部分由上层智能体/对话流负责，产出一组 SVG 后调用本服务。两条入口：

```
调用方（智能体 / 前端对话框 / 已有 ppt-master 项目）
    │
    ▼
PresentationService.render_from_svgs(svg_slides, output_path)   # 一组 SVG 字符串
  或 PresentationService.render_project(project_dir, output_path) # 已有项目目录
    │
    ├─→ 组装临时项目 <work>/proj/svg_output/NN.svg
    │
    ├─→ PptMasterAdapter.quality_check()
    │       └─→ svg_quality_checker.py --quick-generate --canonical-authoring --stage final --json
    │           （写 validation/svg_quality_report.json；blocking.count==0 才算通过）
    │       └─→ 不通过则**中止**，返回 blocking_errors（不转换）
    │
    ├─→ PptMasterAdapter.convert_to_pptx()
    │       └─→ svg_to_pptx.py --quick-generate -o <out.pptx>（原生可编辑 DrawingML）
    │
    └─→ 返回 RenderResult（输出路径 + 质量摘要 + 阻塞/警告）
```

---

## 3. 实施计划

### Phase 1：核心集成（1-2 周）

#### M1：后端服务封装

- [x] **原位调用**官方技能目录（不拷贝；`attribution_guard` 相对自身根校验）
- [x] 创建 `PptMasterAdapter` 封装类（subprocess、超时、UTF-8、无 shell）
- [x] 创建 `PresentationService` 业务服务（质量门禁 + 转换编排）
- [x] 添加 API 端点 `/api/v1/presentation/*`（environment / render-svgs / render-project）
- [x] 单元测试与环境/转换冒烟（36 项，含真实 1 页 SVG→PPTX）

#### M2：前端基础 UI

- [x] PPT 生成对话框组件
- [x] 质量报告展示面板
- [x] 与现有 Office 工作台集成

### Phase 2：模板系统（2-3 周）

- [ ] 模板数据模型（SQLite）
- [ ] 模板管理 API
- [ ] 前端模板选择器
- [ ] 内置模板库

### Phase 3：高级功能（4-6 周）

- [ ] PPT 编辑/美化
- [ ] 图片转 PPT
- [ ] 音频旁白
- [ ] 动画定制

---

## 4. 涉及文件

### 新增文件

| 文件 | 用途 |
|------|------|
| `backend/services/presentation_service.py` | 演示文稿业务服务 |
| `backend/services/ppt_master_adapter.py` | ppt-master 脚本适配器（原位调用） |
| `backend/api/presentation_routes.py` | HTTP 端点 |
| `backend/tests/presentation/` | 适配器/服务/路由测试 |
| `src/shared/api/presentationApi.ts` | 鉴权前端 API 客户端（`backendRequest` 封装） |
| `src/features/presentation/PresentationDialog.tsx` | 生成对话框（Phase 1 前端） |
| `src/features/presentation/QualityReport.tsx` | 质量报告组件（Phase 1 前端） |
| `src/features/presentation/index.ts` | 统一导出 |
| `src/features/presentation/__tests__/PresentationDialog.test.tsx` | 对话框单元测试（7 项） |

> **不新增** `backend/vendor/ppt_master/`：技能保持原位，由
> `SAGE_PPT_MASTER_ROOT` 指向（可选 `SAGE_PPT_MASTER_PYTHON` 指定解释器，
> 默认用后端自身解释器）。

### 修改文件

| 文件 | 改动 |
|------|------|
| `backend/main.py` | 注册 presentation 路由 |
| `src/shared/ui/Modal.tsx` | 复用 main 已有的 `size` 宽度档位（`'xl'`）承载宽对话框，不再另加 prop |
| `src/pages/Office.tsx` | 添加「SVG → 可编辑 PPT」入口 + PresentationDialog 挂载（Phase 1 前端） |

---

## 5. 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| ppt-master 脚本依赖冲突 | 中 | 使用独立虚拟环境或子进程隔离 |
| SVG 生成质量不稳定 | 高 | 添加质量门禁，低于阈值时重试 |
| 许可证冲突（PyMuPDF AGPL） | 低 | 原位调用、不捆绑再分发；sage 侧不 import PyMuPDF |
| 性能（子进程调用开销） | 低 | 异步调用 + 进度反馈 |

---

## 6. 依赖项

### 运行方式

默认用**后端自身解释器**（`sys.executable`，即 `sage-backend`）执行技能脚本；
如需隔离，用 `SAGE_PPT_MASTER_PYTHON` 指向一个装好技能依赖的独立解释器。
sage 不需要把整套 ppt-master 依赖打进自身 `requirements.txt`。

### 依赖矩阵

| 依赖 | 状态 | 说明 |
|------|------|------|
| `python-pptx` | ✅ 已在 `requirements.txt`/`requirements-py38.txt` 钉 0.6.23 | 基础 SVG→PPTX 必需（实测可出原生可编辑 PPTX） |
| `XlsxWriter` | 可选 | 部分导出旁路；未装不影响基础转换 |
| `skia-pathops` / `uharfbuzz` | 可选 | 增强能力（Merge Shapes 物化 / 文字轮廓）；缺失只降级，不阻断 |
| `PyMuPDF` | 可选（AGPL） | 仅 `pdf_to_md.py` 转换 PDF 源时用，本服务不触达 |
| `edge-tts` | 可选 | 仅音频旁白（Phase 3） |

---

## 7. 验收标准

### Phase 1 验收

- [x] 一组 SVG（由对话/智能体产出）可经对话框导出为可编辑 PPTX（真实 PPTX 12.7 KB，浏览器端到端跑通）
- [x] 生成的 PPT 包含原生可编辑的文本和形状（ppt-master DrawingML 合同，真实产物已在 /tmp/ppt-verify-ws/ 验证）
- [x] 质量报告正确显示阻塞/非阻塞问题，阻塞时不产出文件（成功有 output path + warnings；阻塞有 blocking_errors 提示 + 无 output path）
- [x] 前端进度/结果反馈正确展示（任务中心注册、toast、QualityReport、忙态禁用按钮）
- [x] 单元测试覆盖核心服务逻辑（后端 36 项 + 前端 7 项）
