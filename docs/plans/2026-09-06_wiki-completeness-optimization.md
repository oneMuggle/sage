# LLM Wiki 完整性优化方案

> **创建日期**: 2026-09-06  
> **分支**: `feat/wiki-completeness-optimization`  
> **状态**: ✅ 全部交付（Phase 1-5 完成）

---

## 1. 背景与目标

### 1.1 背景

Sage 项目的 Wiki 子系统参考了 `/home/fz/project/llm_wiki`（Andrej Karpathy 的 LLM Wiki 设计模式实现）。经过详细对比分析，发现：

- ✅ **核心功能已完整实现**（90%）：6步 CoT 摄入、混合搜索、知识图谱、RAG 聊天、Deep Research、MCP Server
- ⚠️ **高级功能部分缺失**（50%）：持久化队列、Chrome 扩展、Lint 系统、审核系统
- ❌ **独特功能未实现**（20%）：Rust Agent 运行时（架构差异，不需要实现）

### 1.2 目标

补齐核心缺失功能，使 sage 的 Wiki 系统达到参考实现 95%+ 的功能完整度：

1. **持久化摄入队列** — 支持崩溃恢复和取消/重试
2. **Chrome Web Clipper** — 一键抓取网页到知识库
3. **Lint 系统** — 自动检测 Wiki 质量问题
4. **审核系统** — LLM 标记需要人工审查的内容

### 1.3 不在范围内

- ❌ Rust Agent 运行时（sage 有自己的 orchestration 架构）
- ❌ Obsidian 自动同步（手动打开已支持）
- ❌ 额外 LLM Provider（通过 HttpxLLMAdapter 已支持）

---

## 2. 涉及的文件与模块

### 2.1 后端新增文件

```
backend/wiki/
├── ingest_queue.py          # [新增] 持久化摄入队列
├── lint.py                  # [新增] Wiki 质量检查
├── review.py                # [新增] 审核系统

backend/api/
└── wiki_routes.py           # [修改] 添加 queue/lint/review 端点
```

### 2.2 前端新增文件

```
src/shared/api-client/
└── wiki.ts                  # [修改] 添加 queue/lint/review API 客户端

src/entities/wiki/
├── queue-store.ts           # [新增] 队列状态管理
├── lint-store.ts            # [修改] 已有，需补充 API 调用
└── review-store.ts          # [修改] 已有，需补充 API 调用

src/widgets/wiki/
├── WikiQueuePanel.tsx       # [新增] 队列管理面板
└── WikiLintView.tsx         # [新增] Lint 结果视图

src/pages/
└── Knowledge.tsx            # [修改] 集成新视图
```

### 2.3 Chrome 扩展

```
extension/
├── manifest.json            # [新增] Manifest V3 配置
├── background.js            # [新增] Service Worker
├── popup.html               # [新增] 弹出窗口
├── popup.js                 # [新增] 弹出窗口逻辑
├── content.js               # [新增] 内容提取脚本
├── lib/
│   ├── Readability.js       # [新增] 网页正文提取
│   └── Turndown.js          # [新增] HTML→Markdown 转换
└── icons/
    ├── icon16.png           # [新增]
    ├── icon48.png           # [新增]
    └── icon128.png          # [新增]
```

### 2.4 测试文件

```
backend/tests/unit/wiki/
├── test_ingest_queue.py     # [新增]
├── test_lint.py             # [新增]
└── test_review.py           # [新增]

backend/tests/integration/
├── test_wiki_queue_routes.py    # [新增]
├── test_wiki_lint_routes.py     # [新增]
└── test_wiki_review_routes.py   # [新增]

tests/e2e/
└── wiki-chrome-extension.spec.ts  # [新增] Chrome 扩展 E2E
```

### 2.5 文档

```
docs/technical/
└── 48-wiki-completeness-optimization.md  # [新增] 技术文档

docs/user-manual/
└── 04-wiki-chrome-extension.md           # [新增] 用户手册
```

---

## 3. 技术方案

### 3.1 持久化摄入队列

