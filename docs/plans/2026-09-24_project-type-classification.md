# 项目类型分类系统设计方案

> 创建日期: 2026-09-24
> 状态: 设计中
> 分支: feat/project-type-classification

## 1. 背景与目标

### 1.1 现状问题

Sage 当前的"项目"功能采用单一模型，所有项目共享相同的数据结构和 UI：

- **单一项目类型**: 编码项目、科研项目、事务项目使用相同的功能集
- **无 VCS 集成**: 文档版本仅靠 SQLite 快照，缺乏与 git 等版本控制系统的深度集成
- **约束系统薄弱**: `instructions` 是纯文本字段，无结构化分类和触发机制
- **Wiki 与项目弱耦合**: Wiki 更像全局知识库，非项目专属的结构化文档系统

### 1.2 目标

1. **引入项目类型分类**: 支持编码(coding)、科研(research)、事务(business)、个人(personal)四种类型
2. **差异化功能集**: 不同类型激活不同工具、约束模板、Wiki 结构
3. **VCS 双轨策略**: 编码项目集成 git；一般项目增强内置快照
4. **结构化约束系统**: 替代纯文本 instructions，支持分类/触发/优先级

### 1.3 设计原则

- **渐进增强**: 现有项目默认 `type=null`，保持向后兼容
- **类型驱动**: 项目类型决定 UI 组件、可用工具、约束模板
- **最小侵入**: 核心表新增字段，不破坏现有 API 契约

---

## 2. 数据模型变更

### 2.1 projects 表扩展

```sql
-- 新增字段
ALTER TABLE projects ADD COLUMN project_type TEXT DEFAULT NULL;
-- 值: 'coding' | 'research' | 'business' | 'personal' | NULL (遗留项目)

ALTER TABLE projects ADD COLUMN project_stage TEXT DEFAULT NULL;
-- 项目阶段，按类型有不同枚举值

ALTER TABLE projects ADD COLUMN vcs_mode TEXT DEFAULT 'builtin';
-- 值: 'git' | 'builtin' | 'svn' (实验性)

ALTER TABLE projects ADD COLUMN detected_type TEXT DEFAULT NULL;
-- 自动检测结果（不覆盖用户手动选择）
```

### 2.2 新增 project_constraints 表

```sql
CREATE TABLE project_constraints (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    category TEXT NOT NULL,        -- 约束类别
    content TEXT NOT NULL,         -- 约束内容（自然语言）
    trigger_pattern TEXT,          -- 触发条件（glob 模式或 'always'）
    priority INTEGER DEFAULT 5,    -- 1-10，高优先级覆盖低优先级
    enabled INTEGER DEFAULT 1,     -- 0=禁用, 1=启用
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_constraints_project ON project_constraints(project_id, enabled);
```

**约束类别枚举**（按项目类型预设）:

| 类别 | 适用类型 | 示例 |
|------|---------|------|
| `coding_style` | coding | "使用双引号，函数不超过 50 行" |
| `security` | coding | "禁止硬编码密钥，所有 API 用参数化查询" |
| `testing` | coding | "新功能必须有单元测试，覆盖率 >= 80%" |
| `architecture` | coding | "遵循分层架构，禁止跨层调用" |
| `academic_writing` | research | "使用 APA 引用格式，避免第一人称" |
| `data_ethics` | research | "涉及人体数据须说明伦理审批" |
| `experiment_record` | research | "实验记录须包含日期/方法/结果/分析" |
| `document_format` | business | "使用公司模板，标题用宋体三号" |
| `approval_flow` | business | "重要文档须经过审批流程" |
| `confidentiality` | business | "标注保密等级：内部/机密/绝密" |
| `tagging` | personal | "使用统一标签体系" |
| `privacy` | personal | "不记录敏感个人信息" |

### 2.3 新增 project_milestones 表

```sql
CREATE TABLE project_milestones (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    stage TEXT,                  -- 所属阶段
    due_date DATE,
    completed_at TIMESTAMP,
    status TEXT DEFAULT 'pending',  -- pending | in_progress | completed | blocked
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_milestones_project ON project_milestones(project_id, status);
```

---

## 3. 项目类型定义

### 3.1 类型枚举与特征

```python
class ProjectType(str, Enum):
    CODING = "coding"        # 软件开发
    RESEARCH = "research"    # 科研课题
    BUSINESS = "business"    # 事务项目
    PERSONAL = "personal"    # 个人知识管理

class VCSMode(str, Enum):
    GIT = "git"              # Git 原生集成
    BUILTIN = "builtin"      # 内置快照（默认）
    SVN = "svn"              # SVN 集成（实验性）
```

