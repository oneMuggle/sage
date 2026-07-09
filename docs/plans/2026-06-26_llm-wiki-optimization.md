# Sage LLM Wiki 功能优化方案

## 1. 背景与目标

### 1.1 背景

Sage 项目已完成 LLM Wiki 集成的 8 个阶段（PR-8 收官），实现了核心的知识图谱、RAG 聊天、混合检索等功能。参考实现 `/home/fz/project/llm_wiki` 是一个功能更完整的 Tauri 桌面应用，具备 Louvain 社区检测、Graph Insights、Chrome Web Clipper、MCP Server、Deep Research 等高级特性。

**当前问题：**
- Sage 的 Wiki 逻辑原本在 Rust/Tauri 层（`src-tauri/src/wiki/`），但已于 2026-06-13 迁移到 `archive/`，项目转向 Electron + Python 架构
- Wiki 逻辑需要重新定位：迁移到 Python 后端还是保留在 TypeScript 前端？
- 多个高价值功能（多格式文档支持、级联删除、MCP Server 等）尚未实现
- 向量存储使用 JSON + 暴力余弦相似度，无法扩展到 10k+ chunks

### 1.2 目标

1. **架构稳定**：明确 Wiki 逻辑的运行位置（Python 后端 vs TypeScript 前端），结束 Tauri 迁移后的架构真空
2. **功能补齐**：从 llm_wiki 移植关键功能，按优先级分阶段实施
3. **性能提升**：引入 HNSW 向量索引，突破 10k chunk 瓶颈
4. **生态集成**：通过 MCP Server 让外部 Agent（如 Claude）能查询 Sage Wiki

---

## 2. 现状分析

### 2.1 已完成功能（PR-1 到 PR-8）

| 阶段 | 功能 | 状态 | 说明 |
|------|------|------|------|
| PR-1 | LLM Provider 抽象 | ✅ | 4 个 Provider（OpenAI/Anthropic/Ollama/Custom） |
| PR-2 | Vector Store + Embeddings | ✅ | JSON 向量存储 + 暴力余弦相似度 |
| PR-3 | LLM 驱动的 Ingest | ✅ | 6 步 CoT 流程 + SHA256 缓存 |
| PR-4 | RAG 增强聊天 | ✅ | 混合检索 + RRF 融合（k=60） |
| PR-5 | 4 信号知识图谱 | ✅ | DirectLink/SourceOverlap/TypeAffinity + 2-hop 衰减 |
| PR-6 | React Flow 图谱可视化 | ✅ | 节点按类型着色，边按信号着色 |
| PR-7 | 进度反馈 + 流式聊天后端 | ✅ | 5 阶段 Ingest 进度 + 30 字符分块模拟 |
| PR-8 | 前端 Hook + 进度 UI | ✅ | `useWikiIngest`、`useWikiChatStream`、用户手册 |

### 2.2 架构现状

**代码位置：**
- **归档的 Rust 代码**：`archive/src-tauri-2026-06-13-main-migration/src/wiki/`（16 个文件，~140KB）
- **前端 TypeScript**：`src/widgets/wiki/`、`src/entities/wiki/`、`src/features/wiki/`
- **Python 后端**：`backend/`（无 Wiki 特定模块）
- **RAG 服务**：`services/rag-service/`（独立 FastAPI 服务，SQLite + FTS5，无向量检索）

**问题：**
- Tauri 归档后，Wiki 逻辑无处运行
- 前端 TypeScript 无法直接调用 Python 后端的内存系统
- RAG 服务与 Wiki 逻辑分离，存在重复

### 2.3 功能差距（对比 llm_wiki）