#### 3.1.1 数据模型

```python
# backend/wiki/ingest_queue.py
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, List
import json
import uuid
from datetime import datetime

class QueueStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass
class IngestTask:
    task_id: str
    source_path: str
    project_root: str
    status: QueueStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    result: Optional[dict] = None

class IngestQueue:
    """持久化摄入队列（JSON 文件存储）"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.queue_file = project_root / ".llm-wiki" / "ingest-queue.json"
        self._tasks: dict[str, IngestTask] = {}
        self._load()
    
    def _load(self):
        """从文件加载队列"""
        if self.queue_file.exists():
            data = json.loads(self.queue_file.read_text())
            self._tasks = {t["task_id"]: IngestTask(**t) for t in data["tasks"]}
    
    def _save(self):
        """持久化队列到文件"""
        self.queue_file.parent.mkdir(parents=True, exist_ok=True)
        data = {"tasks": [vars(t) for t in self._tasks.values()]}
        self.queue_file.write_text(json.dumps(data, indent=2, default=str))
    
    def add(self, source_path: str) -> str:
        """添加入任务，返回 task_id"""
        task_id = str(uuid.uuid4())[:8]
        task = IngestTask(
            task_id=task_id,
            source_path=source_path,
            project_root=str(self.project_root),
            status=QueueStatus.PENDING,
            created_at=datetime.now()
        )
        self._tasks[task_id] = task
        self._save()
        return task_id
    
    def get_next_pending(self) -> Optional[IngestTask]:
        """获取下一个待处理任务"""
        for task in self._tasks.values():
            if task.status == QueueStatus.PENDING:
                return task
        return None
    
    def mark_processing(self, task_id: str):
        """标记为处理中"""
        task = self._tasks[task_id]
        task.status = QueueStatus.PROCESSING
        task.started_at = datetime.now()
        self._save()
    
    def mark_completed(self, task_id: str, result: dict):
        """标记为完成"""
        task = self._tasks[task_id]
        task.status = QueueStatus.COMPLETED
        task.completed_at = datetime.now()
        task.result = result
        self._save()
    
    def mark_failed(self, task_id: str, error: str):
        """标记为失败"""
        task = self._tasks[task_id]
        task.status = QueueStatus.FAILED
        task.error_message = error
        task.retry_count += 1
        self._save()
    
    def cancel(self, task_id: str) -> bool:
        """取消任务"""
        task = self._tasks.get(task_id)
        if task and task.status in (QueueStatus.PENDING, QueueStatus.FAILED):
            task.status = QueueStatus.CANCELLED
            self._save()
            return True
        return False
    
    def retry(self, task_id: str) -> bool:
        """重试失败任务"""
        task = self._tasks.get(task_id)
        if task and task.status == QueueStatus.FAILED and task.retry_count < task.max_retries:
            task.status = QueueStatus.PENDING
            task.error_message = None
            self._save()
            return True
        return False
    
    def get_all(self) -> List[IngestTask]:
        """获取所有任务"""
        return list(self._tasks.values())
    
    def get_status_summary(self) -> dict:
        """获取状态摘要"""
        summary = {status.value: 0 for status in QueueStatus}
        for task in self._tasks.values():
            summary[task.status.value] += 1
        return summary
```

#### 3.1.2 API 端点