### 3.2 类型自动检测规则

项目注册时扫描目录内容，推断类型：

```python
def detect_project_type(path: Path) -> Optional[str]:
    """根据目录内容推断项目类型"""
    
    # 强信号: .git 目录存在
    if (path / ".git").exists():
        return "coding"
    
    # 强信号: 典型编码项目文件
    code_signals = ["package.json", "pyproject.toml", "Cargo.toml", "go.mod", 
                    "requirements.txt", "Makefile", "CMakeLists.txt"]
    if any((path / f).exists() for f in code_signals):
        return "coding"
    
    # 中等信号: 学术论文特征
    research_signals = ["*.tex", "*.bib", "references/", "data/raw/"]
    # ... glob 匹配逻辑
    
    # 弱信号: Office 文档为主
    office_count = len(list(path.glob("*.docx")) + list(path.glob("*.xlsx")) + list(path.glob("*.pptx")))
    if office_count > 5:
        return "business"
    
    return None  # 无法确定，由用户选择
```

### 3.3 类型配置表

```python
PROJECT_TYPE_CONFIG = {
    "coding": {
        "default_vcs": "git",
        "available_tools": [
            "bash", "file_read", "file_write", "code_search", 
            "git_diff", "run_tests", "lint_check"
        ],
        "disabled_tools": ["ppt_generate", "word_generate"],  # 默认禁用
        "constraint_categories": ["coding_style", "security", "testing", "architecture"],
        "stage_enum": ["planning", "development", "testing", "deployment", "maintenance"],
        "wiki_templates": ["api_docs", "architecture", "changelog", "adr"],
    },
    "research": {
        "default_vcs": "builtin",
        "available_tools": [
            "file_read", "file_write", "pdf_read", "word_read", 
            "excel_read", "web_search", "academic_search"
        ],
        "constraint_categories": ["academic_writing", "data_ethics", "experiment_record"],
        "stage_enum": ["proposal", "data_collection", "analysis", "writing", "submission", "revision"],
        "wiki_templates": ["literature_review", "experiment_log", "dataset_index", "methodology"],
    },
    "business": {
        "default_vcs": "builtin",
        "available_tools": [
            "file_read", "file_write", "ppt_read", "ppt_generate",
            "word_read", "word_generate", "excel_read", "excel_generate",
            "pdf_read", "pdf_generate"
        ],
        "constraint_categories": ["document_format", "approval_flow", "confidentiality"],
        "stage_enum": ["initiation", "planning", "execution", "monitoring", "closure"],
        "wiki_templates": ["project_charter", "meeting_notes", "deliverables", "milestones"],
    },
    "personal": {
        "default_vcs": "builtin",
        "available_tools": ["*"],  # 全部可用
        "constraint_categories": ["tagging", "privacy"],
        "stage_enum": None,  # 无阶段概念
        "wiki_templates": ["inbox", "notes", "knowledge_base"],
    },
}
```

---

## 4. API 变更

### 4.1 项目注册 API

```
POST /api/v1/projects
Body: {
    "path": "/path/to/project",
    "project_type": "coding" | "research" | "business" | "personal" | null,
    // null = 使用自动检测结果
}
Response: {
    "id": "...",
    "project_type": "coding",        // 最终类型
    "detected_type": "coding",       // 自动检测结果
    "vcs_mode": "git",               // 根据类型推断的 VCS 模式
    ...
}
```

### 4.2 约束管理 API

```
# 列出项目约束
GET /api/v1/projects/{id}/constraints
Response: {
    "constraints": [
        {
            "id": "...",
            "category": "coding_style",
            "content": "使用双引号字符串",
            "trigger_pattern": "*.py",
            "priority": 5,
            "enabled": true
        }
    ]
}

# 创建约束
POST /api/v1/projects/{id}/constraints
Body: {
    "category": "coding_style",
    "content": "...",
    "trigger_pattern": "*.py",  // 可选，默认 'always'
    "priority": 5
}

# 批量导入预设模板
POST /api/v1/projects/{id}/constraints/import-template
Body: {
    "template": "python_django"  // 预定义模板名
}

# 更新/删除约束
PATCH /api/v1/projects/{id}/constraints/{cid}
DELETE /api/v1/projects/{id}/constraints/{cid}
```

### 4.3 里程碑 API

```
GET    /api/v1/projects/{id}/milestones
POST   /api/v1/projects/{id}/milestones
PATCH  /api/v1/projects/{id}/milestones/{mid}
DELETE /api/v1/projects/{id}/milestones/{mid}
POST   /api/v1/projects/{id}/milestones/{mid}/complete
```

### 4.4 类型检测 API

