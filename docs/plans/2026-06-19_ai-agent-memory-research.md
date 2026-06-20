# AI Agent 记忆系统研究报告

> 调研日期: 2026-06-19
> 调研对象: Hermes Agent, Mem0, Letta (MemGPT), 通用 AI Agent 记忆模式

---

## 目录

- [1. 调研概述](#1-调研概述)
- [2. Hermes Agent 记忆系统](#2-hermes-agent-记忆系统)
- [3. Mem0 记忆系统](#3-mem0-记忆系统)
- [4. Letta (MemGPT) 记忆系统](#4-letta-memgpt-记忆系统)
- [5. 记忆类型分类](#5-记忆类型分类)
- [6. 向量数据库对比](#6-向量数据库对比)
- [7. 图记忆方案](#7-图记忆方案)
- [8. 记忆整合策略](#8-记忆整合策略)
- [9. 混合检索方案](#9-混合检索方案)
- [10. 记忆注入与上下文格式化](#10-记忆注入与上下文格式化)
- [11. Token 预算管理](#11-token-预算管理)
- [12. 三大系统对比总结](#12-三大系统对比总结)
- [13. 最佳实践与反模式](#13-最佳实践与反模式)
- [14. 对 Sage 项目的启示](#14-对-sage-项目的启示)

---

## 1. 调研概述

AI Agent 记忆系统是 2025–2026 年 LLM 工程领域最活跃的研究方向之一。核心问题：**如何在有限的上下文窗口中高效管理跨会话的持久化知识？**

三大代表性项目采用了截然不同的设计哲学：

| 项目 | 设计哲学 | 核心洞察 |
|------|----------|----------|
| **Hermes Agent** | 固定预算 + 冻结快照 | 有限记忆是特性，不是缺陷；强制高信息密度 |
| **Mem0** | 提取时蒸馏 | LLM 从对话中提取原子事实 → 向量/图存储 |
| **Letta (MemGPT)** | 操作系统式虚拟内存 | Agent 自主管理上下文窗口（RAM）与外部存储（磁盘）之间的数据流动 |

---

## 2. Hermes Agent 记忆系统

> 来源: [NousResearch/hermes-agent](https://github.com/nousresearch/hermes-agent), [官方文档](https://hermes-agent.nousresearch.com/docs/)

### 2.1 架构概览

Hermes Agent 采用 **分层、有界、文件支撑** 的记忆架构，围绕三个核心原则：

1. **固定预算优于无限增长** — 记忆容量有上限，保证 token 成本可预测
2. **冻结快照保证缓存稳定** — 会话中途的写入不会使 LLM 的 KV Cache 失效
3. **安全优先的持久化** — 多级威胁扫描防止通过持久化记忆进行 prompt 注入

### 2.2 五层记忆模型

| 层 | 名称 | 存储 | 生命周期 | 容量 |
|---|------|------|----------|------|
| 1 | **持久化记忆** (`MEMORY.md`) | Markdown 文件 | 跨会话 | ~2,200 字符 ≈ 800 token |
| 2 | **用户画像** (`USER.md`) | Markdown 文件 | 跨会话 | ~1,375 字符 ≈ 500 token |
| 3 | **会话搜索** (FTS5) | SQLite 数据库 | 无限历史 | 全部会话记录 |
| 4 | **外部记忆提供者** | 插件（8 个可选） | 跨会话 | 取决于后端 |
| 5 | **技能/程序化记忆** | Markdown 文件 | 持久化 | 可复用工作流 |

**总固定成本: 3,575 字符 ≈ 1,300 token/会话**

### 2.3 为什么用字符限制而非 token 限制？

源码注释: *"Character limits (not tokens) because char counts are model-independent."* 不同模型有不同的分词器，但字符计数是通用的。

### 2.4 冻结快照机制（最关键的设计决策）

```
会话开始
  ├── load_from_disk()
  │   ├── 读取 MEMORY.md → 活动状态
  │   ├── 读取 USER.md   → 活动状态
  │   ├── 安全扫描 → 净化条目
  │   └── 生成 _system_prompt_snapshot（冻结的，不可变的）
  │
  │ 系统提示注入
  │   format_for_system_prompt() → 返回冻结快照
  │
  │ 会话中途写入
  │   add/replace/remove → 更新活动状态 + 写入磁盘
  │   但系统提示快照保持不变
  │
  │ 下次会话
  │   load_from_disk() → 新的冻结快照
```

**为什么冻结？** LLM 推理会将系统提示缓存为 KV Cache。如果前缀哪怕变化一个字符，整个缓存就会失效。冻结快照在整个会话期间保持前缀稳定，防止 token 成本飙升。

### 2.5 系统提示组装（三层架构）

| 层 | 内容 | 缓存行为 |
|---|------|---------|
| **稳定层** | Agent 身份 (`SOUL.md`)、工具/模型指导、技能索引、环境提示 | 跨会话稳定 |
| **上下文层** | 项目上下文文件 (`.hermes.md`/`AGENTS.md`/`CLAUDE.md`) | 会话级稳定 |
| **易变层** | 记忆快照 (`MEMORY.md`)、用户画像快照 (`USER.md`)、外部记忆块、时间戳 | 会话级冻结 |

记忆属于"易变层"但在会话内冻结，使其在会话期间实际表现为稳定。这种分层排序最大化 KV Cache 复用。

### 2.6 外部记忆提供者

8 个可插拔的提供者：

| 提供者 | 关键特性 |
|--------|---------|
| **Honcho** | 辩证用户建模，知识图谱 |
| **OpenViking** | 语义搜索 |
| **Mem0** | 自动事实提取 |
| **Hindsight** | 跨会话用户建模 |
| **Holographic** | — |
| **RetainDB** | — |
| **ByteRover** | — |
| **Supermemory** | Cloudflare Workers 上的长期记忆 |

**约束**: 同一时间只能激活一个外部提供者（由 `MemoryManager` 强制执行）。

### 2.7 MemoryProvider 接口

```python
from agent.memory_provider import MemoryProvider

class MyMemoryProvider(MemoryProvider):
    @property
    def name(self) -> str: ...
    def is_available(self) -> bool: ...  # 不允许网络调用
    def initialize(self, session_id: str, **kwargs) -> None: ...
    def get_tool_schemas(self) -> list: ...
    def handle_tool_call(self, tool_name, args, **kwargs) -> Any: ...
    def shutdown(self) -> None: ...

    # 生命周期钩子
    def prefetch(self, query, session_id) -> None: ...       # 每次 API 调用前
    def queue_prefetch(self, query, session_id) -> None: ...  # 每次 turn 后
    def sync_turn(self, user, assistant, session_id) -> None: ...
    def on_pre_compress(self, messages) -> None: ...          # 上下文压缩前
```

### 2.8 记忆整合策略（Agent 驱动）

Hermes **不做自动压缩**。当 `add` 超出字符限制时，工具返回错误并列出当前条目，指导 Agent 执行：

1. 读取当前条目（在错误响应中展示）
2. 识别可删除或合并的条目
3. 使用 `replace` 将相关条目合并为更短的版本
4. 然后 `add` 新条目

**效果**: 固定预算迫使 Agent 保持高信息密度 — "压缩即整合，而非丢失"。

### 2.9 安全架构

三级威胁扫描：

| 范围 | 应用于 | 检测 |
|------|--------|------|
| `all` | 所有文本 | 经典注入 + 数据泄露 |
| `context` | 上下文文件 + 记忆 + 工具结果 | C2/promptware/角色劫持 |
| `strict` | 记忆写入 + 技能安装 | 持久化攻击、SSH 后门、URL 泄露 |

扫描点：**写入时**（每次 add/replace 前）+ **加载时**（`load_from_disk` 期间）。

---

## 3. Mem0 记忆系统

> 来源: [Mem0 论文 (arXiv:2504.19413)](https://arxiv.org/abs/2504.19413), [官方文档](https://docs.mem0.ai/), [Dwarves Memo 技术拆解](https://memo.d.foundation/breakdown/mem0)

### 3.1 架构概览

Mem0（读作 "mem-zero"）是可扩展的记忆驱动架构，发表于 **ECAI 2025**。核心思想：**从对话中动态提取、整合和检索** 重要信息，赋予 Agent 跨会话的持久长期记忆。

两个变体：
- **Mem0** — 基于向量的记忆（原子事实 + 嵌入）
- **Mem0ᵍ (Mem0g)** — 图增强记忆（实体为节点，关系为边）

### 3.2 核心组件

| 组件 | 角色 |
|------|------|
| **Extractor（提取器）** | 基于 LLM 的模块，从对话轮次中识别重要事实 |
| **Updater（更新器）** | 通过工具调用评估提取的事实与现有记忆的关系，决定 ADD/UPDATE/DELETE/NOOP |
| **Retriever（检索器）** | 使用多信号搜索获取当前轮次的相关记忆 |
| **Memory Store（记忆存储）** | 可插拔后端 — 向量数据库（Mem0）或图数据库（Mem0g） |
| **Summary Generator（摘要生成器）** | 异步模块，定期刷新对话摘要提供全局上下文 |

### 3.3 两阶段流水线（原始算法）

**阶段 1: 提取**
1. 新消息对 $(m_{t-1}, m_t)$ 到达
2. 收集两个上下文源：
   - **对话摘要** $S$ — 整个历史的语义概览（异步生成，定期刷新）
   - **近期消息** $\{m_{t-m}, ..., m_{t-2}\}$ — 最近 $m$ 条消息（默认 $m=10$）
3. 组合提示 $P = (S, \{m_{t-m},...,m_{t-2}\}, m_{t-1}, m_t)$ 送入 LLM 提取函数 $\phi$
4. 输出：候选事实集 $\Omega = \{\omega_1, \omega_2, ..., \omega_n\}$

**阶段 2: 更新**
1. 对每个候选事实 $\omega_i$：
   - 检索 top-$s$ 语义相似的现有记忆（默认 $s=10$）
   - 通过**工具调用接口**将候选事实 + 相似记忆呈现给 LLM
   - LLM 决定四种操作之一：
     - **ADD** — 新事实，无等价物存在
     - **UPDATE** — 用更丰富/更新的信息增强现有记忆
     - **DELETE** — 移除被矛盾的记忆
     - **NOOP** — 事实已存在或不相关

### 3.4 v3 新算法（2026 年 4 月）

重大重设计，**LoCoMo 提升 +20 分**（71.4→91.4），**LongMemEval 提升 +26 分**（67.8→93.4）：

**提取：单次 ADD-only**
```
输入对话
  → 检索 top-10 相关现有记忆（去重上下文）
  → 单次 LLM 调用：提取所有不同的新事实
  → 批量嵌入提取的记忆
  → 基于哈希的去重（MD5，防止精确重复）
  → 批量插入向量存储
  → 实体提取 + 链接
```
关键变化：**提取时不再 UPDATE/DELETE**。每个事实作为独立记录保存。状态变化（如"从纽约搬到旧金山"）保留为单独记录，支持时间推理。

**检索：多信号混合搜索**
```
查询
  → 预处理（关键词词形还原、spaCy 实体提取）
  → 并行评分：
    1. 语义搜索（向量余弦相似度）
    2. BM25 关键词搜索（归一化词项匹配）
    3. 实体匹配（来自 entities 集合的实体图提升）
  → 分数融合 → Top-K 选择（默认 top_k=20）
```

### 3.5 存储后端

#### 向量存储（15+ 支持的后端）

| 提供者 | 备注 |
|--------|------|
| **Qdrant** | 主要后端；使用稀疏向量 (BM25) + 密集向量 |
| **ChromaDB** | 嵌入式 |
| **Pinecone** | 托管云 |
| **FAISS** | 本地/嵌入式 |
| **PGVector / PostgreSQL** | 关系型 + 向量 |
| **Milvus** | 大规模 |
| **Weaviate** | 企业级 |
| **Supabase** | |
| **MongoDB** | |
| **Redis** | |
| **Elasticsearch** | |
| **Azure AI Search** | |
| **Upstash Vector** | |
| **Vertex AI Vector Search** | |

#### 图数据库（Mem0g）

原始版本使用 **Neo4j** 作为主要图存储。**v3 (2026 年 4 月) 中，开源 SDK 移除了图存储支持**，替换为内置的**实体链接** — 实体提取后存储在并行向量集合中，无需外部图数据库。Mem0 Platform 仍提供图记忆作为托管功能。

### 3.6 上下文注入格式

```
# CONTEXT:
You have access to memories from speakers in a conversation.
These memories contain timestamped information relevant to the question.

# INSTRUCTIONS:
1. Analyze all provided memories
2. Pay attention to timestamps
3. If contradictory info, prioritize most recent memory
4. Convert relative time references to specific dates

Memories for user {user_id}:
{speaker_memories}

Question: {question}
Answer:
```

### 3.7 Token 效率

| 系统 | 平均 token/对话 |
|------|----------------|
| **Mem0** | ~7,000 token |
| **Mem0g** | ~14,000 token（因图节点+关系翻倍） |
| **完整上下文（原始对话）** | ~26,000 token |
| **Zep（竞品）** | ~600,000 token |

---

## 4. Letta (MemGPT) 记忆系统

> 来源: [原始论文 (arXiv:2310.08560)](https://arxiv.org/abs/2310.08560), [Letta 官方文档](https://docs.letta.com/), [Terse Systems 深度分析](https://tersesystems.com/blog/2025/02/14/adding-memory-to-llms-with-letta/)

### 4.1 OS 虚拟内存类比

MemGPT 的基础洞察（Packer et al., 2023, UC Berkeley）：将 LLM 的上下文窗口视为**物理内存 (RAM)**，外部存储视为**磁盘**，直接借用传统操作系统的虚拟内存分页。

| OS 概念 | MemGPT 等价物 |
|---------|-------------|
| 物理 RAM / 主存 | 上下文窗口（有限，快速访问） |
| 虚拟内存 / 页面文件 | 召回记忆（对话历史数据库） |
| 磁盘存储 | 存档记忆（向量数据库，无界） |
| 页面换入/换出 | 通过函数调用在层间移动数据 |
| 内存管理器进程 | LLM 自身（通过工具调用自主管理） |
| 中断/定时器 | 心跳机制（自链式推理） |
| 应用代码 | 系统指令（只读，定义控制流） |

**关键创新**: LLM **自主决定**什么数据换入/换出 — 无需用户干预。

### 4.2 完整的分层记忆架构

上下文窗口被分为**三个连续区域**（"主上下文"）：

#### 系统指令（只读）
- 静态的，始终位于提示顶部
- 描述控制流、记忆层次和函数模式
- 包含关于如何使用每个记忆层的**详细说明**
- 包含 token 限制警告以指导记忆管理决策

#### 核心记忆（工作上下文，固定大小，可写）
- 上下文窗口内的固定大小区域
- 分为**命名的块**（如 `persona`、`human`、`project` 或自定义块）
- 每个块存储小而聚焦的内容
- **始终可见** — 无需检索，它就在提示中
- 每个块有**字符/token 大小限制**
- 块可以动态地**附加和分离**
- 在数据库中以**修订历史**存储

#### FIFO 队列（近期对话）
- 先进先出消息队列，保存近期对话轮次
- 当队列溢出时，旧消息被"换出" — 它们保留在召回存储中但离开上下文窗口

#### 外部存储（上下文外，无界）

**召回记忆（对话历史数据库）**
- 存储所有交互的**完整消息历史**
- 通过大小写不敏感字符串匹配搜索 (`conversation_search`)
- 类似于 OS 交换/页面文件

**存档记忆（长期向量存储）**
- **语义可搜索**的向量数据库用于长期知识
- 存储事实、文档摘要、从核心记忆溢出的知识
- 使用基于嵌入的相似度搜索（余弦距离）
- **不是从上下文溢出自动填充的** — Agent 必须显式调用 `archival_memory_insert`

### 4.3 Agent 自编辑记忆块

这是最独特的特性。Agent 对自己的记忆拥有**完全自主权**：

#### 自编辑机制
1. 系统提示包含**记忆层次的详细描述**和**完整的函数模式**
2. 每次推理时，Agent 首先进行**内部独白**（用户永远看不到的私有推理）
3. 在内部独白中，Agent 推理什么信息值得保留
4. Agent 然后发出记忆编辑函数调用
5. 所有输出都是工具调用 — 甚至向用户发送消息也需要 `send_message()`

#### 记忆工具函数（核心记忆）

| 函数 | 操作 |
|------|------|
| `core_memory_replace(old_text, new_text)` | 替换块中的内容。空 `new_text` 表示删除 |
| `core_memory_append(text)` | 向记忆块追加新文本 |
| `memory_insert`（Letta v2） | 向块中插入内容 |
| `memory_replace`（Letta v2） | 替换块中的内容 |
| `memory_rethink`（Letta v2） | 总结并重写块 — 用于整合 |

### 4.4 完整工具清单（8 个标准工具）

| 函数 | 描述 |
|------|------|
| `send_message` | 向用户发送消息（唯一的响应方式） |
| `pause_heartbeats` | 暂停心跳 |
| `conversation_search` | 搜索先前对话历史（大小写不敏感） |
| `conversation_search_date` | 按日期过滤的对话搜索 |
| `archival_memory_insert` | 在存档记忆中存储新信息 |
| `archival_memory_search` | 存档记忆的语义搜索 |
| `core_memory_append` | 向核心记忆追加 |
| `core_memory_replace` | 替换核心记忆中的内容 |

### 4.5 函数链式调用（多步检索）

Agent 可以**链式调用多个检索**：
- Agent 调用函数时设置 `request_heartbeat=true`
- 这告诉系统在函数完成后立即返回控制给 LLM（而非等待用户输入）
- LLM 获取函数结果，推理，然后可以发出另一个函数调用
- 这支持**迭代分页遍历结果** — Agent 可以对存档存储进行多次调用
- 与固定上下文基线的单次 top-K 检索不同，MemGPT 可以导航大型文档集

### 4.6 记忆整合策略

#### 压缩（总结）
当对话历史对上下文窗口过长时：
- Letta 自动**压缩/总结**旧消息
- 摘要替换 FIFO 队列中的原始消息
- 原始消息保留在召回存储中供后续检索

#### 睡眠时计算（"做梦"）
较新的 Letta 特性：
- Letta 启动**周期性子 Agent** 异步运行
- 这些"做梦"子 Agent 反思近期对话
- 它们决定**保留、合并、整合或驱逐**记忆中的什么内容
- `/remember` 命令可以显式触发这种反思
- 类似于人脑在睡眠期间整合记忆

### 4.7 存储后端

| 存储类型 | 本地开发 | 生产环境 |
|---------|---------|---------|
| 召回/元数据 | **SQLite** | **PostgreSQL** |
| 存档 | **ChromaDB** | **PostgreSQL + pgvector** |

支持的存档后端（通过 `MEMGPT_ARCHIVAL_STORAGE_TYPE` 配置）：
- PostgreSQL（pgvector 扩展）— 生产默认
- ChromaDB — 本地开发默认
- Milvus — 大规模向量搜索
- Qdrant — 向量相似度搜索
- FAISS — Facebook 的相似度搜索库

### 4.8 Agent 循环

```
1. 事件到达（用户消息、系统中断、定时触发）
     ↓
2. 事件解析 → 追加到主上下文中的 FIFO 队列
     ↓
3. LLM 处理器对主上下文进行推理
     ↓
4. LLM 生成内部独白（私有推理，对用户隐藏）
     ↓
5. LLM 输出函数调用：
   - 记忆编辑 (core_memory_replace, core_memory_append)
   - 记忆检索 (conversation_search, archival_memory_search)
   - 记忆写入 (archival_memory_insert)
   - 用户响应 (send_message)
   - 可选 request_heartbeat=true 用于链式调用
     ↓
6. 函数执行器验证并执行调用
   - 结果（包括错误）反馈到主上下文
     ↓
7. 如果 request_heartbeat=true → 返回步骤 3（链式另一个推理）
   如果 send_message → 暂停，等待下一个事件
     ↓
8. 队列管理器将输入和输出写入召回存储
```

---

## 5. 记忆类型分类

2025–2026 年的共识识别出认知科学启发的分类法：

### 5.1 短期/工作记忆（上下文窗口）

- **存储内容**: LLM 的上下文窗口 — 推理期间可用的有限 token 缓冲区
- **实现**: 原始消息历史、系统提示、注入的上下文、工具结果
- **类比**: RAM — 快速、易失、容量有限
- **局限**: 即使 128K–1M token 窗口也遭受**上下文腐烂** — 随着 token 数量增加，注意力稀释

### 5.2 情景记忆（发生了什么？）

- **存储内容**: 特定时间戳的事件、对话、交互、结果
- **实现**: 带元数据的向量数据库（时间戳、用户 ID、采取的行动、结果）
- **用例**: 个人助手、调试会话、需要从过去经验中学习的场景
- **风险**: 情景记忆存在安全风险（偏见强化、隐私泄露）

### 5.3 语义记忆（我知道什么？）

- **存储内容**: 泛化的事实、定义、规则、用户偏好、领域知识 — 与学习时间无关
- **实现**: 知识图谱（实体-关系存储）、结构化关系数据库、带 RAG 检索的向量数据库
- **关键模式**: 随时间推移，频繁访问的情景记忆被**蒸馏**为语义知识 — 事实存活，原始情节被丢弃

### 5.4 程序化记忆（如何做这件事？）

- **存储内容**: 学习到的工作流、常规、行为模式、技能
- **实现**: 编码为提示、Agent 代码、工作流定义、工具序列或微调的模型行为
- **关键收益**: 减少重复思考，使推理能专注于新颖情况

### 5.5 它们如何协同工作

一个准备市场分析的研究助手使用：
- **情景记忆**: "上个月用户喜欢监管风险评估但觉得术语令人反感"
- **语义记忆**: "可再生能源市场估值、关键参与者、监管框架"
- **程序化记忆**: "从市场规模 → 竞争格局 → 风险评估 → 投资建议开始"

---

## 6. 向量数据库对比

| 特性 | Chroma | FAISS | Qdrant | Weaviate | Pinecone |
|------|--------|-------|--------|----------|----------|
| **类型** | 嵌入式库 | 库（非完整 DB） | 完整服务器 | 完整服务器 | 托管云 |
| **设置** | 最简单 (pip install) | 简单 | 中等 (Docker) | 中等 | 最简单 (API key) |
| **速度 (1M 向量, 768d)** | 15ms | 0.5ms GPU / 2ms CPU | 5ms | 8ms | 取决于层级 |
| **QPS** | 65 | 2000 GPU / 500 CPU | 200 | 125 | 按需扩展 |
| **内存 (1M 向量)** | 4.5 GB | 3 GB | 4 GB | 5 GB | 托管 |
| **过滤** | 基础 | 手动（后过滤） | 高级（payload） | 高级（GraphQL） | 元数据过滤 |
| **GPU 支持** | 否 | 是 | 有限 | 否 | 否 |
| **混合搜索** | 否 | 否 | 是 (sparse+dense) | 是 (BM25+vector) | 是 |
| **许可证** | Apache 2.0 | MIT | Apache 2.0 | BSD-3 | 专有 |

### 选择指南

| 场景 | 推荐 |
|------|------|
| 原型/学习 | **Chroma**（零配置） |
| 最大速度 | **FAISS**（GPU，数十亿向量） |
| 生产 RAG | **Qdrant**（最佳全能） |
| 企业/复杂查询 | **Weaviate**（GraphQL，ML 模块） |
| 零运维云 | **Pinecone**（托管，自动扩展） |
| 已用 Postgres | **pgvector**（无新基础设施） |

---

## 7. 图记忆方案

### 7.1 为什么图优于纯向量

平坦向量存储在以下场景失败：
- 实体间关系（组织层级、依赖链）
- 时间事件序列（什么变了，何时，为什么）
- 多实体交互（多跳推理）
- 可解释检索（每个答案通过特定节点/边追溯）

### 7.2 时间知识图谱（2025–2026 突破）

主导方法使用**双时间知识图谱** — 每个事实节点管理两个时间维度：
- `valid_at` — 事实在真实世界中何时变为真
- `transaction_time` — 系统何时记录该事实
- `invalid_at` — 事实何时被取代（失效，而非删除）

### 7.3 主要图框架

| 框架 | 架构 | 优势 | 劣势 |
|------|------|------|------|
| **Zep** | Neo4j 上的时间 KG + 向量/BM25 索引 | 时间推理，长期会话强 | 更重的心智模型 |
| **Graphiti** | Zep 的开源时间图引擎 | 自托管，双时间基底 | 电池较少 |
| **Mem0 Graph** | 写入时实体链接 + 并行实体集合 | 简单 API | 图记忆仅云端 ($249/月) |
| **Letta** | 三层分级记忆，Agent 自管理 | 紧密的模型+记忆集成 | 高设计复杂度 |

### 7.4 图 DB 选项

| 数据库 | 特点 |
|--------|------|
| **Neo4j** | 最广泛采用，成熟的 Cypher，大生态 |
| **FalkorDB** | 为 AI/GraphRAG 打造，稀疏邻接矩阵，亚毫秒遍历 |
| **Kuzu** | 嵌入式图 DB，适合轻量本地使用 |

---

## 8. 记忆整合策略

### 8.1 四杠杆框架（2026 年最佳实践模型）

来源: [Hindsight/Vectorize, 2026 年 5 月](https://hindsight.vectorize.io/blog/2026/05/21/agent-memory-consolidation)

#### 杠杆 1: 重要性（什么成为记忆？）

两种主导模式：

| 模式 | 方法 | 优势 | 劣势 |
|------|------|------|------|
| **LLM 评分** | 对每个观察评 1–10 分重要性 | 灵活 | 每次写入需模型调用；评分跨模型版本漂移 |
| **事实提取** | 将对话分解为原子事实；只存储存活提取的内容 | 对话填充、问候、噪声永远不会成为记忆 | 激进过滤损失召回 |

#### 杠杆 2: 合并（解决重复/矛盾事实）

- **实体解析**: 将提及 ("Ben"、"用户"、"你") 链接到规范实体 ID。**必须在写入时**发生
- **事实去重**: "Ben 在 Vectorize 工作" + "用户受雇于 Vectorize" → 一个事实
- **冲突处理策略**:

| 策略 | 描述 | 适用场景 |
|------|------|---------|
| **最近优先** | 新事实取代旧事实 | 最可靠的默认值 |
| **来源优先** | 可信来源覆盖不可信来源 | 需要信任模型 |
| **置信度优先** | 最高置信度分数获胜 | 需要校准 |

**最佳实践**: 最近优先 + 显式**失效**（标记旧事实为失效而非删除）— 旧状态可恢复用于审计，当前状态明确用于检索。

#### 杠杆 3: 衰减（随时间的置信度）

三种衰减形状：

| 形状 | 描述 | 适用 |
|------|------|------|
| **线性衰减** | 置信度按固定量/时间单位下降 | 简单推理 |
| **指数衰减**（推荐默认） | 置信度按时间尺度减半。匹配艾宾浩斯遗忘曲线 | 用户偏好 |
| **阶梯函数衰减** | 置信度保持平稳直到外部事件触发失效 | 稳定属性（姓名、公司） |

**关键洞察**: 不是所有事实以相同方式老化。

#### 杠杆 4: 驱逐（记忆何时离开）

- **分数驱逐**: 每个记忆按最近性 + 重要性 + 相关性评分。达到容量时驱逐最低分
- **访问频率驱逐**: 最少最近使用的记忆被归档或删除
- **语义驱逐**: 情景记忆**蒸馏**为语义知识 — 事实被提升，原始情节退出

### 8.2 各框架的整合方法

| 框架 | 整合方法 |
|------|---------|
| **Mem0** | 写入时 LLM 门控事实提取。去重 + 矛盾时覆盖。推荐异步模式 |
| **Zep** | 双时间失效。通过小模型调用进行实体提取。图作为真实来源 |
| **Letta** | Agent 通过工具调用自管理层提升。核心记忆 vs 召回 vs 存档 |
| **Hermes** | Agent 驱动的手工整理。固定预算强制高信息密度 |

---

## 9. 混合检索方案

### 9.1 为什么需要混合

在一项覆盖约 25,000 个 QA 对（4 个数据集）的评估中，**基于词项 (BM25) + 密集 (向量) 检索优于任一单独方法**。

### 9.2 混合检索架构

```
查询 → [语义搜索（向量相似度）]
     → [关键词搜索（BM25 / 全文）]
     → [图遍历（实体关系，多跳）]
     → [融合/重排（交叉编码器、RRF、加权分数）]
     → Top-K 结果 → 上下文注入
```

### 9.3 融合策略

| 策略 | 描述 | 成本 |
|------|------|------|
| **倒数排名融合 (RRF)** | 组合来自多个检索器的排名列表 | 低 |
| **交叉编码器重排** | 用专用模型重新评分 top-N 候选 | 高 |
| **加权评分** | 组合相似度分数 + 时间权重 + 重要性分数 + 图距离分数 | 中 |

### 9.4 纯向量足够的场景

- 简单 FAQ 检索
- 单实体、单跳问题
- 原型和 MVP
- 延迟预算 <10ms 且无法承受图遍历

---

## 10. 记忆注入与上下文格式化

### 10.1 模式 1: 结构化 XML/Markdown 节（系统提示中）

```xml
<user_profile>
  Name: Alex Chen
  Preferred language: Python
  Role: Senior Backend Engineer
  Last active: 2026-06-18
</user_profile>

<relevant_memories>
  - User migrated from Postgres to MySQL on 2026-03-15
  - User prefers async/await patterns over callbacks
  - User's team uses Railway for deployment
</relevant_memories>
```

### 10.2 模式 2: 事实列表注入（Mem0 模式）

```
## User Facts
- Prefers Python for backend development
- Deployed to Railway last week
- Migrated database from Postgres to MySQL (March 2026)
- Works on team of 5 engineers
```

### 10.3 模式 3: 时间上下文（Zep 模式）

事实标注有效期：
```
[2026-01-15 → present] Uses MySQL for primary database
[2025-06-01 → 2026-03-15] Used Postgres for primary database (SUPERSEDED)
```

### 10.4 模式 4: 情景摘要

```
## Recent Session Summary (June 17, 2026)
User debugged a memory leak in the notification service.
Root cause: unclosed WebSocket connections in the event handler.
Resolution: Added connection cleanup in the finally block.
User was frustrated with the previous rate-limiting approach.
```

### 10.5 系统提示设计最佳实践（Anthropic）

- 使用**清晰、直接的语言**在"正确的高度"
- 使用 XML 标签或 Markdown 标题**组织为不同的节**
- **追求完全概述预期行为的最小信息集**
- 从最小化开始，用最佳模型测试，然后根据发现的失败模式添加指令
- **上下文腐烂是真实的**: 随着 token 数量增加，模型的召回准确率**下降**

---

## 11. Token 预算管理

### 11.1 预算分配框架

```
总上下文窗口预算
├── 系统提示（指令、人格、规则）       → ~10-15%
├── 工具定义（函数模式）              → ~10-20%
├── 注入记忆（用户画像、事实、历史）   → ~15-25%
├── 检索上下文（RAG 结果）            → ~20-30%
├── 当前对话（近期轮次）              → ~20-30%
└── 输出缓冲（响应空间）              → ~10-15%
```

### 11.2 实用 Token 预算技术

| 技术 | 描述 | 适用场景 |
|------|------|---------|
| **截断/滑动窗口** | 只保留最近 N 轮 | 简单场景 |
| **总结/压缩** | 将旧对话历史压缩为摘要块 | 长期对话 |
| **选择性检索 (RAG)** | 动态检索每个查询最相关的记忆 | **主导模式** |
| **分层记忆 (Letta)** | 核心记忆（始终在上下文）+ 召回 + 存档 | 复杂 Agent |
| **重要性加权注入** | 对每个记忆评分，只注入高于阈值的 | 精细控制 |
| **自适应上下文大小** | 根据查询复杂度动态调整 | 成本优化 |

### 11.3 各系统的 Token 管理对比

| 维度 | Hermes | Mem0 | Letta |
|------|--------|------|-------|
| 预算方法 | 固定字符限制 | 动态提取 + top-K 检索 | Agent 自主管理 |
| 可预测性 | 精确（每会话 ~1,300 token） | 中等（~7K token/对话） | 低（取决于 Agent 决策） |
| 遗忘风险 | 低（冻结快照，始终可见） | 中（基于相关性的隐式遗忘） | 中（Agent 可能忘记检索） |
| 信息质量 | Agent 整理，高密度 | LLM 提取的原子事实 | Agent 策展的块 |

---

## 12. 三大系统对比总结

| 维度 | Hermes Agent | Mem0 | Letta (MemGPT) |
|------|-------------|------|----------------|
| **设计哲学** | 固定预算 + 冻结快照 | 提取时蒸馏 | OS 虚拟内存 |
| **记忆类型** | 5 层（持久化 + 用户画像 + 会话搜索 + 插件 + 技能） | 向量事实 + 图实体关系 | 3 层（核心 + 召回 + 存档） |
| **存储后端** | Markdown 文件 + SQLite FTS5 + 插件后端 | 15+ 向量 DB + 图 DB（云端） | SQLite/PostgreSQL + ChromaDB/pgvector/Milvus/Qdrant |
| **检索机制** | FTS5 全文搜索 + 插件语义搜索 | 语义 + BM25 + 实体链接（三路融合） | Agent 控制的函数调用（语义搜索 + 字符串匹配） |
| **记忆整合** | Agent 驱动的手工整理（预算溢出触发） | LLM 门控 ADD/UPDATE/DELETE 或 ADD-only + 实体链接 | Agent 自管理 + 睡眠时计算（做梦） |
| **上下文注入** | 冻结快照在系统提示 + 外部记忆在用户消息 | 结构化模板（时间戳 + 事实列表） | 核心记忆块在系统提示 + 检索结果追加 |
| **Token 预算** | 固定 ~1,300 token（字符限制） | ~7K token/对话（动态） | Agent 感知（动态，工具调用管理） |
| **Agent 自主权** | 有限（工具触发记忆写入） | 无（系统自动提取/整合） | 完全（Agent 决定一切） |
| **安全** | 三级威胁扫描 + 漂移检测 | 无特殊记忆安全 | 工具调用验证 |
| **可扩展性** | 单 Agent（一个外部提供者） | 多用户、多 Agent | 多 Agent 共享记忆块 |
| **最适场景** | 个人助手、CLI Agent | 快速原型、事实密集工作负载 | 长期有状态 Agent、透明记忆行为 |

---

## 13. 最佳实践与反模式

### 13.1 最佳实践

1. **分层记忆**: 至少区分"始终在上下文"的核心记忆和"按需检索"的长期记忆
2. **混合检索**: 组合语义搜索 + 关键词搜索 + 图遍历（如适用）
3. **写入时整合**: 在记忆写入时进行事实提取和去重，而非等待查询时
4. **时间感知**: 使用双时间模型（valid_at + transaction_time）处理事实变化
5. **异步写入**: 记忆提取和存储应异步运行，避免用户可见延迟
6. **冻结快照**: 如果在系统提示中注入记忆，在会话期间冻结它们以保护 KV Cache
7. **安全扫描**: 对记忆写入进行威胁扫描，防止 prompt 注入持久化
8. **预算意识**: 将上下文窗口视为有限资源，有递减边际收益

### 13.2 反模式

| 反模式 | 问题 | 修复 |
|--------|------|------|
| **填充一切** | 注意力稀释、高成本、上下文腐烂 | 选择性检索 + 重要性过滤 |
| **无整合** | 索引无限增长，检索精度下降 | 实施四杠杆整合策略 |
| **过度去重** | 丢失细微差别、讽刺、条件性扁平化 | 在原始情节日志上分层事实存储 |
| **忽略时间漂移** | Agent 自信地断言过时事实 | 双时间失效，最近优先 |
| **无重要性过滤** | 填充/问候成为可检索记忆 | 事实提取作为重要性门控 |
| **阻塞式记忆写入** | 每轮用户可见延迟 | 异步记忆写入 |
| **单一存储一切** | 无法同时处理语义和关系查询 | 混合存储: 向量 + 图 + KV |
| **硬编码检索顺序** | 所有查询类型使用相同检索策略 | 基于查询分类的动态检索路由 |
| **视上下文窗口为无限** | 模型随更长上下文失去准确性 | 视为有限资源，有递减收益 |
| **无驱逐策略** | 记忆存储无界增长，成本爆炸 | 分数驱逐 + 存档层 |

---

## 14. 对 Sage 项目的启示

基于以上研究，Sage 项目的记忆系统设计可以考虑：

### 14.1 推荐架构

```
Sage 记忆架构
├── 核心记忆（始终在上下文）
│   ├── 用户画像（偏好、工作风格）
│   └── 当前任务状态
├── 情景记忆（按需检索）
│   ├── 对话历史 → PostgreSQL + FTS5
│   └── 交互事件 → 向量数据库
├── 语义记忆（按需检索）
│   ├── 实体-关系图 → 知识图谱或向量集合
│   └── 领域知识 → 向量数据库
└── 程序化记忆
    └── 技能/工作流 → Markdown 文件或数据库
```

### 14.2 推荐技术选型

| 组件 | 推荐 | 理由 |
|------|------|------|
| 向量 DB | **pgvector**（如已用 PostgreSQL）或 **Qdrant** | 最小基础设施或最佳全能 |
| 全文搜索 | **PostgreSQL FTS** 或 **SQLite FTS5** | 已有基础设施 |
| 图存储 | 先用**实体链接**（Mem0 v3 模式），需要时升级到 Neo4j | 渐进式复杂度 |
| 嵌入模型 | **text-embedding-3-small** 或 Ollama 本地模型 | 成本/质量平衡 |
| 整合策略 | **事实提取作为重要性门控** + **最近优先冲突解决** | 经过验证的模式 |

### 14.3 关键设计决策

1. **记忆预算**: 借鉴 Hermes 的固定预算理念，为核心记忆设置字符/token 上限
2. **冻结快照**: 如果在系统提示中注入记忆，在会话期间冻结
3. **异步提取**: 借鉴 Mem0，记忆提取和整合异步运行
4. **Agent 自主权**: 借鉴 Letta，让 Agent 通过工具调用决定何时检索/存储
5. **安全**: 借鉴 Hermes，对记忆写入进行威胁扫描
6. **时间感知**: 借鉴 Zep，使用双时间模型处理事实变化

### 14.4 渐进式实施路径

| 阶段 | 内容 | 复杂度 |
|------|------|--------|
| **阶段 1** | 基础核心记忆（用户画像 + 任务状态）→ Markdown 或 DB 字段 | 低 |
| **阶段 2** | 对话历史搜索 → FTS5 / PostgreSQL FTS | 低 |
| **阶段 3** | 语义记忆 → 向量 DB + 事实提取 | 中 |
| **阶段 4** | 记忆整合 → 去重 + 冲突解决 | 中 |
| **阶段 5** | 图增强 → 实体链接或知识图谱 | 高 |
| **阶段 6** | 睡眠时计算 → 异步反思子 Agent | 高 |

---

## 参考来源

### Hermes Agent
- [NousResearch/hermes-agent GitHub](https://github.com/nousresearch/hermes-agent)
- [Hermes Agent 官方文档](https://hermes-agent.nousresearch.com/docs/)
- [Memory Providers 文档](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/memory-providers.md)
- [PR #3958: MemoryProvider Protocol](https://github.com/NousResearch/hermes-agent/pull/3958)

### Mem0
- [Mem0 论文 — arXiv:2504.19413](https://arxiv.org/abs/2504.19413) (ECAI 2025)
- [Mem0 官方文档](https://docs.mem0.ai/)
- [Mem0 Graph Memory 文档](https://docs.mem0.ai/platform/features/graph-memory)
- [Dwarves Memo — Mem0 技术拆解](https://memo.d.foundation/breakdown/mem0)
- [FalkorDB — Graph Memory for LLM Agents](https://www.falkordb.com/blog/graph-memory-llm-agents-mem0-falkordb/)

### Letta (MemGPT)
- [原始论文 — arXiv:2310.08560](https://arxiv.org/abs/2310.08560)
- [Letta 官方文档](https://docs.letta.com/)
- [Terse Systems — Adding Memory to LLMs with Letta](https://tersesystems.com/blog/2025/02/14/adding-memory-to-llms-with-letta/)
- [Leonie Monigatti — MemGPT 论文解读](https://www.leoniemonigatti.com/papers/memgpt.html)
- [Agent Memory Techniques Notebook](https://github.com/NirDiamant/Agent_Memory_Techniques/blob/main/all_techniques/26_letta_memgpt_patterns/letta_memgpt_patterns.ipynb)

### 通用模式
- [SparkCo — AI Agent Memory Comparative Guide](https://sparkco.ai/blog/ai-agent-memory-in-2026-comparing-rag-vector-stores-and-graph-based-approaches)
- [Hindsight/Vectorize — The Consolidation Problem](https://hindsight.vectorize.io/blog/2026/05/21/agent-memory-consolidation)
- [Anthropic — Effective Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [LangChain — Context Engineering for Agents](https://www.langchain.com/blog/context-engineering-for-agents)
- [Redis — Context Window Management Guide](https://redis.io/blog/context-window-management-llm-apps-developer-guide/)
- [Redis — Long-Term Memory Architectures](https://redis.io/blog/long-term-memory-architectures/)
- [FalkorDB — Graph Database AI Agents](https://www.falkordb.com/blog/graph-database-ai-agents/)
- [Mem0 — State of AI Agent Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026)
- [Towards AI — The State of AI Agent Memory in 2026](https://pub.towardsai.net/the-state-of-ai-agent-memory-in-2026-what-the-research-actually-shows-0b77063c2c2b)
