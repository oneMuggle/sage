# 项目治理 AI 辅助方案（2026-10-27）

> 分支：`feat/project-governance-ai`
> 目标：解决「项目类型如何确定和修改」「如何引导用户确定治理方案」「确定方案后如何让 AI 辅助治理」三个歧义点。

## 背景与目标

### 现状诊断

| 维度 | 现状 | 痛点 |
|------|------|------|
| 类型检测 | `backend/services/project_type_detector.py` signal 加权评分，仅 4 类（coding/research/business/personal） | 不区分技术栈子类型；用户选了 "coding" 后仍不知如何治理 |
| 创建向导 | `ProjectCreationWizard.tsx` 3 步表单（选目录→选类型→确认脚手架） | 单向表单，类型靠用户猜；模板盲选无理由说明 |
| 规则/约束 | 19 个预设模板 + CRUD（`project_constraint_repo.py`） | 用户不知道需要哪些规则；无项目专属定制规则 |
| AI 顾问 | `project_advisor.py` 健康评分（0-100）+ 风险 + 建议 | 只做事后评估，不做事前引导，不生成规则 |
| 治理页面 | `ProjectGovernance.tsx` 6 tab | 功能全但入口深，缺"下一步做什么"引导 |

### 竞品对标

| 能力 | Cursor | Windsurf | Cline | Copilot | Claude Code | Sage 目标 |
|------|--------|---------|-------|---------|-------------|-----------|
| 项目类型检测 | 手动 glob | 手动 | 检测竞品规则文件 | 自动发现 | `/init` 深度扫描 | **两级分类 + 内容解析** |
| 引导方式 | Settings UI | Settings UI | Rules 面板 | agents tab | `/init` 命令 | **LLM 对话式分析向导** |
| 规则生成 | `/Generate Rules` | ❌ | ❌ | Cloud Agent 一键 | `/init` 自动生成 | **AI 从代码库推导规则** |
| 持续学习 | ❌ | Memories | ❌ | ❌ | Auto Memory | **从纠正中捕获候选规则** |
| 规则作用域 | 4 层 | 2 层 | 3 层 | 4 层 | 4 层 | **复用五层上下文 L1-L5** |

**结论**：Sage 已有完整的数据底座（五层上下文、19 模板、archetype blueprint、milestone/stage 系统），
缺失的是「AI 把这些底座串起来」的一层。本方案补这一层，不重造轮子。

## 技术方案

### 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│  前端                                                          │
│  ProjectAnalysisWizard  (新, 替换 ProjectCreationWizard Step2)  │
│    ├── ProjectAnalysisReport  (新, 分析报告卡 + toggle)         │
│    ├── ProjectTypeSelector     (增强, 两级分类)                 │
│    └── TypeDetectionPreview    (增强, 展示子类 + 信号明细)      │
│  ProjectGovernance                                             │
│    └── AiGovernancePanel (新, P2) / ProjectAdvisorCard (增强)    │
└─────────────────────────────────────────────────────────────────┘
                            │ REST
┌─────────────────────────────────────────────────────────────────┐
│  后端                                                          │
│  project_type_detector.py  (增强: 子类型 + 内容解析)            │
│  project_profiler.py       (新: 代码库结构化画像)                │
│  project_analysis_agent.py (新: LLM 深度分析 → 治理方案)        │
│  project_rule_generator.py (新: LLM 规则生成)                   │
│  project_advisor.py        (增强: 复用 profiler)                │
│  project_routes.py         (新增 4 个端点)                      │
└─────────────────────────────────────────────────────────────────┘
```

### 1. 两级项目类型分类

保持向后兼容：`ProjectType` 仍是 4 值 union（`coding|research|business|personal`），
新增 `ProjectSubType` 作为二级维度，**不改变数据库 schema**，通过 `project.detected_type` 复用存储。

```python
# backend/services/project_subtypes.py（新增）
CODING_SUBTYPES = {
    "python_backend":   ["fastapi", "django", "flask", "uvicorn", "pytest"],
    "typescript_frontend": ["react", "vue", "svelte", "vite", "next"],
    "fullstack_web":    ["同时含前后端信号"],
    "desktop_app":      ["electron", "tauri"],
    "data_science":     ["pandas", "numpy", "jupyter", "torch"],
    "rust_systems":     ["cargo", "tokio", "axum"],
    "go_services":      ["go.mod", "gin", "grpc"],
    "java_spring":      ["pom.xml", "spring-boot"],
    "mobile_app":       ["react-native", "flutter"],
}
RESEARCH_SUBTYPES = ["academic_paper", "grant_proposal", "literature_review", "lab_experiment"]
BUSINESS_SUBTYPES = ["contract_mgmt", "report_writing", "archive_dossier", "presentation"]
PERSONAL_SUBTYPES  = ["knowledge_base", "journal", "todo_planning", "learning_notes"]
```

**检测算法升级**（`project_type_detector.py`）：

1. 保留现有 signal 打分 → 得到 L1 类型（不破坏现有行为）
2. 新增 `detect_sub_type(path, level1_type)`：
   - 解析 `package.json` → dependencies/devDependencies → 匹配前端/桌面/移动特征
   - 解析 `pyproject.toml` / `requirements.txt` → 匹配 Python 后端/数据科学特征
   - 解析 `Cargo.toml` / `go.mod` / `pom.xml`
   - 目录结构启发：`src/` + `tests/` → 通用工程；`notebooks/` → 数据科学
3. 内容解析失败时回退到 L1（`None` 表示"仅知 L1"），**不猜测**

同时输出 `tech_stack: List[str]`（供 LLM 分析与报告展示用）。

### 2. 项目画像采集器（ProjectProfiler）

`backend/services/project_profiler.py`（新增）——确定性扫描，不调 LLM，产出结构化画像：

```python
@dataclass
class ProjectProfile:
    root: str
    level1_type: Optional[str]
    sub_type: Optional[str]
    tech_stack: List[str]
    frameworks: List[str]
    build_commands: List[str]      # 从 package.json scripts / Makefile / pyproject 提取
    test_frameworks: List[str]    # pytest / vitest / jest / playwright
    lint_configs: List[str]       # ruff / eslint / mypy 配置
    ci_workflows: List[str]       # .github/workflows/*.yml
    existing_rule_files: List[str]  # CLAUDE.md / .cursorrules / .editorconfig / AGENTS.md
    directory_layout: List[str]    # 顶层目录（限 20）
    source_samples: List[SourceSample]  # 采样 ≤8 个核心源文件（各 ≤120 行）
    git_stats: GitStats            # commit 数 / 近 30 天活跃度 / 分支数
    vcs_mode: str
