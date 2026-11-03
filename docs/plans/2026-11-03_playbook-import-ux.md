# Playbook 规范导入体验优化

> 日期：2026-11-03
> 分支：feat/playbook-import-ux
> 状态：已实施（M1–M4）

---

## 一、背景与目标

### 1.1 问题陈述

Sage 项目管理系统在功能层面已领先主流工具（Cursor、Claude Code、Copilot），但在用户体验包装上存在明显短板：

1. **术语泄露**：`ProjectAdvisorCard.tsx` 中"沉淀至 L3"、"存为 L4 资料"等内部层级代号直接暴露给用户，普通用户无法理解
2. **规范导入断链**：用户手中已有大量 Word/PDF 格式的规范文件（申报指南、质量管理体系文档等），当前只能导入 JSON 格式 Playbook，无法从现有文档一键生成
3. **跨工具分享缺失**：规程导出后只能通过文件传输，没有公开链接方便团队协作

### 1.2 目标

| 优先级 | 目标 | 预期效果 |
|--------|------|---------|
| **P0** | 术语去技术化 | 消除 L1/L2/L3/L4 对用户的暴露，统一"约束"→"规则" |
| **P1** | Word/PDF → Playbook 一键导入 | 上传规范文档 → AI 解析 → 生成 Playbook 预览 → 确认后落库 |
| **P2** | 规程分享链接 | 生成带 token 的分享 URL，接收方点击即可导入 |

---

## 二、技术方案

### 2.1 P0：术语去技术化

**涉及文件**：
- `src/features/project-type/ProjectAdvisorCard.tsx`
- `src/features/project-type/ProjectExpandedPanels.tsx`（已做友好化，作为参考）

**改动清单**：

| 当前文案 | 改为 | 说明 |
|---------|------|------|
| "沉淀至 L3" | "保存到 AI 记忆" | L3 是内部概念 |
| "已沉淀 L3" | "已保存" | 同上 |
| "存为 L4 资料" | "保存为项目资料" | L4 是内部概念 |
| "已存 L4" | "已保存" | 同上 |
| "固化为约束" | "保存为规则" | "约束"偏技术 |

**变量名清理**（用户不可见，但降低维护心智负担）：
- `SIDEBAR_L2_PRESETS` → `SIDEBAR_PRESETS`
- `savedOverviewL3` → `savedOverviewProfile`
- `handleSaveOverviewToL3` → `handleSaveOverviewToProfile`

### 2.2 P1：Word/PDF → Playbook 一键导入

**架构设计**：

```
用户上传 .docx/.pdf/.md
    ↓
POST /playbooks/import/document
    ↓
后端：
  1. parse_document() 提取纯文本（已有）
  2. LLM 分析文本 → 生成 Playbook 草案
     - 识别阶段数量与名称
     - 提取每阶段产物清单
     - 提取退出条件/完成标准
     - 提取通用规则
  3. 生成 Playbook JSON 预览（不写库）
    ↓
返回 preview（含 stages[]、rules[]、metadata）
    ↓
前端：展示预览 + 用户编辑/确认
    ↓
POST /playbooks/import/confirm
    ↓
后端：写入 project_playbooks + playbook_library
```

**关键接口**：

```python
# backend/api/playbook_routes.py

@router.post("/playbooks/import/document")
async def import_playbook_from_document(
    file: UploadFile,
    project_id: str | None = None,  # 可选：绑定到项目
):
    """从 Word/PDF/Markdown 文档生成 Playbook 预览"""
    # 1. 解析文档
    text = parse_document(file.file)
    
    # 2. LLM 分析
    playbook_draft = await llm_generate_playbook(text, filename=file.filename)
    
    # 3. 返回预览（不写库）
    return {"preview": playbook_draft, "source_doc": file.filename}

@router.post("/playbooks/import/confirm")
async def confirm_playbook_import(
    payload: PlaybookConfirmImportRequest,
):
    """用户确认后落库"""
    # 写入 project_playbooks 或 playbook_library
```

**LLM Prompt 设计**：