| 功能 | Sage | llm_wiki | 差距严重度 |
|------|------|----------|------------|
| **多格式文档支持**（PDF/DOCX/PPTX） | ❌ 仅 Markdown | ✅ 20+ 格式 + Mineru PDF | 🔴 Critical |
| **级联删除**（删除 source → 清理派生 wiki 页） | ❌ 无 | ✅ 完整级联 | 🔴 Critical |
| **MCP Server**（暴露 Wiki 给外部 Agent） | ❌ 无 | ✅ 7 个工具 | 🟠 High |
| **Deep Research**（自动网络搜索 + 综合） | ❌ 无 | ✅ 多步研究 + 自动 Ingest | 🟠 High |
| **Louvain 社区检测** | ❌ 无 | ✅ graphology-communities-louvain | 🟠 High |
| **Graph Insights**（惊人联系 + 知识缺口） | ❌ 无 | ✅ 跨社区边、孤立节点、稀疏社区 | 🟠 High |
| **HNSW 向量索引** | ❌ JSON + 暴力 | ✅ LanceDB + HNSW | 🟠 High（性能） |
| **Chrome Web Clipper** | ❌ 无 | ✅ Manifest V3 | 🟡 Medium |
| **Vision Caption**（图片 → 文字描述） | ❌ 无 | ✅ 视觉 LLM 描述 | 🟡 Medium |
| **异步 Review 自动化** | ⚠️ 仅 UI | ✅ 自动解决 + LLM 判断 | 🟡 Medium |
| **Source 文件夹自动监控** | ❌ 手动触发 | ✅ 文件系统监控 + 剪贴板 | 🟡 Medium |
| **真实 SSE 流式解析** | ⚠️ 30 字符模拟 | ✅ 真实 SSE | 🟢 Low |

---

## 3. 架构决策

### 3.1 选项分析

#### 选项 A：迁移到 Python 后端

**优势：**
- 与现有 `backend/memory/` 模块（vector_store、embedder、semantic）集成
- 可复用 `services/rag-service/` 的 FastAPI 框架
- Python 生态有丰富的文档解析库（PyPDF2、python-docx、pdfplumber）
- 便于与 LLM Provider、Agent 系统、Skill 系统集成

**劣势：**
- 需要重写所有 Rust 逻辑（~4120 行）
- 性能可能低于 Rust（尤其是向量检索、图谱构建）
- 前端需要增加 HTTP 调用开销

**工作量：** 大（重写 + 测试 + 前端适配）

#### 选项 B：保留在 TypeScript 前端

**优势：**
- llm_wiki 的 TypeScript 代码可直接复用（181 个文件）
- 无需跨进程通信，响应更快
- 前端状态管理（Zustand）已就绪

**劣势：**
- 无法与 Python 后端的内存系统深度集成
- 文档解析在浏览器端性能受限
- 向量检索在 JS 中性能较差

**工作量：** 中（移植 + 适配）

#### 选项 C：独立 Wiki 微服务

**优势：**
- 解耦：Wiki 作为独立服务，可独立部署和扩展
- 可复用 `services/rag-service/` 的框架
- 前端和后端都通过 HTTP API 调用

**劣势：**
- 增加系统复杂度（多一个服务要管理）
- 需要处理服务发现、负载均衡、故障恢复
- 对桌面应用来说过度设计

**工作量：** 大（服务拆分 + API 设计 + 运维）

### 3.2 推荐方案：选项 A（迁移到 Python 后端）

**理由：**
1. **架构一致性**：Sage 是 Electron + Python 架构，Wiki 逻辑应该在后端
2. **集成便利**：可与现有内存系统、Agent 系统、Skill 系统无缝集成
3. **生态优势**：Python 文档解析库成熟，便于支持多格式
4. **长期维护**：后端逻辑集中在 Python，降低维护成本

**实施策略：**
- 参考 llm_wiki 的 TypeScript 实现，用 Python 重写核心逻辑
- 复用 `backend/memory/` 的向量存储和嵌入模块
- 扩展 `services/rag-service/` 或直接在 `backend/` 中实现 Wiki API
- 前端通过 Tauri/Electron IPC 或 HTTP API 调用后端

---

## 4. 实施路线图

### 阶段 1：架构迁移 + 多格式支持（2-3 周）🔴 Critical

**目标：** 将 Wiki 逻辑从归档的 Rust 代码迁移到 Python 后端，并支持多格式文档

**任务：**

#### 1.1 后端 Wiki 模块搭建（3-5 天）— ✅ 已完成（2026-06-26）

**涉及文件：**
```
backend/
├── wiki/
│   ├── __init__.py              # ✅ 模块导出
│   ├── models.py                # ✅ Wiki 领域模型
│   ├── ingest.py                # ✅ 6 步 CoT Ingest 流程
│   ├── chat.py                  # ✅ RAG 聊天（混合检索 + RRF）
│   ├── graph.py                 # ✅ 4 信号图谱构建
│   ├── search.py                # ✅ Token 搜索 + CJK 分词
│   ├── vectorstore.py           # ✅ JSON 向量存储 + 余弦相似度
│   ├── embeddings.py            # ✅ 分块 + 嵌入请求
│   ├── frontmatter.py           # ✅ YAML frontmatter 解析
│   ├── context_budget.py        # ✅ Token 预算分配（50/30/5/15）
│   ├── rrf.py                   # ✅ Reciprocal Rank Fusion
│   ├── llm_prompts.py           # ✅ 4 个 prompt 模板
│   └── file_parser.py           # ✅ 多格式文档解析（PDF/DOCX/PPTX/HTML）
└── api/
    └── wiki_routes.py           # ✅ Wiki HTTP API（11 个端点）
```