```python
# backend/api/wiki_routes.py 新增端点

@router.post("/ingest/queue/add")
async def queue_add(req: QueueAddRequest):
    """添加入任务到队列"""
    queue = IngestQueue(Path(req.project_path))
    task_id = queue.add(req.source_path)
    return {"task_id": task_id, "status": "pending"}

@router.get("/ingest/queue/status")
async def queue_status(project_path: str):
    """获取队列状态"""
    queue = IngestQueue(Path(project_path))
    return queue.get_status_summary()

@router.get("/ingest/queue/tasks")
async def queue_tasks(project_path: str):
    """获取所有任务"""
    queue = IngestQueue(Path(project_path))
    return {"tasks": [vars(t) for t in queue.get_all()]}

@router.post("/ingest/queue/cancel/{task_id}")
async def queue_cancel(task_id: str, project_path: str):
    """取消任务"""
    queue = IngestQueue(Path(project_path))
    success = queue.cancel(task_id)
    return {"success": success}

@router.post("/ingest/queue/retry/{task_id}")
async def queue_retry(task_id: str, project_path: str):
    """重试任务"""
    queue = IngestQueue(Path(project_path))
    success = queue.retry(task_id)
    return {"success": success}

@router.post("/ingest/queue/process")
async def queue_process(project_path: str):
    """处理下一个待处理任务（由前端轮询或后端调度器调用）"""
    queue = IngestQueue(Path(project_path))
    task = queue.get_next_pending()
    if not task:
        return {"processed": False, "message": "No pending tasks"}
    
    queue.mark_processing(task.task_id)
    try:
        # 调用现有的 ingest_source
        result = await ingest_source(...)
        queue.mark_completed(task.task_id, result)
        return {"processed": True, "task_id": task.task_id, "result": result}
    except Exception as e:
        queue.mark_failed(task.task_id, str(e))
        return {"processed": False, "error": str(e)}
```

### 3.2 Chrome Web Clipper

#### 3.2.1 扩展结构

```json
// extension/manifest.json
{
  "manifest_version": 3,
  "name": "Sage Web Clipper",
  "version": "1.0.0",
  "description": "一键抓取网页到 Sage 知识库",
  "permissions": ["activeTab", "storage"],
  "host_permissions": ["http://127.0.0.1:8765/*"],
  "background": {
    "service_worker": "background.js"
  },
  "action": {
    "default_popup": "popup.html",
    "default_icon": {
      "16": "icons/icon16.png",
      "48": "icons/icon48.png",
      "128": "icons/icon128.png"
    }
  },
  "icons": {
    "16": "icons/icon16.png",
    "48": "icons/icon48.png",
    "128": "icons/icon128.png"
  }
}
```

#### 3.2.2 核心逻辑

```javascript
// extension/content.js
// 使用 Readability.js 提取正文，Turndown.js 转换为 Markdown

async function extractContent() {
  // 克隆 document
  const documentClone = document.cloneNode(true);
  
  // 使用 Readability 提取正文
  const reader = new Readability(documentClone);
  const article = reader.parse();
  
  // 使用 Turndown 转换为 Markdown
  const turndownService = new TurndownService();
  const markdown = turndownService.turndown(article.content);
  
  return {
    title: article.title,
    url: window.location.href,
    content: markdown,
    extracted_at: new Date().toISOString()
  };
}

// extension/popup.js
document.getElementById('clip-btn').addEventListener('click', async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  
  // 在 content script 中提取内容
  const [result] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    function: extractContent
  });
  
  // 发送到 Sage 后端
  const response = await fetch('http://127.0.0.1:8765/api/v1/wiki/clip', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      project_path: await getSelectedProject(),
      url: result.result.url,
      title: result.result.title,
      content: result.result.content
    })
  });
  
  if (response.ok) {
    showSuccess('已保存到知识库');
  } else {
    showError('保存失败');
  }
});
```

### 3.3 Lint 系统

#### 3.3.1 检查规则