```
# 在不注册的情况下预览检测结果
POST /api/v1/projects/detect-type
Body: { "path": "/path/to/project" }
Response: {
    "detected_type": "coding",
    "confidence": 0.9,
    "signals": [
        {"type": ".git exists", "weight": 0.5},
        {"type": "package.json found", "weight": 0.4}
    ]
}
```

---

## 5. 约束注入机制

### 5.1 系统提示词构建流程

```
构建系统提示词时:
1. 加载 project_profile (现有逻辑)
2. 加载 project.instructions (现有逻辑，向后兼容)
3. 新增: 查询 project_constraints WHERE enabled=1
4. 按 priority DESC 排序
5. 根据当前文件路径匹配 trigger_pattern
6. 拼接到系统提示词的 [Project Constraints] 段
```

### 5.2 约束匹配逻辑

```python
def resolve_constraints(project_id: str, current_file: Optional[str] = None) -> list[Constraint]:
    """解析当前上下文应激活的约束"""
    
    constraints = db.query(
        "SELECT * FROM project_constraints WHERE project_id = ? AND enabled = 1",
        project_id
    )
    
    active = []
    for c in constraints:
        if c.trigger_pattern == "always" or c.trigger_pattern is None:
            active.append(c)
        elif current_file and fnmatch.fnmatch(current_file, c.trigger_pattern):
            active.append(c)
    
    # 按优先级排序，高优先级在前
    return sorted(active, key=lambda c: c.priority, reverse=True)
```

---

## 6. VCS 集成

### 6.1 Git 集成（只读优先）

编码项目检测到 `.git` 后，启用以下只读能力：

```python
class GitIntegration:
    """Git 只读集成，不修改仓库状态"""
    
    def get_status(self) -> GitStatus:
        """当前分支、未提交变更、ahead/behind"""
        
    def get_log(self, limit: int = 20) -> list[Commit]:
        """最近 commit 历史"""
        
    def get_diff(self, ref: str = "HEAD") -> str:
        """工作区与 HEAD 的 diff"""
        
    def get_ignored_files(self) -> list[str]:
        """读取 .gitignore，索引时排除"""
        
    def get_current_branch(self) -> str:
        """当前分支名，注入到系统提示词"""
    
    def get_file_blame(self, path: str) -> list[BlameLine]:
        """文件逐行归属（辅助理解代码）"""
```

**不实现**（避免复杂性）：
- commit / push / pull（用户自己在终端操作）
- 分支切换（同上）
- merge / rebase

### 6.2 内置快照增强

一般性项目使用增强的内置快照：

```python
class BuiltinSnapshotService:
    """基于内容哈希的文档版本管理"""
    
    def create_snapshot(self, project_id: str, file_path: str) -> Snapshot:
        """对单个文件创建快照（SHA-256 去重存储）"""
        
    def get_timeline(self, project_id: str) -> list[SnapshotEvent]:
        """项目文件变更时间线"""
        
    def diff_snapshots(self, snap_a: str, snap_b: str) -> DiffResult:
        """两个快照之间的差异（文本文件显示 diff，二进制显示元数据变化）"""
        
    def restore_snapshot(self, snap_id: str) -> None:
        """恢复到指定快照"""
```

### 6.3 SVN 集成（实验性，P3 优先级）

暂不实现。如未来有明确需求，通过插件机制扩展。

---

## 7. Wiki 差异化

### 7.1 Wiki 模板结构

项目类型决定 Wiki 的默认页面结构：

**Coding 项目 Wiki**:
```
├── API Documentation (自动从代码生成)
├── Architecture Overview (import 关系图)
├── Changelog (git log 聚合)
├── ADR (Architecture Decision Records)
└── Runbook (运维手册)
```

**Research 项目 Wiki**:
```
├── Literature Review (文献综述)
├── Experiment Log (实验记录)
├── Dataset Index (数据索引)
├── Methodology (方法论)
└── Publication Tracker (投稿追踪)
```

**Business 项目 Wiki**:
```
├── Project Charter (项目章程)
├── Meeting Notes (会议纪要)
├── Deliverables (交付物清单)
├── Milestone Timeline (里程碑时间线)
└── Risk Register (风险登记册)
```

**Personal 项目 Wiki**:
```
├── Inbox (待整理)
├── Notes (笔记)
└── Knowledge Base (知识库)
```

### 7.2 Wiki 自动内容生成

| 项目类型 | 自动化能力 |
|---------|-----------|
| coding | 从代码注释生成 API 文档；从 git log 生成 changelog |
| research | 从 PDF 高亮聚合文献综述；从对话提取实验记录 |
| business | 从对话提取会议纪要；从 Office 文档聚合交付物 |
| personal | 从对话自动归类到 inbox |

