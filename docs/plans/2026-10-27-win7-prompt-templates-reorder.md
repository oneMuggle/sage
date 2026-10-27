# Win7：补齐 Prompt 模板拖拽排序后端端点

- 日期：2026-10-27
- 基线：`release/win7`（变更时 tip 见 PR）
- 相关：R42 拖拽排序、`#857`（静默丢失 13 个 IPC 命令）

## 现象

设置 → Prompt 模板页的**拖拽排序在 win7 上无效**：拖动后顺序会自己弹回去，没有任何报错。

## 归因

沿着完整调用链逐段核对，缺失的只有最后一环：

| 环节 | 文件 | win7 现状 |
|---|---|---|
| 前端 UI（R42 拖拽） | `src/pages/settings/PromptTemplatesTab.tsx` | **有**，与 main 完全相同 |
| 前端 API | `src/shared/api/promptApi.ts` → `reorder()` | **有**，`invoke('prompts_reorder', ...)` |
| Electron IPC | `electron/commandRoutes/prompts.ts` → `prompts_reorder` | **有**，`PUT /api/v1/prompts/templates/reorder` |
| 后端端点 | `backend/api/prompt_routes.py` | **缺失** |

于是：

```
拖拽 -> 前端乐观更新 -> PUT /templates/reorder -> 404
     -> catch {} -> await load() -> 服务端仍按 updated_at 降序 -> 顺序还原
```

不是崩溃，是**静默回滚**，所以一直没被发现，只在测试里表现为 2 个用例红。

后端原 docstring 写着：

> win7 行为基线：main 侧为存储序 + reorder 端点（R42 拖拽排序），
> 但 win7 前端无拖拽排序 UI，因此保持 updated_at 排序，不引入 reorder 端点。

这个前提**已经不成立** —— 前端 UI 后来同步进来了，但后端没有跟着补。原来的
`test_list_sorts_by_updated_at_desc` 锁定的正是这套降级行为，也就一并过时了。

## 决策

按 main 版收敛，而不是另造一套 win7 专属语义（例如在 reorder 时改写 `updated_at`）。
理由：前端与 Electron 两侧已经和 main 完全一致，后端对齐后三者天然自洽；另造语义会让
win7 与 main 的分歧更大，且 `updated_at` 会失去「更新时间」的本意。

## 改动

`backend/api/prompt_routes.py`（对齐 main）：

1. `list_templates` 由 `updated_at` 降序改回**存储顺序** —— 否则拖拽结果无法在刷新后保持。
2. 新增 `ReorderIn`（`ordered_ids: List[str]`）与 `PUT /templates/reorder`：
   - 按 `ordered_ids` 顺序重排；
   - `ordered_ids` 里未出现的模板按原序**追加到尾部**（防调用方漏传导致数据丢失）；
   - 未知 id 忽略。
3. 路由声明位置在 `/templates/{template_id}` **之前**。这点是必须的：
   FastAPI 按声明顺序匹配，若 `{template_id}` 在前，`PUT /templates/reorder`
   会被当成 `template_id="reorder"` 吃掉。

`backend/tests/unit/api/test_prompt_routes.py`（对齐 main）：

- 新增 `test_reorder_and_append_missing`、`test_reorder_extra_ids_ignored`；
- 移除 `test_list_sorts_by_updated_at_desc`（其前提已消失）。

## 验证

```
改前（win7 版代码 + win7 版测试）      17 passed
改后（main 版代码 + main 版测试）
  py3.11                             18 passed
  py3.8（真实 sage-backend-py38）      18 passed
```

路由表烟囱（`import backend.main` 后枚举）：

```
改前  /api/v1/prompts/templates            GET / POST
      /api/v1/prompts/templates/{id}       PUT / DELETE
      ...（无 reorder）

改后  /api/v1/prompts/templates            GET / POST
      /api/v1/prompts/templates/reorder    PUT      <- 新增，且排在 {id} 之前
      /api/v1/prompts/templates/{id}       PUT / DELETE
```

py3.8 通道同时验证了 `Field(min_length=1)` 在 pydantic v1.10 下不会报错（v1 对 `List`
的 `min_length` 不施加约束，但不影响正确性 —— 前端始终传全量 id）。

## 前端无回归

`PromptTemplatesTab.test.tsx` 等三个前端测试不断言列表顺序，只用到 `updated_at` 字段本身，
改后端排序不影响它们。