```python
# backend/wiki/lint.py
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional
import re

class LintSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

@dataclass
class LintIssue:
    file_path: str
    line: Optional[int]
    severity: LintSeverity
    rule: str
    message: str
    suggestion: Optional[str] = None

class WikiLint:
    """Wiki 质量检查器"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.wiki_dir = project_root / "wiki"
    
    def check_all(self) -> List[LintIssue]:
        """运行所有检查"""
        issues = []
        issues.extend(self.check_structure())
        issues.extend(self.check_wikilinks())
        issues.extend(self.check_frontmatter())
        return issues
    
    def check_structure(self) -> List[LintIssue]:
        """检查目录结构规范"""
        issues = []
        
        # 检查必需目录
        required_dirs = ["wiki/entities", "wiki/concepts", "wiki/sources"]
        for dir_path in required_dirs:
            if not (self.project_root / dir_path).exists():
                issues.append(LintIssue(
                    file_path=dir_path,
                    line=None,
                    severity=LintSeverity.ERROR,
                    rule="structure.required_dir",
                    message=f"必需目录缺失: {dir_path}",
                    suggestion=f"创建目录: mkdir -p {dir_path}"
                ))
        
        # 检查必需文件
        required_files = ["wiki/index.md", "wiki/overview.md", "wiki/schema.md"]
        for file_path in required_files:
            if not (self.project_root / file_path).exists():
                issues.append(LintIssue(
                    file_path=file_path,
                    line=None,
                    severity=LintSeverity.ERROR,
                    rule="structure.required_file",
                    message=f"必需文件缺失: {file_path}",
                    suggestion=f"创建文件: touch {file_path}"
                ))
        
        return issues
    
    def check_wikilinks(self) -> List[LintIssue]:
        """检查 wikilink 断链"""
        issues = []
        
        # 收集所有 wiki 页面
        wiki_pages = set()
        for md_file in self.wiki_dir.rglob("*.md"):
            rel_path = md_file.relative_to(self.project_root)
            wiki_pages.add(str(rel_path))
        
        # 检查每个文件中的 wikilink
        wikilink_pattern = re.compile(r'\[\[([^\]]+)\]\]')
        for md_file in self.wiki_dir.rglob("*.md"):
            content = md_file.read_text()
            for line_num, line in enumerate(content.split('\n'), 1):
                for match in wikilink_pattern.finditer(line):
                    link_target = match.group(1)
                    # 尝试解析链接目标
                    resolved = self._resolve_wikilink(md_file, link_target)
                    if resolved and str(resolved) not in wiki_pages:
                        issues.append(LintIssue(
                            file_path=str(md_file.relative_to(self.project_root)),
                            line=line_num,
                            severity=LintSeverity.WARNING,
                            rule="wikilink.broken",
                            message=f"断链: [[{link_target}]]",
                            suggestion=f"创建页面: {link_target}.md"
                        ))
        
        return issues
    
    def check_frontmatter(self) -> List[LintIssue]:
        """检查 frontmatter 必填字段"""
        issues = []
        
        # 必填字段
        required_fields = ["title", "created", "updated"]
        
        for md_file in self.wiki_dir.rglob("*.md"):
            content = md_file.read_text()
            
            # 提取 frontmatter
            if not content.startswith('---'):
                issues.append(LintIssue(
                    file_path=str(md_file.relative_to(self.project_root)),
                    line=1,
                    severity=LintSeverity.WARNING,
                    rule="frontmatter.missing",
                    message="缺少 YAML frontmatter",
                    suggestion="添加 ---\ntitle: ...\ncreated: ...\nupdated: ...\n---"
                ))
                continue
            
            # 解析 frontmatter
            end = content.find('---', 3)
            if end == -1:
                continue
            
            frontmatter = content[3:end].strip()
            
            # 检查必填字段
            for field in required_fields:
                if f"{field}:" not in frontmatter:
                    issues.append(LintIssue(
                        file_path=str(md_file.relative_to(self.project_root)),
                        line=1,
                        severity=LintSeverity.WARNING,
                        rule=f"frontmatter.{field}",
                        message=f"frontmatter 缺少字段: {field}",
                        suggestion=f"在 frontmatter 中添加 {field}: ..."
                    ))
        
        return issues
    
    def _resolve_wikilink(self, source_file: Path, link: str) -> Optional[Path]:
        """解析 wikilink 到实际文件路径"""
        # 尝试多种解析方式
        candidates = [
            self.wiki_dir / f"{link}.md",
            self.wiki_dir / link / "index.md",
            source_file.parent / f"{link}.md",
        ]
        
        for candidate in candidates:
            if candidate.exists():
                return candidate.relative_to(self.project_root)
        
        return None
```

#### 3.3.2 API 端点