```
你是一个项目管理规范分析师。用户将提供一份规范文档，请从中提取：

1. **阶段**（stages）：识别项目生命周期的各个阶段
   - 每个阶段需要：id（英文 kebab-case）、label（中文名称）、order（顺序号）
   - 每个阶段的目标（objective，一句话）

2. **产物**（artifacts）：每个阶段需要产出的文件/文档
   - 每个产物需要：id、label、globs（文件匹配模式）
   - 标记是否必需（required: true/false）

3. **完成标准**（exit_criteria）：每个阶段的退出条件
   - 关联到具体产物，或描述为可检查的条件

4. **通用规则**（global_rules）：适用于整个项目的规则
   - 每条规则需要：id、label、content（具体内容）

请只输出 JSON，格式如下：
{
  "name": "规程名称",
  "stages": [...],
  "global_rules": [...]
}

文档内容：
{text}
```

**降级策略**：LLM 不可用时，使用 `playbook_author.py:build_author_preview()` 的确定性模板，基于文档关键字匹配生成基础结构。

**前端交互**：

在 `PlaybookToolbar.tsx` 的 Import 按钮旁增加"从文档导入"按钮：
- 点击后弹出文件选择器（接受 .docx/.pdf/.md）
- 上传后展示加载动画
- 预览页展示：阶段列表、产物清单、规则列表（可编辑）
- 确认后写入数据库

### 2.3 P2：规程分享链接

**架构设计**：

```
用户点击"生成分享链接"
    ↓
POST /playbooks/library/{id}/share
    ↓
后端：
  1. 生成随机 token（secrets.token_urlsafe(16)）
  2. 写入 playbook_shares 表（token, playbook_id, expires_at）
  3. 返回分享 URL：https://sage.local/share/playbook/{token}
    ↓
前端：复制链接到剪贴板 + 显示有效期
    ↓
接收方访问 URL
    ↓
GET /playbooks/shared/{token}
    ↓
后端：验证 token → 返回 playbook spec → 接收方一键导入
```

**新增数据表**：

```sql
CREATE TABLE IF NOT EXISTS playbook_shares (
    id TEXT PRIMARY KEY,
    playbook_id TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    created_by TEXT,
    expires_at INTEGER NOT NULL,  -- Unix timestamp
    created_at INTEGER NOT NULL,
    FOREIGN KEY (playbook_id) REFERENCES playbook_library(id) ON DELETE CASCADE
);
```

**有效期**：默认 7 天，可配置。

---

## 三、涉及文件清单

### 3.1 新增文件

| 文件 | 说明 |
|------|------|
| `backend/services/playbook_document_import.py` | Word/PDF → Playbook 解析服务 |
| `backend/services/playbook_share.py` | 分享链接生成与验证服务 |
| `backend/data/playbook_share_repo.py` | 分享记录 CRUD |
| `src/features/playbook/PlaybookDocumentImportDialog.tsx` | 文档导入对话框 |
| `src/features/playbook/PlaybookPreviewEditor.tsx` | Playbook 预览编辑器 |
| `src/features/playbook/PlaybookShareDialog.tsx` | 分享链接对话框 |
| `docs/technical/XX-playbook-import-share.md` | 技术文档（归档用） |

### 3.2 修改文件

| 文件 | 改动 |
|------|------|
| `src/features/project-type/ProjectAdvisorCard.tsx` | 术语去技术化 |
| `src/features/playbook/PlaybookToolbar.tsx` | 增加"从文档导入"和"分享"按钮 |
| `backend/api/playbook_routes.py` | 新增 3 个 API endpoint |
| `backend/data/database.py` | 新增 `playbook_shares` 表 |
| `backend/services/playbook_library.py` | 增加文档解析入口 |

### 3.3 测试文件

| 文件 | 说明 |
|------|------|
| `backend/tests/test_playbook_document_import.py` | 文档导入单元测试 |
| `backend/tests/test_playbook_share.py` | 分享链接单元测试 |
| `src/features/playbook/__tests__/PlaybookDocumentImportDialog.test.tsx` | 前端组件测试 |

---

## 四、实施步骤

