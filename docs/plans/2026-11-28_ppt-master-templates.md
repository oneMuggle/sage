# PPT Master 集成 Phase 2：模板系统

> 日期：2026-11-28
> 分支：`feat/ppt-master-templates`
> 前置：Phase 1（SVG → 原生可编辑 PPTX）已双分支合并并归档
> （main `docs/technical/181-ppt-master-integration.md`）。

## 1. 背景与目标

Phase 1 只走 `--quick-generate` 自由设计路径：SVG 进来，质量门禁通过后
直接导出，未利用 ppt-master 的模板体系。ppt-master v6.10.0 提供四类正交
模板（`brand` / `style` / `layout` / `deck`），存放在技能目录
`templates/<kind_dir>/<id>/`，每类在目录内有 `<kind_dir>_index.json`
（如 `templates/brands/brands_index.json`）；转换前
用 `scripts/apply_template.py <project> --root <workspace>` 把模板安装到
项目的 `templates/`、`images/`、`icons/`。Quick 导出会根据页面 SVG 是否
携带 `data-pptx-*` 结构化元数据推断 `structured` / `flat`。

Phase 2 目标（对照归档路线图「模板系统：SQLite 存储模板、管理 API、
模板选择器、内置模板库」）：

1. **内置模板库索引**：扫描技能目录四类模板，落 SQLite；
2. **管理 API**：列表（可按 kind 过滤）+ 手动刷新索引；
3. **模板选择器**：Office「SVG → 可编辑 PPT」对话框内按类选择模板；
4. **转换前安装**：渲染请求携带所选模板，服务端在质量门禁/转换前调用
   `apply_template.py` 安装，支持结构化母版/版式导出；未携带则行为与
   Phase 1 完全一致（向后兼容）。

非目标（留给 Phase 3）：AI 创作 SVG、模板编辑器、图片转 PPT、旁白/动画。

## 2. 关键约束与事实

- 模板根解析复用 Phase 1：显式参数 > `SAGE_PPT_MASTER_ROOT` >
  `~/project/ppt-master/skills/ppt-master` > `/opt/agent-skills/ppt-master`，
  命中要求 `scripts/attribution_guard.py`。
- `apply_template.py` 约束：每类最多一个 root；可重复 `--root`；用
  `--skip-validation` 跳过模板自身 SVG 的重复校验（内置库随技能发布即已
  校验，避免每次渲染多跑一轮质量检查）。
- Quick 结构化是**全有或全无**：`parse_optional_layout_slides` 要求所有
  页面都声明 `data-pptx-master` / `data-pptx-layout` 等元数据，混入普通
  扁平 SVG 会直接报错。因此：选择 Layout/Deck 但页面无结构化元数据时，
  服务端回传 warning，不阻断（输出仍为扁平），前端同步提示。
- 品牌/风格模板（brand/style）不改变扁平导出的视觉，只在结构化/按模板
  创作的页面中生效；选择器需如实说明，避免「选了没效果」的误解。
- py38 兼容：win7 分支 Python 3.8，禁用 PEP 585 注解（`list[str]` /
  `dict[str, Any]`），统一 `typing.List/Dict/Optional`。

## 3. 涉及文件

### 后端（新增）

- `backend/data/migrations/v23_presentation_templates.py` — 建表迁移。
- `backend/services/presentation_template_registry.py` — 扫描 + upsert +
  查询 + 根路径解析。
- `backend/tests/presentation/test_presentation_template_registry.py`
- `backend/tests/presentation/test_presentation_templates_routes.py`
  （或并入现有 routes 测试文件）

### 后端（修改）

- `backend/data/migrations/runner.py` — 注册 v23。
- `backend/services/ppt_master_adapter.py` — 新增 `apply_templates()`。
- `backend/services/presentation_service.py` — `render_from_svgs` /
  `render_project` 接收模板 root 列表，安装后走原门禁/转换；返回
  `templates_applied`。
- `backend/api/presentation_routes.py` — `GET /templates`、
  `POST /templates/refresh`、渲染请求新增 `template_ids`。
- `backend/tests/presentation/test_presentation_service.py` /
  `test_presentation_routes.py` — 覆盖新增参数与安装顺序。

### 前端（修改）

- `src/shared/api/presentationApi.ts` — 模板列表/刷新接口、
  `template_ids` 字段。
- `src/features/presentation/PresentationDialog.tsx` — 模板选择区。
- `src/features/presentation/__tests__/PresentationDialog.test.tsx` —
  选择与提交断言。

### 文档

- 本计划文档；合并后并入 `docs/technical/181-*` 与
  `docs/user-manual/64-*`（win7 对应 185/65），随后删除本文件。

## 4. 技术方案

### 4.1 SQLite 表（v23）

```sql
CREATE TABLE IF NOT EXISTS presentation_templates (
    kind TEXT NOT NULL CHECK(kind IN ('brand','style','layout','deck')),
    template_id TEXT NOT NULL,
    name TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    primary_color TEXT,
    canvas_format TEXT,
    page_count INTEGER,
    page_types TEXT NOT NULL DEFAULT '[]',   -- JSON 数组
    root_path TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (kind, template_id)
);
CREATE INDEX IF NOT EXISTS idx_presentation_templates_kind
    ON presentation_templates(kind);
```

迁移函数幂等（`CREATE TABLE IF NOT EXISTS`），注册进 `MIGRATIONS`。

### 4.2 注册表服务