```python
# backend/api/wiki_routes.py 新增端点

@router.get("/lint")
async def lint_check(project_path: str):
    """运行 Wiki 质量检查"""
    linter = WikiLint(Path(project_path))
    issues = linter.check_all()
    return {
        "total": len(issues),
        "by_severity": {
            "error": len([i for i in issues if i.severity == LintSeverity.ERROR]),
            "warning": len([i for i in issues if i.severity == LintSeverity.WARNING]),
            "info": len([i for i in issues if i.severity == LintSeverity.INFO]),
        },
        "issues": [vars(i) for i in issues]
    }
```

### 3.4 审核系统

#### 3.4.1 数据模型

```python
# backend/wiki/review.py
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional
from datetime import datetime
import json
import uuid

class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class ReviewReason(str, Enum):
    LOW_QUALITY = "low_quality"
    INACCURATE = "inaccurate"
    INCOMPLETE = "incomplete"
    DUPLICATE = "duplicate"
    NEEDS_REVIEW = "needs_review"

@dataclass
class ReviewItem:
    item_id: str
    file_path: str
    reason: ReviewReason
    confidence: float  # 0.0 - 1.0
    status: ReviewStatus
    created_at: datetime
    llm_reasoning: str
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None

class WikiReview:
    """Wiki 审核系统"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.review_file = project_root / ".llm-wiki" / "review-queue.json"
        self._items: dict[str, ReviewItem] = {}
        self._load()
    
    def _load(self):
        """加载审核队列"""
        if self.review_file.exists():
            data = json.loads(self.review_file.read_text())
            self._items = {i["item_id"]: ReviewItem(**i) for i in data["items"]}
    
    def _save(self):
        """持久化审核队列"""
        self.review_file.parent.mkdir(parents=True, exist_ok=True)
        data = {"items": [vars(i) for i in self._items.values()]}
        self.review_file.write_text(json.dumps(data, indent=2, default=str))
    
    async def sweep(self, llm_context) -> List[ReviewItem]:
        """扫描所有页面，使用 LLM 标记需要审查的内容"""
        new_items = []
        
        for md_file in (self.project_root / "wiki").rglob("*.md"):
            # 跳过已审查的文件
            if any(i.file_path == str(md_file.relative_to(self.project_root)) 
                   for i in self._items.values()):
                continue
            
            # 使用 LLM 评估质量
            content = md_file.read_text()
            evaluation = await self._evaluate_with_llm(content, llm_context)
            
            if evaluation["needs_review"]:
                item = ReviewItem(
                    item_id=str(uuid.uuid4())[:8],
                    file_path=str(md_file.relative_to(self.project_root)),
                    reason=ReviewReason(evaluation["reason"]),
                    confidence=evaluation["confidence"],
                    status=ReviewStatus.PENDING,
                    created_at=datetime.now(),
                    llm_reasoning=evaluation["reasoning"]
                )
                self._items[item.item_id] = item
                new_items.append(item)
        
        self._save()
        return new_items
    
    async def _evaluate_with_llm(self, content: str, ctx) -> dict:
        """使用 LLM 评估页面质量"""
        prompt = f"""评估以下 Wiki 页面的质量：

{content}

请评估以下方面：
1. 内容完整性（是否涵盖主题的要点）
2. 准确性（是否有明显错误）
3. 质量（写作质量、结构清晰度）
4. 是否重复（是否与其他页面重复）

返回 JSON 格式：
{{
  "needs_review": true/false,
  "reason": "low_quality|inaccurate|incomplete|duplicate|needs_review",
  "confidence": 0.0-1.0,
  "reasoning": "简要说明"
}}
"""
        
        response = await ctx.llm_call([{"role": "user", "content": prompt}])
        # 解析 JSON 响应
        # ... 实现细节省略
        
        return {"needs_review": False, "reason": "needs_review", "confidence": 0.5, "reasoning": ""}
    
    def approve(self, item_id: str, resolved_by: str = "user") -> bool:
        """批准审查项"""
        item = self._items.get(item_id)
        if item and item.status == ReviewStatus.PENDING:
            item.status = ReviewStatus.APPROVED
            item.resolved_at = datetime.now()
            item.resolved_by = resolved_by
            self._save()
            return True
        return False
    
    def reject(self, item_id: str, resolved_by: str = "user") -> bool:
        """拒绝审查项（标记为需要修改）"""
        item = self._items.get(item_id)
        if item and item.status == ReviewStatus.PENDING:
            item.status = ReviewStatus.REJECTED
            item.resolved_at = datetime.now()
            item.resolved_by = resolved_by
            self._save()
            return True
        return False
    
    def get_pending(self) -> List[ReviewItem]:
        """获取待审查项"""
        return [i for i in self._items.values() if i.status == ReviewStatus.PENDING]
    
    def get_all(self) -> List[ReviewItem]:
        """获取所有审查项"""
        return list(self._items.values())
```

