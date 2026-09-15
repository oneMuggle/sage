# 记忆提取异步化 — Design Spec

- **Date:** 2026-08-02
- **Branch:** `feat/async-memory-extraction` (基于 `origin/main`)
- **Status:** Draft,待用户 review
- **Author:** Claude (brainstorming with user)

## 1. 背景与目标

### 1.1 问题

记忆事实提取（`extract_and_store_memory` → `MemoryExtractor.extract`，包含一次 LLM 调用）目前在两条路径上都是 **inline await**，阻塞聊天响应完成：

| 路径 | 位置 | 现状 |
|---|---|---|
| hex `ChatService.run_turn` | `_run_turn_inner` 第 7 步 | `await extract_and_store_memory(...)` — LLM 提取完成后响应才返回 |
| legacy `/chat/stream` | `_extract_legacy_chat_memory`（legacy_routes.py:1663） | `await extract_and_store_memory(...)` — 提取阻塞流式请求收尾（session update / 标题生成 / DONE 推送之前） |

`extract_and_store_memory` 内部已有 best-effort 语义（绝不外抛、只 warning），但 **await 本身**把一次慢 LLM 调用放到了用户等待路径上。

> 注：39 章 §4 原记录"legacy 已非阻塞，hex 收益有限，留待 API_MODE=hex 启用后"——即此项曾被有意推迟。本次按用户指示"按文档原顺序全做"将其纳入，且 legacy 路径实为 inline await（与文档描述略有出入），异步化对两条路径都成立。

### 1.2 目标

1. 记忆提取脱离聊天响应关键路径：hex `run_turn` 与 legacy 流式收尾**不等待** LLM 提取。
2. 两条路径共用同一个异步队列，统一调度 / 顺序 / 背压 / 可观测性。
3. 复用现有 `extract_and_store_memory` 统一写入语义，**不重写提取逻辑**。

### 1.3 非目标 (YAGNI)

- ❌ title 自动生成异步化（独立 LLM 调用，本期不动）
- ❌ working memory compress 异步化（与提取无数据依赖，本期不动）
- ❌ 提取批处理 / 多轮聚合 / 降级重试
- ❌ 引入 MetricPort 依赖（队列在 legacy/hex 装配路径之外，用 logger + 计数器即可）
- ❌ web 模式兼容（项目 Electron-only）
- ❌ release/win7 同步（本期只在 main，后续按需 cherry-pick）

## 2. 用户故事

- **US-1**: 作为 Sage 用户,一次慢速 LLM 提取（记忆事实）不应拖延我的聊天响应——消息完成后界面应立即可交互。
- **US-2**: 作为开发者,即使记忆提取持续失败,聊天功能不受任何影响（best-effort 语义保持,只在日志中可见）。

## 3. 架构

### 3.1 新增模块 `backend/memory/async_extractor.py`

```
MemoryExtractionQueue
├── submit(request: ExtractionRequest)   # 非阻塞入队，返回立即
├── _worker()                            # 单 worker 协程，消费队列
│   └── await extract_and_store_memory(...)   # 复用现有统一写入路径
├── async drain(timeout=5.0)             # 等队列空 + worker 空闲（测试/关机）
├── 计数器：pending / completed / failed / skipped
└── 单例：get_memory_extraction_queue() / reset_memory_extraction_queue()
```

- **`ExtractionRequest` dataclass**：`(memory_port, extractor, user_text, assistant_text, session_id, enabled)` — 与 `extract_and_store_memory` 参数同构，worker 原样透传。
- **单 worker 串行**：顺序保证 + 天然背压（LLM 提取本就慢，并发只会叠加 LLM 负载；与 `file_mutation_queue.py` 的"队列 + 单 worker"先例一致）。
- 保持六边形纯净：队列不依赖 FastAPI（`BackgroundTasks` 方案已评估否决）。

### 3.2 数据流

```
Chat 响应路径                             后台
─────────────                           ─────
hex run_turn step 7  ─┐
                      ├─► queue.submit(ExtractionRequest) ─► asyncio.Queue ─► _worker ─► extract_and_store_memory ─► MemoryAdapter.store / store_profile
legacy 1663           ─┘
   (保留 autoMemory 开关检查 + adapter/extractor 构建，仅末尾 submit)
```

### 3.3 接入点改造