```

**安全约束**（重要）：
- 源码采样必须**排除**敏感路径：`.env*`、`secrets/`、`*.pem`、`*.key`、`id_rsa`、`credentials*`、`.git/`
- 采样总量上限：8 文件 × 120 行 = 960 行，防止 prompt 爆炸
- 路径穿越防护：所有 glob 结果必须 `resolve()` 后校验在 root 之内

### 3. LLM 深度分析（ProjectAnalysisAgent）

`backend/services/project_analysis_agent.py`（新增）——对标 Claude Code `/init` + Copilot Cloud Agent。

**输入**：`ProjectProfile`
**输出**：`AnalysisReport`

```python
@dataclass
class SuggestedRule:
    template_key: str          # 已有模板 key，或 "ai_custom"
    label: str
    reason: str                # 为什么推荐（引用具体检测信号）
    confidence: float
    category: str
    content: str               # ai_custom 时的规则正文
    trigger_pattern: str
    priority: int

@dataclass
class AnalysisReport:
    level1_type: str
    sub_type: Optional[str]
    confidence: float
    tech_stack: List[str]
    architecture_summary: str
    suggested_rules: List[SuggestedRule]
    governance_recommendations: List[str]
    stage_recommendation: Optional[str]
    sage_md_draft: str
    docs_refs: List[Dict[str,str]]   # {"title":..., "reason":..., "path":...}
```

**LLM 不可用时的降级**（关键 — 桌面端可能没配 LLM）：
- `ProjectAnalysisAgent.available` 为 False 时，返回**纯规则**的报告：
  - L1/L2 由确定性检测给出
  - `suggested_rules` 由技术栈 → 模板映射表给出（`tech_stack` 命中 `python_default` 等）
  - `sage_md_draft` 由 archetype blueprint 模板填充
  - `governance_recommendations` 由确定性启发规则给出（检测到 `.github/workflows` → 建议 CI 门禁等）
- 端点永远返回 200，不因 LLM 缺失而 5xx

**JSON 解析健壮性**：复用 `project_advisor._parse_response` 的思路（剥离 ```json 围栏 + 找首个 `{` 到末个 `}`），但抽成共享工具 `backend/services/llm_json.py`。

### 4. AI 规则生成（ProjectRuleGenerator）

`backend/services/project_rule_generator.py`（新增）——对标 Cursor `/Generate Cursor Rules`。

基于 `ProjectProfile` + 用户确认的 `AnalysisReport`，LLM 生成：
1. `sage_md_draft`（项目级 AI 行为约束）—— 已含在 AnalysisReport 中
2. 项目**专属** constraints（`ai_custom`）：不是通用模板，而是从实际代码风格推导的规则
3. 推荐 milestone 模板

**去重**：生成后与项目已有 constraints 比对（content 归一化后比较），跳过重复。

### 5. API 端点