#### 3.4.2 API 端点

```python
# backend/api/wiki_routes.py 新增端点

@router.post("/review/sweep")
async def review_sweep(req: ReviewSweepRequest):
    """运行审核扫描"""
    reviewer = WikiReview(Path(req.project_path))
    ctx = make_llm_context(req.llm_base_url, req.llm_api_key, req.llm_model)
    new_items = await reviewer.sweep(ctx)
    return {"new_items": len(new_items), "items": [vars(i) for i in new_items]}

@router.get("/review/items")
async def review_items(project_path: str, status: Optional[str] = None):
    """获取审查项"""
    reviewer = WikiReview(Path(project_path))
    if status == "pending":
        items = reviewer.get_pending()
    else:
        items = reviewer.get_all()
    return {"items": [vars(i) for i in items]}

@router.post("/review/approve/{item_id}")
async def review_approve(item_id: str, project_path: str):
    """批准审查项"""
    reviewer = WikiReview(Path(project_path))
    success = reviewer.approve(item_id)
    return {"success": success}

@router.post("/review/reject/{item_id}")
async def review_reject(item_id: str, project_path: str):
    """拒绝审查项"""
    reviewer = WikiReview(Path(project_path))
    success = reviewer.reject(item_id)
    return {"success": success}
```

---

## 4. 实施步骤

### Phase 1: 持久化摄入队列（优先级：高）

- [x] **步骤 1**: 实现 `backend/wiki/ingest_queue.py` 数据模型
- [x] **步骤 2**: 实现队列管理逻辑（add/get_next/mark_*/cancel/retry）
- [x] **步骤 3**: 添加 API 端点到 `backend/api/wiki_routes.py`
- [x] **步骤 4**: 编写单元测试 `backend/tests/unit/wiki/test_ingest_queue.py` (29 个用例)
- [x] **步骤 5**: 编写集成测试 `backend/tests/integration/test_wiki_queue_routes.py` (18 个用例)
- [x] **步骤 6**: 前端实现 `src/entities/wiki/queue-store.ts` (Zustand store, 10 个 action)
- [x] **步骤 7**: 前端实现 `src/widgets/wiki/WikiQueuePanel.tsx` (状态摘要 + 过滤 + 任务列表 + 操作按钮)
- [x] **步骤 8**: 集成到 `src/pages/Knowledge.tsx` (新增 'queue' 视图 + IconSidebar 入口)
- [x] **步骤 9**: 添加 API 客户端到 `src/shared/api-client/wiki.ts` (7 个 HTTP 函数)
- [x] **步骤 10**: 扩展 `WikiView` 类型 union (新增 `'queue'`)

**预计工作量**: 3-5 天

### Phase 2: Chrome Web Clipper（优先级：高）