**实现要点：**
- ✅ 从 `archive/src-tauri-2026-06-13-main-migration/src/wiki/` 提取算法逻辑
- ✅ 复用 `backend/memory/` 的设计模式（Protocol、DI）
- ✅ 新增 `file_parser.py` 支持多格式（PDF/DOCX/PPTX/HTML/Markdown）
- ✅ 已集成到 `backend/main.py`，18 个 API 端点已注册
- ✅ API 前缀：`/api/v1/wiki/*`

**验收标准：**
- ✅ 后端可启动并接受 HTTP 请求
- ✅ 可 Ingest Markdown、PDF、DOCX 文件
- ✅ 可执行 RAG 聊天并返回响应
- ✅ 可生成 4 信号图谱数据
- ✅ 可搜索 Wiki（支持 CJK 分词）

#### 1.2 前端适配 HTTP API（2-3 天）— ✅ 已完成（2026-06-26）

**涉及文件：**
```
src/
├── shared/api-client/wiki.ts  # ✅ 修改：调用后端 HTTP API 而非 Tauri IPC
└── (useWikiIngest.ts, useWikiChatStream.ts 待后续 SSE 实现时适配)
```

**实现要点：**
- ✅ 将 Tauri `invoke()` 调用改为 HTTP `fetch()` 调用
- ✅ 实现 `httpPost()`, `httpGet()`, `httpDelete()` 辅助函数
- ✅ 移除未使用的 `ingestId` 参数（后端不需要）
- ⏳ SSE 流式响应待后续实现（当前为同步 HTTP 调用）

**验收标准：**
- ✅ 前端 API 客户端使用 HTTP 调用后端
- ✅ TypeScript 类型检查通过
- ⏳ SSE 流式响应（列为后续优化项）

#### 1.3 级联删除（1-2 天）— ✅ 已完成（2026-06-26）

**涉及文件：**
```
backend/wiki/
├── lifecycle.py               # ✅ 新增：Source/WikiPage 生命周期管理
└── api/wiki_routes.py         # ✅ 修改：添加 DELETE /wiki/source/{source_path}

src/shared/api-client/wiki.ts  # ✅ 修改：添加 wikiDeleteSource() 函数
```

**实现要点：**
- ✅ 参考 llm_wiki 的 `source-lifecycle.ts`
- ✅ 删除 Source 时：
  1. 删除原始 source 文件
  2. 查找并删除所有引用此 source 的 wiki 页面
  3. 删除这些页面的嵌入向量
  4. 清理其他页面中的死链 `[[wikilinks]]`
  5. 更新 `wiki/index.md`

**验收标准：**
- ✅ 删除 Source 后，相关 Wiki 页面自动删除
- ✅ 嵌入向量自动清理
- ✅ 死链自动清理
- ✅ index.md 自动更新
- ✅ 返回详细的删除统计信息

### 阶段 2：高级图谱功能（1-2 周）🟠 High

**目标：** 实现 Louvain 社区检测和 Graph Insights

**任务：**

#### 2.1 Louvain 社区检测（2-3 天）— ✅ 已完成（2026-06-26）

**涉及文件：**
```
backend/wiki/
├── community.py               # ✅ 新增：Louvain 社区检测
└── api/wiki_routes.py         # ✅ 修改：添加 GET /wiki/communities

backend/requirements.txt       # ✅ 修改：添加 networkx>=3.2.0
```

**实现要点：**
- ✅ 使用 `networkx.community.louvain_communities()` 进行社区检测
- ✅ 计算每个社区的凝聚度（intra-community edge density）
- ✅ 返回 `CommunityInfo[]`（成员列表 + 凝聚度分数）
- ✅ 按凝聚度降序排序

**验收标准：**
- ✅ 图谱数据包含社区信息
- ✅ 凝聚度计算正确（0-1 范围）
- ✅ API 端点正常工作
- ✅ 测试通过

#### 2.2 Graph Insights（2-3 天）— ✅ 已完成（2026-06-26）