### 里程碑 M1：术语去技术化（P0，0.5 天）

- [x] 修改 `ProjectAdvisorCard.tsx` 中的 5 处文案
- [x] 批量替换 14 个 .tsx 文件中的 L3/L4/约束 术语
- [x] 更新测试文件断言
- [x] 验证前端 TypeScript 类型检查通过
- [x] 验证 ConstraintSummaryWidget 11 个测试全部通过

### 里程碑 M2：Word/PDF → Playbook 导入（P1，2-3 天）

- [x] 实现 `playbook_document_import.py`：文档解析 + LLM 生成 Playbook 草案
- [x] 实现降级策略（LLM 不可用时的确定性模板，支持中文数字序号）
- [x] 新增 API endpoint：`POST /playbooks/import/document`
- [x] 新增 Electron IPC 命令路由 `playbook_import_document`
- [x] 新增 TypeScript API 方法 `playbookApi.documentImport()`
- [x] 编写后端单元测试（20 个，全通过）
- [x] 实现前端 `PlaybookDocumentImportDialog.tsx`：文件选择 + 预览
- [x] 实现前端 `PlaybookPreviewEditor.tsx`：阶段/产物/规则编辑（合并到 Dialog 内预览）
- [x] 修改 `PlaybookToolbar.tsx` 增加入口

### 里程碑 M3：规程分享链接（P2，1-2 天）

- [x] 新增 `playbook_shares` 数据表
- [x] 实现 `playbook_share_repo.py` + `playbook_share.py`
- [x] 新增 API endpoint：`POST /playbooks/library/{id}/share` + `GET /playbooks/shared/{token}`
- [x] 实现前端 `PlaybookShareDialog.tsx`：生成链接 + 复制
- [x] 实现分享页面：访问 URL → 预览 → 一键导入
- [x] 编写单元测试

### 里程碑 M4：集成测试与文档（0.5 天）

- [x] 端到端测试：上传 Word → 预览 → 确认 → 绑定项目（`backend/tests/integration/test_playbook_import_share.py` TestDocumentImportFlow）
- [x] 端到端测试：生成分享链接 → 访问 → 导入（`TestShareLinkFlow` 含 5 个用例，覆盖无效/过期/库缺失）
- [x] 归档技术文档到 `docs/technical/126-playbook-import-share.md`
- [x] 更新用户手册（如需要）—— 本轮以技术手册为主，用户手册待后续按需追加

---

## 五、风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| LLM 解析规范文档质量不稳定 | 生成的 Playbook 结构不准确 | 提供预览编辑环节，用户可手动调整；降级策略保证无 LLM 也能用 |
| Word/PDF 解析失败（加密/扫描版） | 用户无法导入 | 明确提示文件格式要求；建议用户转为纯文本后重试 |
| 分享链接泄露 | 内部规范外泄 | 默认 7 天有效期；记录分享日志；敏感项目禁用分享功能 |
| 术语改动破坏现有测试 | CI 失败 | 修改后全量跑前端测试，修复断言 |

---

## 六、验收标准

1. **术语友好化**：用户界面中不再出现 L1/L2/L3/L4 字样，"约束"统一改为"规则"
2. **文档导入**：上传一份 Word 规范文件（如《XX 项目申报指南》），能生成包含 3-5 个阶段的 Playbook 预览，用户编辑后成功落库
3. **分享链接**：生成分享链接后，在另一台机器访问该链接，能预览 Playbook 内容并一键导入
4. **测试覆盖**：新增代码测试覆盖率 ≥ 80%
5. **回归测试**：现有 Playbook 导入导出功能不受影响

---

## 七、参考资料

- 主流 AI 应用对比：Cursor `.cursorrules`、Claude Code `CLAUDE.md`、GitHub Copilot `.github/copilot-instructions.md`
- Sage 现有 Playbook 系统：`backend/services/playbook_*.py` + `backend/api/playbook_routes.py`
- 文档解析能力：`backend/wiki/file_parser.py:parse_document()`
- Word 规则抽取：`backend/tools/office_word_intelligence_tools.py:OfficeExtractRulesTool`