- [x] **步骤 1**: 创建 `extension/` 目录结构
- [x] **步骤 2**: 实现 `manifest.json` 配置
- [x] **步骤 3**: 集成 Readability.js 和 Turndown.js（下载到 `lib/`）
- [x] **步骤 4**: 实现 `content.js` 内容提取
- [x] **步骤 5**: 实现 `popup.js` 用户界面
- [x] **步骤 6**: 实现 `background.js` Service Worker
- [x] **步骤 7**: 创建图标资源（16/48/128 PNG）
- [x] **步骤 8**: 后端 `POST /api/v1/wiki/clip` 端点（已存在）
- [x] **步骤 9**: 用户手册 `extension/wiki-clipper/README.md`

**预计工作量**: 2-3 天 → ✅ 实际 1 天（脚手架已存在）

### Phase 3: Lint 系统（优先级：中）

- [x] **步骤 1**: 实现 `backend/wiki/lint.py` 检查器
- [x] **步骤 2**: 实现结构检查（check_structure）
- [x] **步骤 3**: 实现 wikilink 检查（check_wikilinks）
- [x] **步骤 4**: 实现 frontmatter 检查（check_frontmatter）
- [x] **步骤 5**: 添加 API 端点到 `backend/api/wiki_routes.py`
- [x] **步骤 6**: 编写单元测试 `backend/tests/unit/wiki/test_lint.py` (29 个用例)
- [x] **步骤 7**: 编写集成测试 `backend/tests/integration/test_wiki_lint_routes.py` (6 个用例)
- [x] **步骤 8**: 前端实现 `src/widgets/wiki/WikiLintView.tsx` (severity filter + 计数 + 自动跑)
- [x] **步骤 9**: 更新 `src/entities/wiki/lint-store.ts` 调用 API (`runLint` + `mapBackendIssue`)
- [x] **步骤 10**: 集成到 `src/pages/Knowledge.tsx` (case 'lint')

**预计工作量**: 2-3 天

### Phase 4: 审核系统（优先级：中）

- [x] **步骤 1**: 实现 `backend/wiki/review.py` 检查器（确定性，无 LLM）
- [x] **步骤 2**: 实现 5 种审核器（missing-page / duplicate / contradiction / suggestion / confirm）
- [x] **步骤 3**: 实现 blake2b 内容稳定 ID（`rv-<16hex>`）+ Jaccard 相似度（阈值 0.6）
- [x] **步骤 4**: 添加 API 端点 `GET /api/v1/wiki/review` 到 `backend/api/wiki_routes.py`
- [x] **步骤 5**: 编写单元测试 `backend/tests/unit/wiki/test_review.py`（51 个用例）
- [x] **步骤 6**: 编写集成测试 `backend/tests/integration/test_wiki_review_routes.py`（8 个用例）
- [x] **步骤 7**: 更新 `src/entities/wiki/review-store.ts`（`runReview` + `mapBackendItem` + error/lastRunAt/dismissItem/reset）
- [x] **步骤 8**: 扩展 `src/shared/types/wiki.ts`（`ReviewItemRaw` / `ReviewResponse` / `ReviewItem` 加可选 backend 字段）
- [x] **步骤 9**: 添加 `wikiReviewRun` 到 `src/shared/api-client/wiki.ts`
- [x] **步骤 10**: 新增 `src/widgets/wiki/WikiReviewView.tsx`（type filter + counts + 自动运行 + dismiss）
- [x] **步骤 11**: 集成到 `src/pages/Knowledge.tsx`（`review: '内容审核'` + `case 'review':`）
- [x] **步骤 12**: 导出到 `src/widgets/wiki/index.ts`

**实际工作量**: 1.5 天

**实现说明**:
- 采用**确定性审核**而非 LLM 评估：速度快、零成本、结果稳定
- 5 类审核器：
  - `missing-page`: 收集 `[[wikilink]]` 目标 vs 实际存在页，报告断链
  - `duplicate`: 标题 token 集合 Jaccard ≥ 0.6 报重复（最少 2 token）
  - `contradiction`: frontmatter `created > updated`（ISO 字符串比较）
  - `suggestion`: 内容 < 150 字符（`short_page`）、无 title（`no_title`）
  - `confirm`: 无入链的孤儿页（零 incoming 链接）