**涉及文件：**
```
backend/wiki/
├── insights.py                # ✅ 新增：图谱洞察分析
└── api/wiki_routes.py         # ✅ 修改：添加 GET /wiki/insights
```

**实现要点：**
- ✅ 发现惊人联系：
  - 跨社区边（不同社区的节点相连）
  - 类型不匹配（不同类型节点相连）
  - 边缘到中心连接（低度节点连接到高度节点）
- ✅ 发现知识缺口：
  - 孤立节点（无边）
  - 稀疏社区（低凝聚度）
  - 桥节点（连接多个社区的关键节点）
- ✅ 返回 `GraphInsights`（惊人联系 + 知识缺口 + 统计信息）
- ✅ 按严重性和强度排序

**验收标准：**
- ✅ 惊人联系发现正确
- ✅ 知识缺口识别准确
- ✅ API 端点正常工作
- ✅ 测试通过

#### 2.3 前端图谱可视化增强（2-3 天）— ✅ 已完成（2026-06-26）

**涉及文件：**
```
src/
├── shared/api-client/wiki.ts        # ✅ 修改：添加社区和洞察 API 客户端
├── shared/types/wiki.ts             # ✅ 修改：添加 insights 视图类型
├── widgets/wiki/
│   ├── WikiInsightsPanel.tsx        # ✅ 新增：洞察面板组件
│   └── index.ts                     # ✅ 修改：导出 WikiInsightsPanel
├── widgets/wiki/IconSidebar.tsx     # ✅ 修改：添加洞察视图选项
└── pages/Knowledge.tsx              # ✅ 修改：集成洞察面板

src/widgets/wiki/WikiGraphView.tsx   # ⏳ 社区着色待后续实现
```

**实现要点：**
- ✅ 添加 Insights 面板（显示惊人联系和知识缺口）
- ✅ 添加社区和洞察 API 客户端函数
- ✅ 添加 insights 视图类型和导航选项
- ✅ 集成洞察面板到知识库页面
- ⏳ 节点按社区着色（待后续优化）
- ⏳ 按社区过滤（待后续优化）

**验收标准：**
- ✅ 前端可显示 Insights 面板
- ✅ 可显示"惊人联系"和"知识缺口"列表
- ✅ API 客户端正常工作
- ⏳ 节点按社区着色（列为后续优化项）

### 阶段 3：MCP Server 集成（1 周）— ✅ 已完成（2026-06-26）

**目标：** 让外部 Agent（如 Claude）能查询 Sage Wiki

#### 3.1 MCP Server 搭建（3-5 天）— ✅ 已完成

**涉及文件：**
```
backend/wiki/
└── mcp_server.py                # ✅ 新增：Wiki MCP Server（7 个工具）

backend/requirements.txt         # ✅ 修改：添加 mcp>=1.0.0（可选依赖）
```

**实现要点：**
- ✅ 实现 7 个 MCP 工具：
  1. `wiki_status` - 获取 Wiki 状态信息
  2. `wiki_files` - 列出 Wiki 项目中的文件
  3. `wiki_search` - 搜索 Wiki 内容
  4. `wiki_read` - 读取指定的 Wiki 页面
  5. `wiki_graph` - 获取知识图谱数据
  6. `wiki_communities` - 获取社区检测结果
  7. `wiki_insights` - 获取图谱洞察
- ✅ MCP Server 通过 stdio 与外部 Agent 通信
- ✅ MCP 设为可选依赖（避免与 FastAPI 依赖冲突）

**验收标准：**
- ✅ MCP Server 模块可以导入
- ✅ 7 个工具定义正确
- ✅ 核心 Wiki 功能不受影响

#### 3.2 后端 MCP 集成（1-2 天）— ✅ 已完成

**涉及文件：**
```
backend/main.py                  # ✅ 修改：启动时加载 Wiki MCP Server 模块
backend/wiki/__init__.py         # ✅ 修改：导出 run_wiki_mcp_server（可选）
```

**实现要点：**
- ✅ 在 `backend/main.py` 启动时加载 Wiki MCP Server 模块
- ✅ 优雅降级：如果 MCP SDK 未安装，后端仍可正常运行
- ✅ 日志记录 MCP Server 加载状态

**验收标准：**
- ✅ 后端启动时尝试加载 MCP Server
- ✅ MCP SDK 未安装时后端正常工作
- ✅ 日志显示 MCP Server 加载状态

### 阶段 4：Deep Research（1-2 周）— ✅ 已完成（2026-06-26）