---

## 8. 前端变更

### 8.1 项目创建向导

新增项目创建对话框，包含：

1. **目录选择** + 自动类型检测
2. **类型选择**（可覆盖自动检测结果）
3. **预设模板选择**（按类型显示可用模板）
4. **确认创建**

### 8.2 项目仪表盘差异化

项目概览页根据类型渲染不同 Widget：

| 类型 | Widget 组合 |
|------|------------|
| coding | GitStatusWidget + TestCoverageWidget + RecentCommitsWidget + FileTreeWidget |
| research | LiteratureWidget + ExperimentProgressWidget + WritingProgressWidget |
| business | DocumentListWidget + MilestoneTimelineWidget + TaskBoardWidget |
| personal | InboxWidget + RecentNotesWidget + TagCloudWidget |

### 8.3 约束管理界面

设置页新增"项目约束"Tab：

- 约束列表（按类别分组）
- 添加/编辑约束（类别、内容、触发模式、优先级）
- 导入预设模板
- 启用/禁用开关

---

## 9. 实施步骤

### Phase 1: 数据模型 + 基础 API (1-2 周) ✅ 已完成

- [x] 9.1.1 `projects` 表新增 `project_type` / `project_stage` / `vcs_mode` / `detected_type` 字段
- [x] 9.1.2 创建 `project_constraints` 表 + Repository
- [x] 9.1.3 创建 `project_milestones` 表 + Repository
- [x] 9.1.4 实现类型自动检测逻辑 (`detect_project_type()`)
- [x] 9.1.5 更新项目注册 API 支持 `project_type` 参数
- [x] 9.1.6 添加约束 CRUD API
- [x] 9.1.7 添加里程碑 CRUD API
- [x] 9.1.8 编写单元测试

### Phase 2: 约束注入 + 系统集成 (1 周) ✅ 已完成

- [x] 9.2.1 修改系统提示词构建逻辑，注入约束
- [x] 9.2.2 实现 `resolve_constraints()` 匹配逻辑
- [x] 9.2.3 预设约束模板数据（coding/research/business 各 3-5 个）
- [x] 9.2.4 约束导入模板 API
- [x] 9.2.5 集成测试

### Phase 3: Git 只读集成 (1 周) ✅ 已完成

- [x] 9.3.1 实现 `GitIntegration` 类（status/log/diff/ignore/branch）
- [x] 9.3.2 项目打开时自动检测 git 状态
- [x] 9.3.3 当前分支注入到系统提示词
- [x] 9.3.4 Git status widget 后端 API
- [x] 9.3.5 索引时排除 .gitignore 中的文件
- [x] 9.3.6 集成测试

### Phase 4: 前端项目类型 UI (1-2 周)

- [ ] 9.4.1 项目创建向导组件
- [ ] 9.4.2 类型自动检测预览组件
- [ ] 9.4.3 项目概览页差异化 Widget
- [ ] 9.4.4 约束管理界面
- [ ] 9.4.5 里程碑管理界面
- [ ] 9.4.6 前端测试

### Phase 5: Wiki 差异化 (1 周)

- [ ] 9.5.1 Wiki 模板按类型初始化
- [ ] 9.5.2 Coding 项目自动生成 API 文档骨架
- [ ] 9.5.3 Research 项目文献综述聚合
- [ ] 9.5.4 Business 项目会议纪要提取
- [ ] 9.5.5 集成测试

---

## 10. 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 现有项目类型迁移 | 低（`project_type=NULL` 保持兼容） | 提供批量设置脚本 |
| 约束系统复杂度 | 中（用户可能困惑） | 提供预设模板，降低手动配置成本 |
| Git 集成稳定性 | 低（只读操作） | 异常捕获，降级为无 git 模式 |
| 前端 Widget 膨胀 | 中（包体积增大） | 按需加载，按类型条件渲染 |
| 数据库迁移失败 | 低（ALTER TABLE 幂等） | 迁移脚本加事务保护 |

---

## 11. 不在范围内

- ❌ SVN 集成（P3，暂不实现）
- ❌ Git 写操作（commit/push/pull）
- ❌ 多人协作权限管理
- ❌ 项目间依赖关系
- ❌ 云端同步

---

## 12. 参考

- 项目现有 Office 功能设计: `docs/plans/2026-07-16_office-features.md`
- Cursor Rules 设计: https://kirill-markin.com/articles/cursor-ide-rules-for-ai/
- Claude Code CLAUDE.md 设计: 项目内 `.claude/CLAUDE.md`
- Git vs SVN 对比: https://hackmamba.io/engineering/git-vs-svn/