- 豁免页：`wiki/schema.md`、`wiki/overview.md`
- blake2b 64-bit 哈希生成 `rv-` 前缀稳定 ID（同输入 → 同 ID）
- UTF-8 鲁棒性：`read_text(encoding="utf-8", errors="replace")`
- 前端 `ReviewItemRaw`（snake_case）→ `ReviewItem`（camelCase）通过 `mapBackendItem` 映射
- `WikiReviewView` 复用 `ReviewItemCard`（不修改其接口），dismiss 按钮以绝对定位覆盖


### Phase 5: 文档与测试（优先级：低）

- [x] **步骤 1**: 编写技术文档 `docs/technical/50-wiki-completeness-optimization.md`（8 章节，覆盖 4 大功能架构/集成/设计决策/测试/性能/后续优化）
- [x] **步骤 2**: 用户手册更新 `docs/user-manual/03-wiki.md`（新增 4 节：摄入队列 / Lint / Review / Chrome Clipper）
- [x] **步骤 3**: 更新技术文档索引 `docs/technical/README.md`（新增第 50 行）
- [x] **步骤 4**: 运行完整测试套件（后端 156 pass；前端 tsc 0 诊断）
- [x] **步骤 5**: 修复发现的问题（`backend/wiki/review.py` SIM102 嵌套 if 拆分；`backend/wiki/__init__.py` I001 导入排序自动修复）
- [ ] **步骤 6**: 创建 PR（待用户触发）

**实际工作量**: 0.5 天

---

## 5. 风险评估与依赖

### 5.1 风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Chrome 扩展 Manifest V3 兼容性问题 | 中 | 在 Chrome 115+ 测试，回退到 Manifest V2 |
| LLM 评估质量不稳定 | 中 | 增加 confidence 阈值，提供人工覆写 |
| 持久化队列文件损坏 | 低 | 实现 JSON 校验和备份机制 |
| Wikilink 解析误判 | 低 | 支持多种解析策略，提供忽略规则 |

### 5.2 依赖

- **Phase 1** 无外部依赖
- **Phase 2** 需要 Readability.js 和 Turndown.js（MIT 许可）
- **Phase 3** 无外部依赖
- **Phase 4** 依赖现有的 `LLMContext`（已实现）

---

## 6. 验收标准

### 6.1 功能验收

- [ ] 摄入队列支持添加、取消、重试、崩溃恢复
- [ ] Chrome 扩展可以一键抓取网页到 Wiki
- [ ] Lint 系统可以检测结构、wikilink、frontmatter 问题
- [ ] 审核系统可以使用 LLM 标记需要审查的内容
- [ ] 所有新功能有完整的单元测试和集成测试
- [ ] 前端 UI 完整实现，交互流畅

### 6.2 性能验收

- [ ] 队列操作 < 100ms
- [ ] Lint 检查 1000 个页面 < 10s
- [ ] Chrome 扩展加载 < 2s
- [ ] 审核扫描 100 个页面 < 30s（含 LLM 调用）

### 6.3 质量验收

- [ ] 测试覆盖率 > 80%
- [ ] 无 CRITICAL 或 HIGH 级别的安全问题
- [ ] 代码符合项目规范（ruff、eslint）
- [ ] 文档完整、准确

---

## 7. 后续优化（不在本次范围内）

1. **Rust Agent 运行时** — 需要架构重构，不在本次范围
2. **Obsidian 自动同步** — 可以作为独立功能实现
3. **更多 Lint 规则** — 可以逐步添加
4. **审核历史** — 可以添加更详细的审计日志
5. **批量操作** — 队列和审核的批量处理

---

## 8. 参考资料

- [Andrej Karpathy 的 LLM Wiki 设计](https://github.com/karpathy/llm-wiki)
- [Sage Wiki 技术文档](../technical/25-llm-wiki-integration.md)
- [流式架构设计规范](../superpowers/specs/2026-07-08-wiki-streaming-design.md)
- [Chrome 扩展 Manifest V3 文档](https://developer.chrome.com/docs/extensions/mv3/)
