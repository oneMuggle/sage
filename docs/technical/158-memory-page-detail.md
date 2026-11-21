# 记忆页面详情化与结构化标题

> 2026-11-17 · 分支 `feat/memory-page-detail` · 功能已并入本文档（原 `docs/plans/` 计划文件按规范删除）

## 背景

记忆库页面此前只有"标题"和 80 字预览——标题实为 `content` 前 30 字硬截断，
长记忆（尤其会话摘要）没有入口查看全文，也无法编辑。对标 ChatGPT「管理记忆」、
Gemini「已保存的信息」，本功能补齐三件事：**全文详情、结构化标题、单条编辑**。

## M1 前端详情体验

- `src/widgets/memory/memoryTitle.ts`（新增）
  - `deriveMemoryTitle` / `resolveMemoryTitle` / `deriveMemoryPreview`：
    首个非空行 → 去 markdown/列表前缀 → 压缩空白 → 60 字截断（标题）/
    160 字截断（预览）。优先使用后端下发的 `title`。
- `src/widgets/memory/MemoryItemCard.tsx`（新增，从 `MemoryBrowser.tsx` 拆出）
  - 普通模式点击卡片 / 「详情」按钮切换展开，全文以 `whitespace-pre-wrap` 展示；
  - 选择模式点击仍为勾选，与展开互斥；
  - `role="button"` + `aria-expanded` + Enter/Space 键盘操作；
  - 折叠态显示正文真实字数；
  - 展开态支持内联编辑（标题 + 内容 textarea → 保存/取消）。
- `MemoryBrowser.tsx` 只保留列表/筛选/统计逻辑（文件从 1225 行降至 ~740 行）。

## M2 结构化标题（后端）

- 迁移（幂等 `ALTER TABLE`）：`memories_episodic.title`、`memories_semantic.title`
  （`backend/data/database.py` 与 `semantic.py` 自建表路径双覆盖）。
- `backend/memory/title_text.py`：`derive_title(content)` 确定性推导，
  与前端 `memoryTitle.ts` 同一套规则；写入缺省时生成，读取时对存量 NULL 兜底。
- 写入链路：`memory_port.store(..., title=)` → `MemoryAdapter.store` →
  `MemoryManager.memorize/memorize_with_conflict_check` → `episodic/semantic.save`。
- LLM 提取：`EXTRACTION_PROMPT` 新增 `title` 输出字段（≤20 字，随同一次提取
  调用产出，无额外成本）；解析失败/缺失时 `derive_title` 兜底；
  关键词降级路径同样生成 title。
- 手动保存：`MemorySaveRequest.title` 可选；`NewMemoryModal` 增加可选标题输入；
  `memoryApi.saveMemory` 透传。
- 读取兜底：`_enrich_memory_records` / `_enrich_working_records` /
  `_enrich_summary_records` 为缺失 title 的行补 `derive_title`，旧数据无需回填任务。

## M3 单条记忆编辑

- 端点：`PUT /memory/{memory_id}`（`backend/api/legacy_memory_update_routes.py`，
  独立模块保持 `legacy_memory_routes.py` 在 800 行架构红线内）。
  - Body：`{content?, title?, tags?, importance?}`，只更新显式传入字段；
  - episodic 优先，未命中落 semantic；不存在/working/摘要行 → 404；
  - 语义层无 `importance` 列：显式传 → 422（不做静默忽略）；
  - 空 payload → 422。
- 存储层 `EpisodicMemory.update` / `SemanticMemory.update`：
  - `content` 变更 → summary 重算、title 按新内容重推（显式 title 优先）、
    标签未显式给定时跟随新内容重推；
  - 主表更新后重建 FTS 行并删除旧向量（检索层按需重嵌入），
    避免全文/语义检索继续命中过期内容。
- 前端：`memoryApi.updateMemory` + Electron IPC `update_memory`（PUT）；
  更新成功后用返回记录局部替换列表项（不整页刷新）。

## 测试

| 层 | 文件 |
|---|---|
| 前端工具 | `src/widgets/memory/__tests__/memoryTitle.test.ts` |
| 前端卡片 | `src/widgets/memory/__tests__/MemoryItemCard.test.tsx` |
| 后端推导 | `backend/tests/unit/test_memory_title.py` |
| 后端存储 | `backend/tests/unit/test_memory_update_store.py` |
| 后端端点 | `backend/tests/api/test_memory_update.py` |

## 陷阱与注意事项

- `MemoryBrowser.test.tsx` 等既有测试依赖卡片内 title/正文同名文本，
  断言多元素匹配时用 `getAllByText`/`findAllByText`。
- win7（py38 + pydantic v1）：新增模型沿用 `typing.List/Optional` 与
  `# ruff: noqa` 兼容注释；迁移 SQL 全部幂等。
- 架构棘轮：本次按协议上调了 7 个既有基线文件条目；`MemoryBrowser.tsx`
  基线下调留待专门的 `--tighten` PR。
