# 项目级文件访问控制（Allowed Paths）

## 背景与目标

### 问题

当前 sage 项目的文件访问受限于 workspace 绑定：
- @菜单文件搜索（`AtFileMenu`）只显示 workspace 内的文件
- `sage-file://` 协议只允许访问已注册的 workspace 根目录
- 后端 `read_file` 工具虽然不做 workspace 边界检查，但前端 UI 无法浏览工作区外的文件

用户场景：
1. **临时访问**：偶尔需要查看桌面/下载目录的文件（大部分场景）
2. **长期访问**：某个项目经常需要访问固定目录（如共享文档目录）

### 目标

1. 复用现有项目模型，扩展 `allowed_paths` 字段存储路径规则
2. 支持通配符路径规则（`~/Documents/**`、`/tmp/scratch/*` 等）
3. 首次访问未授权路径时弹窗审批，支持"项目级允许"持久化
4. 项目详情面板管理 `allowed_paths` 规则
5. 读写分离：读取遵守 allowed_paths，写入仍限于 workspace 内

## 涉及的文件与模块

### 后端（Python）

| 文件 | 改动 |
|------|------|
| `backend/data/database.py` | projects 表添加 `allowed_paths` 列 |
| `backend/data/project_repo.py` | Project 模型扩展 `allowed_paths` 字段 |
| `backend/api/project_routes.py` | 项目 CRUD 接口增加 `allowed_paths` |
| `backend/office/path_safety.py` | 新增路径规则匹配引擎 |
| `backend/tools/file_tool.py` | `read_file`/`list_dir` 遵守 allowed_paths |
| `backend/api/workspace_routes.py` | `/workspace/files` 搜索包含 allowed_paths 目录 |
| `backend/tools/permissions.py` | 权限检查支持 allowed_paths 规则 |

### 前端（TypeScript/React）

| 文件 | 改动 |
|------|------|
| `src/shared/api/projectApi.ts` | 项目接口类型扩展 |
| `src/features/project/ProjectDetail.tsx` | 项目详情面板（新增 allowed_paths 管理） |
| `src/widgets/permission/ApprovalDialog.tsx` | 审批弹窗增加"项目级允许"选项 |
| `src/shared/api/fileSearchClient.ts` | 文件搜索支持 allowed_paths 目录 |
| `electron/sageFileUrl.ts` | 协议层放行 allowed_paths 内路径 |
| `electron/commands.ts` | 新增 allowed_paths 管理命令 |

## 技术方案

### 1. 数据模型扩展

**数据库 Schema**：
```sql
ALTER TABLE projects ADD COLUMN allowed_paths TEXT DEFAULT '[]'
-- JSON 数组，存储路径规则字符串
```

**Project 模型**：
```python
@dataclass
class Project:
    id: str
    path: str
    name: str
    created_at: int
    last_opened_at: int
    allowed_paths: List[str] = field(default_factory=list)
    # 新增字段，默认空列表
```

### 2. 路径规则语法

采用类 `.gitignore` 语法（使用 `pathlib.PurePath.match`）：

| 规则 | 含义 |
|------|------|
| `~/Documents/**` | 用户 Documents 目录及其所有子目录 |
| `~/Desktop/*.pdf` | 用户桌面所有 PDF 文件 |
| `/tmp/scratch/*` | /tmp/scratch 直接子文件（不含子目录） |
| `~/projects/sage-shared` | 精确匹配（目录或文件） |

**路径展开**：
- `~` → `Path.home()`
- 相对路径 → 相对于项目根目录

### 3. 路径匹配引擎

新增 `backend/office/allowed_paths.py`：

```python
def is_allowed(candidate: str, allowed_paths: List[str]) -> bool:
    """检查 candidate 路径是否匹配任一 allowed_paths 规则。"""
    candidate_path = Path(candidate).resolve()
    
    for rule in allowed_paths:
        rule_path = _expand_rule(rule)
        
        # 精确匹配或前缀匹配（目录包含）
        if rule_path.is_dir():
            try:
                candidate_path.relative_to(rule_path)
                return True
            except ValueError:
                continue
        
        # 通配符匹配
        if PurePath(candidate_path).match(rule_path):
            return True
    
    return False

def _expand_rule(rule: str) -> Path:
    """展开路径规则：~ → home，相对路径 → 项目根。"""
    expanded = Path(rule).expanduser()
    return expanded.resolve()
```

### 4. 文件访问检查流程