```python
@dataclass(frozen=True)
class TemplateEntry:
    kind: str
    template_id: str
    name: str
    summary: str
    primary_color: Optional[str]
    canvas_format: Optional[str]
    page_count: Optional[int]
    page_types: List[str]
    root_path: str

class PresentationTemplateRegistry:
    def __init__(self, conn_factory=None): ...
    def refresh(self) -> int: ...               # 扫描并 upsert，返回条数
    def list_templates(self, kind=None) -> List[TemplateEntry]: ...
    def ensure_fresh(self) -> None: ...         # 空表时惰性扫描
    def resolve_roots(self, template_ids: Sequence[str]) -> List[Path]: ...
```

扫描规则：

- 对每个 kind 依次扫描内置层 `templates/<kind_dir>/` 与可选用户层
  `templates/local/<kind_dir>/`，读取目录内的 `<kind_dir>_index.json`
  （如 `templates/brands/brands_index.json`）作为 summary / primary_color /
  canvas_format / page_count / page_types 权威；同名条目用户层覆盖内置层；
- 每个条目目录 `templates/<kind_dir>/<id>/templates/design_spec.md`
  必存在（否则跳过并记日志）；索引与 spec frontmatter 均**没有 name 字段**，
  `name` 直接取 template_id（前端可美化展示）；
- `root_path` 存模板根（`templates/<kind_dir>/<id>` 绝对路径）；
- 先清空再写入（简单、可收敛），单事务提交；技能目录缺失 → 抛
  `PptMasterEnvError`（API 转 503 或返回 available=false）。

`resolve_roots`：按 `template_ids`（形如 `layout:editorial_bleed`）查库，
未知名抛 `PresentationInputError`；同类多于一个抛错。渲染端点接收
`template_ids` 而不是客户端传路径，避免任意路径安装。

### 4.3 适配器安装

```python
def apply_templates(self, project_dir: Path, roots: Sequence[Path]) -> None:
    # python apply_template.py <project> --root r1 --root r2 --skip-validation
```

失败抛 `PptMasterRunError`，错误信息带 stderr。

### 4.4 服务编排

`render_from_svgs(svg_slides, output_path, template_roots=())`：

1. 写 `proj/svg_output/NN.svg`；
2. `template_roots` 非空 → `adapter.apply_templates(proj, roots)`；
3. 质量门禁 → 转换（原流程不变）。

`render_project(project_dir, output_path, template_roots=())`：同样在门禁前
安装（显式请求才执行，避免默认改写用户项目）。

结构化提示：请求含 layout/deck 且所有 SVG 均不含 `data-pptx-layout` 时，
往 `warnings` 追加一条中文提示（不阻断）。

### 4.5 API

- `GET /presentation/templates?kind=layout` →

  ```json
  {"available": true, "error": null,
   "templates": [{"kind":"layout","template_id":"editorial_bleed",
                  "name":"...","summary":"...","primary_color":null,
                  "canvas_format":"ppt169","page_count":10,
                  "page_types":["hero_full", "..."],
                  "root_path":"..."}]}
  ```

- `POST /presentation/templates/refresh` → `{"available": true, "count": 41}`
- `RenderSvgRequest` / `RenderProjectRequest` 增 `template_ids: List[str] = []`
  （最多 4 条，每类最多 1 条，服务端校验）。
- `RenderResponse` 增 `templates_applied: List[str] = []`。

### 4.6 前端

- 打开对话框时并行拉取 `environment` 与 `templates`；模板区按四类分组，
  每类一个下拉/卡片组，默认「不使用」。选项展示名称 + 摘要（title 提示）
  + 品牌色圆点（有 `primary_color` 时）。
- 选中 `layout`/`deck` 且所有已添加 SVG 不含 `data-pptx-layout` 时，显示
  内联提示「当前 SVG 未携带版式元数据，模板将以扁平方式导出」。
- 提交时发送 `template_ids`（`kind:id` 形式）；成功后展示
  `templates_applied`。

## 5. 实施步骤

- [x] 1. v23 迁移 + runner 注册
- [x] 2. 注册表服务（扫描/查询/解析） + 单测
- [x] 3. 适配器 `apply_templates` + 单测（stub 子进程）
- [x] 4. 服务支持 `template_roots` + 单测（安装先于门禁）
- [x] 5. API：列表/刷新 + 渲染 `template_ids` + 路由测试
- [x] 6. 前端 API 客户端 + 对话框选择器 + 组件测试
- [x] 7. 全量门禁：ruff、pytest（sage-backend）、vitest、tsc、架构棘轮
- [x] 8. 真机冒烟：选 layout/deck 原型渲染，确认模板安装 receipt
  - 已用真实技能目录无头验证：扫描 44 个模板（品牌 21 / 风格 14 / 版式 7 / 整套 2）、
    `resolve_roots(["layout:presentation_core"])`、`apply_templates` 生成
    `template_install.json`；带 `brand:anthropic` 真实渲染出 12.7 KB PPTX、
    `templates_applied=["anthropic"]`。Electron 界面手动冒烟留待合并前进行。
- [ ] 9. 合并后归档文档并删除本计划文件

## 6. 风险与依赖

| 风险 | 应对 |
| --- | --- |
| 模板安装耗时/磁盘复制 | 仅选模板时执行；`--skip-validation`；临时项目随渲染清理 |
| 用户误以为品牌模板会改扁平 PPT 视觉 | 前端明确提示 + 服务端 warning，不静默 |
| 技能目录/索引字段漂移 | 扫描时缺 spec 即跳过并日志；索引缺失仅保留目录项最小字段 |
| py38 类型注解 | 全部使用 `typing.List/Dict/Optional`，跑 `check_py38_compat.py` |
| 架构棘轮 | 只动现有大文件才需 bump；新增文件不入基线，实测为准 |
| 渲染项目被写入 | 仅在显式 `template_ids` 时安装，并在响应/文档说明 |