| 路径 | 现状 | 改造后 |
|---|---|---|
| hex `_run_turn_inner` step 7 | `await extract_and_store_memory(...)` | `get_memory_extraction_queue().submit(ExtractionRequest(...))`，**不 await** |
| legacy `_extract_legacy_chat_memory` | `await extract_and_store_memory(...)` | 保留 autoMemory 开关检查 + `MemoryAdapter`/`MemoryExtractor` 构建（廉价），末尾 `queue.submit(...)` **不 await** |

**span 属性调整**：hex 原 `span.set_attribute("memory.stored_facts", stored_facts)` 移除（worker 无调用方 span），改为 worker 内 `logger.debug` 记录实际写入条数。`run_turn` 内提取相关的 span 属性删除，不破坏其它 span 属性。

## 4. 错误处理（三层防护）

1. **worker 外圈**：`extract_and_store_memory` 内置 best-effort try/except（绝不外抛）；worker 循环**再包一层** try/except — 理论外异常记 `logger.warning` + `failed += 1`，**继续处理下一项**，worker 永不因单条失败退出。
2. **提交端前置过滤**：`submit` 时 `memory_port is None` 或 `enabled=False` 直接丢弃计 `skipped`（不入队）— 与 `extract_and_store_memory` 开头 guard 同语义，提前到入队端省 worker 空转。
3. **可观测性**：模块级计数器 `pending / completed / failed / skipped`；failed 记 `logger.warning` 含 skill/session 上下文（如有）。

## 5. 生命周期

| 事件 | 行为 |
|---|---|
| 应用启动 | main.py lifespan 里 `asyncio.create_task(queue._worker())`，task 引用存 `app.state` 防 GC |
| 重复启动 | 队列内 `_is_running` 标志防双 worker |
| 优雅关闭 | FastAPI shutdown 时 `await queue.drain(timeout=5.0)` 排空在途任务；超时未完成直接丢弃（best-effort 记忆不值得阻塞退出） |
| 测试隔离 | `reset_memory_extraction_queue()` 重置单例 + worker 状态（沿用 `get_usage_store` 模式） |

## 6. 测试

### 6.1 新增单测 `backend/tests/unit/test_async_extractor.py`

| 用例 | 断言 |
|---|---|
| submit 非阻塞 | 返回后 worker 未完成（异步语义） |
| worker 消费 | 调 `extract_and_store_memory`（mock 断言 store 被调） |
| 顺序保持 | 多 submit 按序消费 |
| 单 worker 串行 | 并发 submit 不并发执行 |
| 单条失败不杀 worker | 后续项继续，failed 计数 +1 |
| `drain()` | 等待完成；超时返回不抛 |
| 前置过滤 | `memory_port None` / `enabled=False` → skipped 不入队 |

### 6.2 现有测试适配（主要破坏面）

| 文件 | 适配 |
|---|---|
| `backend/tests/unit/test_chat_service.py` | hex 路径原 await 提取后断言 `store` 被调 / span `stored_facts` 属性 → 改为断言 `queue.submit` 被调用（或 submit 后 `drain()` 再断言效果）；span 属性移除 |
| `backend/tests/integration/test_legacy_memory_extraction.py` | legacy 路径原 await → 改为断言 submit（或 drain 后断言） |

`extract_and_store_memory` 自身逻辑单测**保持不动**（worker 透传，单测仍直接测它）。

### 6.3 验证命令

```bash
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest \
  backend/tests/unit/test_async_extractor.py \
  backend/tests/unit/test_chat_service.py \
  backend/tests/integration/test_legacy_memory_extraction.py
```

## 7. 风险与限制

| 风险 | 应对 |
|---|---|
| 后台 worker 异常退出导致后续提取全挂 | worker 外层 try/except + `_is_running` 标志；单条失败不退出；监控计数器 |
| 队列堆积（提取慢于产出） | 单 worker 天然背压，队列无界即内存增长——本轮接受（提取是低频后台任务，量级小），如需可加 `maxsize` 后续迭代 |
| shutdown 丢失在途提取 | `drain(timeout=5)` 尽力排空；记忆是 best-effort 辅助数据，丢失可接受 |
| 测试时序不稳 | 测试统一走 `drain()` 等待确定性结果，不依赖 sleep |

## 8. 验收

- [ ] `pytest backend/tests/unit/test_async_extractor.py` 全绿（新增单测）
- [ ] `pytest backend/tests/unit/test_chat_service.py backend/tests/integration/test_legacy_memory_extraction.py` 适配后全绿
- [ ] 全量 `pytest backend/tests` 无回归
- [ ] ruff 全绿
- [ ] 手动冒烟：真实对话后 chat 响应立即返回，记忆在后台落库（日志可见 completed 计数）