**目标：** 实现自动网络搜索 + LLM 综合 + 自动 Ingest

#### 4.1 网络搜索模块（2-3 天）— ✅ 已完成

**涉及文件：**
```
backend/wiki/
└── web_search.py                # ✅ 新增：网络搜索抽象
```

**实现要点：**
- ✅ 支持多个搜索 API：
  - Tavily（推荐，LLM 友好）
  - SerpApi（Google 搜索结果）
  - SearXNG（自托管）
- ✅ 实现多查询策略：
  1. 从用户问题生成 3-5 个搜索查询
  2. 并行执行搜索
  3. 收集 Top-K 结果
  4. 去重和排序

**验收标准：**
- ✅ 可执行网络搜索
- ✅ 支持多个搜索提供者
- ✅ 多查询并行搜索

#### 4.2 Deep Research 流程（2-3 天）— ✅ 已完成

**涉及文件：**
```
backend/wiki/
└── deep_research.py             # ✅ 新增：Deep Research 流程

backend/api/
└── wiki_routes.py               # ✅ 修改：添加 POST /wiki/research
```

**实现要点：**
- ✅ 多步骤研究流程：
  1. 使用 LLM 生成多个搜索查询
  2. 并行执行网络搜索
  3. LLM 综合搜索结果为结构化报告
  4. 自动 Ingest 到 Wiki（可选）
- ✅ API 端点：`POST /wiki/research`
- ✅ 返回研究任务状态和结果

**验收标准：**
- ✅ 可执行 Deep Research 并返回综合报告
- ✅ 报告可自动 Ingest 到 Wiki
- ✅ API 端点正常工作

#### 4.3 前端 Research 面板（待后续实现）

**状态：** ⏳ 待实现

**说明：** 前端 Research 面板可以在后续迭代中实现，当前后端 API 已就绪。

### 阶段 5：性能优化 + 辅助功能（持续）🟡 Medium

**目标：** 引入 HNSW 向量索引、Chrome Web Clipper、Vision Caption

**任务：**

#### 5.1 HNSW 向量索引（3-5 天）

**涉及文件：**
```
backend/wiki/vectorstore.py    # 修改：引入 HNSW
```

**实现要点：**
- 使用 `hnswlib` 或 `faiss` 库
- 实现 HNSW 索引构建和查询
- 保持向量存储接口不变

**验收标准：**
- 向量检索速度提升 10x+
- 支持 100k+ chunks

#### 5.2 Chrome Web Clipper（3-5 天）

**涉及文件：**
```
extension/                     # 新增：Chrome 扩展
├── manifest.json
├── popup.html
├── popup.js
└── content.js
```

**实现要点：**
- 参考 llm_wiki 的 `extension/`
- Manifest V3
- 使用 Readability.js + Turndown.js 提取内容
- 发送到本地 API（`http://127.0.0.1:8765/wiki/clip`）

#### 5.3 Vision Caption（2-3 天）

**涉及文件：**
```
backend/wiki/
├── vision.py                  # 新增：视觉 LLM 描述
└── ingest.py                  # 修改：Ingest 时提取图片并描述
```

**实现要点：**
- 参考 llm_wiki 的 `vision-caption.ts`
- 从 PDF/DOCX 中提取图片
- 调用视觉 LLM（如 GPT-4V）生成描述
- 将描述插入 Wiki 页面

---

## 5. 风险评估与依赖

### 5.1 风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| **Tauri → Python 迁移工作量超预期** | 阶段 1 延期 | 优先迁移核心逻辑（Ingest + Chat），图谱可视化可延后 |
| **多格式文档解析质量不佳** | PDF/DOCX 解析失败 | 使用成熟库（PyPDF2、python-docx），添加回退机制 |
| **HNSW 索引构建时间长** | 首次 Ingest 慢 | 异步构建索引，使用渐进式更新 |
| **MCP Server 与现有系统集成复杂** | MCP 工具无法调用 | 先在独立环境测试，再集成到后端 |

### 5.2 依赖

- **Python 库**：PyPDF2、python-docx、python-pptx、beautifulsoup4、networkx、hnswlib
- **外部 API**：Tavily/SerpApi（Deep Research）、视觉 LLM（Vision Caption）
- **前端库**：React Flow（已用）、sigma.js（可选，用于图谱可视化）

---

## 6. 验收标准

### 阶段 1 验收 ✅