`backend/api/project_routes.py` 新增：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/projects/analyze` | POST | 采集画像 + LLM 分析 → `AnalysisReport` |
| `/projects/profile` | POST | 仅采集确定性画像（不调 LLM，供调试/快速预览） |
| `/projects/generate-rules` | POST | 基于 report 生成专属规则 → constraints 草稿 |
| `/projects/sub-types` | GET | 返回所有 L1 → L2 子类型定义（前端渲染选择器） |

**响应 schema** 加到 `backend/api/project_schemas.py`。

### 6. 前端改造

#### 6.1 `src/features/project-type/ProjectAnalysisWizard.tsx`（新增）

替换 `ProjectCreationWizard` 的 Step 2。流程：

```
Step 1 选择文件夹（沿用）
  ↓
Step 2 「AI 治理分析」  ← 新
  ├── 自动触发 /projects/analyze
  ├── 展示 ProjectAnalysisReport：
  │     ├── 类型判定卡（L1 + L2 + 置信度 + 信号明细）
  │     ├── 技术栈与架构摘要
  │     ├── 推荐规则包列表（每条带 reason + toggle 开关）
  │     ├── 治理建议列表（可勾选采纳）
  │     ├── 推荐文档链接
  │     └── 重新分析按钮
  ├── 用户可手动改类型/子类型
  └── 「跳过 AI 分析，手动选择」降级入口（LLM 不可用时自动展开）
  ↓
Step 3 确认并初始化（沿用，但规则包列表来自 report 而非 blueprint 默认）
```

**LLM 不可用降级**：端点返回的 report 中 `llm_available: false` + 规则仍可用（确定性映射），
UI 显示「未配置 LLM，已基于文件特征生成基础建议」。

#### 6.2 `src/features/project-type/ProjectTypeSelector.tsx`（增强）

支持两级：先选 L1，再选 L2（该 L1 下的子类型卡片网格）。子类型由 `projectApi.getSubTypes()` 拉取。

#### 6.3 `src/features/project-type/TypeDetectionPreview.tsx`（增强）

展示 `sub_type` / `tech_stack` / 更细的信号明细。

#### 6.4 `src/shared/api/projectApiTypes.ts` + `projectApi.ts`

新增类型与 API 方法。

## 实施步骤

- [x] **Step 1**: 后端 — `project_subtypes.py` 两级类型定义 + 映射表（20 子类型，L1 不变）
- [x] **Step 2**: 后端 — `project_type_detector.py` 增强（子类型检测 + 技术栈提取 + 内容解析 6 种清单 + 23 个既有测试仍绿）
- [x] **Step 3**: 后端 — `project_profiler.py` 画像采集器（14 维度 + 敏感路径黑名单 + 8×120 采样上限 + 路径穿越校验 + 23 个单元测试）
- [x] **Step 4**: 后端 — `llm_json.py` 共享 JSON 解析工具（3 策略解析 + 8 个单元测试）
- [x] **Step 5**: 后端 — `project_analysis_agent.py` LLM 分析 + 确定性降级（13 个单元测试）
- [x] **Step 6**: 后端 — `project_rule_generator.py` 规则生成（模板 + AI 专属 + 去重 + 里程碑，12 个单元测试）
- [x] **Step 7**: 后端 — `project_schemas.py` + `project_routes.py` 新增端点（analyze / profile / generate-rules / sub-types）
- [x] **Step 8**: 前端 — `projectApiTypes.ts` / `projectApi.ts` 类型与 API
- [x] **Step 9**: 前端 — `ProjectAnalysisWizard.tsx` + `ProjectAnalysisReport.tsx`（容器 + 纯展示；支持 LLM 不可用降级 / 手动覆盖 L1+L2）
- [x] **Step 10**: 前端 — `ProjectTypeSelector` / `TypeDetectionPreview` 增强
- [x] **Step 11**: 前端 — `ProjectCreationWizard` 接入新向导
- [x] **Step 12**: 测试 — 后端单测 + 前端组件测试

## 风险评估与依赖

| 风险 | 缓解 |
|------|------|
| LLM 未配置 / 调用失败 | 确定性降级路径，端点不 5xx；前端显式提示 |
| 采样源码泄露敏感信息 | 敏感路径黑名单 + 路径穿越校验 + 行数上限 |
| LLM 返回非法 JSON | `llm_json.py` 多级回退（围栏剥离 → 括号定位 → 抛错） |
| prompt 过长 | 采样上限 8 文件 × 120 行；画像字段裁剪 |
| 现有检测行为被破坏 | L1 检测逻辑完全保留，仅新增；现有单测必须仍绿 |
| 前后端类型漂移 | TS 类型与 Pydantic schema 一一对应，加 round-trip 测试 |

**依赖**：
- 现有 `backend.orchestration.llm_factory.build_llm_client_from_settings()`
- 现有 `backend/data/project_constraint_repo.CONSTRAINT_TEMPLATES`（19 模板）
- 现有 `backend/services/project_archetype_scaffold.ARCHETYPE_BLUEPRINTS`

**不做**（超出本期范围）：
- 运行时持续学习（从对话纠正捕获规则）— P2 独立迭代
- 自动治理执行（pre-commit hook / PR review）— P3
- 规则冲突检测 — P2
- 跨工具兼容（AGENTS.md 导出）— P3