```
Agent 请求读取 /home/fz/Desktop/报告.txt
    ↓
检查是否在当前 workspace 内？
    → 是 → 允许
    → 否 ↓
获取当前项目的 allowed_paths
    ↓
路径匹配 allowed_paths 规则？
    → 是 → 允许
    → 否 ↓
触发权限审批弹窗
    ↓
用户选择：
    - 拒绝 → 拒绝
    - 允许一次 → 仅本次允许
    - 本会话允许 → 会话级临时授权
    - 项目级允许 → 添加到 allowed_paths，持久化
```

### 5. 前端 UI 集成

**项目详情面板**（新增）：
```
┌─ 项目设置：sage ─────────────────────────┐
│                                          │
│ 项目路径: /home/fz/project/sage          │
│                                          │
│ 额外访问路径                              │
│ ┌──────────────────────────────────────┐ │
│ │ ✓ ~/Documents/**          [删除]     │ │
│ │ ✓ ~/Desktop/**            [删除]     │ │
│ │ + [添加路径...]                      │ │
│ └──────────────────────────────────────┘ │
│                                          │
│ [保存]                                   │
└──────────────────────────────────────────┘
```

**审批弹窗**（扩展）：
```
┌─────────────────────────────────────────┐
│ 🔐 访问授权请求                          │
│                                          │
│ Agent 想访问: /home/fz/Desktop/报告.txt │
│ 所在目录: /home/fz/Desktop               │
│                                          │
│ [拒绝]  [允许一次]  [本会话] [项目级✓]  │
└─────────────────────────────────────────┘
```

### 6. sage-file:// 协议扩展

当前协议只允许访问已注册的 workspace 根目录。扩展为：
- 检查路径是否在任一项目的 allowed_paths 内
- 匹配 → 放行
- 不匹配 → 拒绝（fail-closed）

## 实施步骤

### Phase 1：数据模型与后端基础（预计 2 小时）

- [x] 1.1 数据库迁移：projects 表添加 `allowed_paths` 列
- [x] 1.2 Project 模型扩展 `allowed_paths` 字段
- [x] 1.3 ProjectRepository CRUD 支持 `allowed_paths`
- [x] 1.4 路径规则匹配引擎实现
- [x] 1.5 单元测试：路径匹配引擎

### Phase 2：后端集成（预计 2 小时）

- [x] 2.1 `file_tool.py` 读取检查支持 allowed_paths
- [x] 2.2 `workspace_routes.py` 搜索包含 allowed_paths 目录
- [x] 2.3 项目 API 增加 `allowed_paths` 字段
- [x] 2.4 单元测试：集成路径

### Phase 3：前端集成（预计 2 小时）

- [x] 3.1 项目 API 类型扩展
- [x] 3.2 项目详情面板 UI（allowed_paths 管理）
- [ ] 3.3 审批弹窗扩展（"项目级允许"选项）— 后续 PR
- [ ] 3.4 文件搜索客户端支持 allowed_paths — 后续 PR

### Phase 4：Electron 协议层（预计 1 小时）

- [x] 4.1 sage-file:// 协议放行 allowed_paths
- [x] 4.2 IPC 命令扩展
- [x] 4.3 单元测试（集成测试随后续 PR 补充）

### Phase 5：文档与清理（预计 0.5 小时）

- [ ] 5.1 用户手册更新 — 后续 PR
- [ ] 5.2 技术文档归档 — 后续 PR
- [ ] 5.3 CHANGELOG 更新 — PR merge 时统一处理

## 风险评估与依赖

### 风险

1. **路径遍历攻击**：必须确保路径匹配引擎正确处理 `..` 和符号链接
   - 缓解：使用 `Path.resolve()` 归一化路径
2. **性能影响**：每次文件访问都要检查 allowed_paths
   - 缓解：规则数量通常 < 20，匹配复杂度 O(n)
3. **用户困惑**：allowed_paths 与 workspace 的关系不清晰
   - 缓解：UI 文案明确区分（"workspace 内可读写，allowed_paths 仅只读"）

### 依赖

- 无外部依赖
- 复用现有项目模型和权限系统

## 成功标准

1. 用户可以配置项目级 allowed_paths
2. Agent 可以读取 allowed_paths 内的文件
3. 首次访问未授权路径时弹窗审批
4. 用户可以选择"项目级允许"持久化规则
5. 所有现有测试通过，新增测试覆盖率 > 80%