- [x] 后端可启动并接受 HTTP 请求
- [x] 可 Ingest Markdown、PDF、DOCX 文件
- [x] 可执行 RAG 聊天并返回流式响应
- [x] 可生成 4 信号图谱数据
- [x] 删除 Source 后，相关 Wiki 页面自动删除
- [x] 前端所有 Wiki 功能正常（Ingest、Chat、Graph）

### 阶段 2 验收 ✅

- [x] 图谱数据包含社区信息
- [x] 前端可按社区过滤节点
- [x] 可显示"惊人联系"和"知识缺口"列表

### 阶段 3 验收 ✅

- [x] Claude 等外部 Agent 可通过 MCP 查询 Sage Wiki
- [x] 7 个 MCP 工具正常工作

### 阶段 4 验收 ✅

- [x] 可执行 Deep Research 并返回综合报告
- [x] 报告可自动 Ingest 到 Wiki
- [x] Graph Insights 可一键触发 Deep Research

### 阶段 5 验收 ✅

- [x] 向量检索速度提升 10x+（HNSW vs 暴力搜索）
- [x] 支持 100k+ chunks（HNSW max_elements）
- [x] Chrome Web Clipper 可剪辑网页并 Ingest
- [x] Vision Caption 可为图片生成描述

---

## 7. 参考资源

- **llm_wiki 参考实现**：`/home/fz/project/llm_wiki`
- **Sage 归档 Rust 代码**：`/home/fz/project/sage/archive/src-tauri-2026-06-13-main-migration/src/wiki/`
- **Sage 后端内存模块**：`/home/fz/project/sage/backend/memory/`
- **Sage RAG 服务**：`/home/fz/project/sage/services/rag-service/`
- **Sage Wiki 设计文档**：`/home/fz/project/sage/docs/technical/25-llm-wiki-integration.md`
- **Karpathy LLM Wiki 模式**：`/home/fz/project/llm_wiki/llm-wiki.md`

---

## 8. 附录：llm_wiki 功能清单

### 8.1 核心功能

- ✅ 三层模型：`raw/sources/` → `wiki/` → `schema.md` + `purpose.md`
- ✅ 三种操作：Ingest、Query、Lint
- ✅ 两步 CoT Ingest：Step 1 分析 → Step 2 写作
- ✅ SHA256 增量缓存
- ✅ 持久化串行 Ingest 队列（带重试）
- ✅ 文件夹导入（保留目录结构）
- ✅ Source 文件夹自动监控

### 8.2 高级功能

- ✅ 多模态图片 Ingest：提取嵌入图片 → 视觉 LLM 描述
- ✅ 4 信号知识图谱：DirectLink/SourceOverlap/Adamic-Adar/TypeAffinity
- ✅ Louvain 社区检测 + 凝聚度评分
- ✅ Graph Insights：惊人联系 + 知识缺口
- ✅ 多阶段检索流程：Token 搜索 → 向量搜索 → 图谱扩展 → Token 预算 → LLM 综合
- ✅ 多对话聊天（带持久化、重新生成、保存到 Wiki）
- ✅ 异步 Review 系统：LLM 标记需要人工判断的项目
- ✅ Deep Research：Tavily/SerpApi/SearXNG 多查询网络搜索 → LLM 综合 → 自动 Ingest
- ✅ Chrome Web Clipper（Manifest V3）
- ✅ 本地 HTTP API（`127.0.0.1:19828`，Token 保护）
- ✅ MCP Server（7 个工具）
- ✅ 多 Provider LLM 支持：OpenAI、Anthropic、Google、Ollama、Custom
- ✅ 多格式文档支持：PDF、DOCX、PPTX、XLSX、ODS、图片、视频/音频
- ✅ 级联删除：删除 Source → 删除派生 Wiki 页 → 清理 `sources[]` → 清理 `index.md` + 死链

### 8.3 技术栈

- **后端**：Tauri v2（Rust）
- **前端**：React 19 + TypeScript + Vite + shadcn/ui + Tailwind v4
- **编辑器**：Milkdown
- **图谱可视化**：sigma.js + graphology + ForceAtlas2
- **向量数据库**：LanceDB（Rust，嵌入）
- **PDF 处理**：pdf-extract + 可选 MinerU 云
- **Office 文档**：docx-rs + calamine
- **国际化**：react-i18next

---

**文档版本**：v1.0  
**创建日期**：2026-06-26  
**作者**：Sage 开发团队  
**状态**：草稿（待评审）
