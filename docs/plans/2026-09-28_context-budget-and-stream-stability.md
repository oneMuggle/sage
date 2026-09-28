# 上下文预算体系 + 流式滚动稳定性（参考 ZCode）

> 日期：2026-09-28
> 状态：待实施
> 分支：`feat/context-budget-and-stream-stability`
> 参考：ZCode v3.14.0 `core/src/compact/*`、`apps/zcode-cli/packages/ui` 滚动层

---

## 一、背景与目标

### 1.1 为什么要做

对比 ZCode 后，Sage 在**上下文预算**和**流式滚动**两处存在明确缺口：

**上下文**：长对话跑到中后段，`run_loop` 的消息历史只增不减。现有防线只有
`first_aid_compact`（`backend/core/legacy/context_first_aid.py:116`）这一层**机械截断**，
缺少 ZCode 的分层治理。关键缺失项：

| ZCode 机制 | Sage 现状 |
|---|---|
| 双层压缩（microcompact 清旧工具结果 / auto-compact 调 LLM 摘要） | 仅单层机械截断 |
| 省太少不动手（`MIN_TOKEN_SAVINGS`） | 无，每次触发都改写历史 → 抖动 |
| 双约束阈值 `min(budget×0.9, budget−2000)` | 单阈值 `DEFAULT_RUN_CTX_BUDGET_TOKENS=100_000` |
| 阈值先扣 output 预留（context window 为 input+output 共享） | 固定 100k 常量，与实际模型窗口脱钩 |
| 熔断（连续失败 N 次停）+ rapid-refill 检测 | 溢出路径有 `_MAX_FIRST_AID_ATTEMPTS=2`；**预防路径无熔断、无回填检测** |
| 清内容保哨兵串，tool_call/tool_result 配对不断 | 保头尾截断到 400 字符（语义不同） |
| 工具级输出封顶 | 已有 32KB/条 + 256KB/run，可调 |

**流式滚动**：基础比预期好——「用户上滑不打断」已有（`Chat.tsx:210` `wasAtBottomRef`
+ 48px 阈值 + 跳到最新按钮）。真正的问题是
`Chat.tsx:229-252` 每个 delta 都**同步**写 `scrollTop = scrollHeight`，
在高频 token 流入下与用户手势竞争，产生可见抖动。

### 1.2 目标

| 目标 | 验收标准 |
|---|---|
| 分层压缩 | 预防路径走 microcompact → first_aid → ContextCompactor 三级；触发前校验节省量足够 |
| 防死循环 | 预防路径连续失败熔断；压缩后立即回满触发 rapid-refill 告警 |
| 预算对齐模型 | 阈值从「固定常量」改为「模型有效窗口 × 比率」，扣 output 预留 |
| 工具结果上限 | 单条 32KB → 100KB，run 级预算相应上调 |
| 滚动稳定 | delta 高频下无抖动；用户上滑不被抢；`Chat.auto-scroll.test.tsx` 守门通过 |
| 覆盖率口径 | 补 `coverage.exclude` + fakeStream fixture，滚动改造不误伤棘轮门禁 |

### 1.3 非目标（本期明确不做）

- **真虚拟化**：`MessageList.tsx:79-110` 的 `WINDOW_STEP=60` 伪虚拟化换
  `@tanstack/react-virtual` + 行高 LRU cache。单独开 PR（理由见 §5.1）。
- **覆盖率提到 70%**：实测 statements 仅 61.81，门禁 60/79/65/60 是刻意留 2pt
  余量的棘轮。提到 70 需新增约 8pt 真实测试量，滚动改造引入的新分支反而会拉低。
  本期只补 exclude 与测试基建。
- **显式 Turn 状态机**：ZCode `agent/turn-machine.ts` 的 13 态迁移校验。独立 PR。

---

## 二、涉及文件与模块

### 2.1 后端

| 文件 | 改动性质 |
|---|---|
| `backend/core/legacy/context_microcompact.py` | **新建** — ZCode 式 microcompact 层 |
| `backend/core/legacy/context_first_aid.py` | 改：预算改为窗口派生 + 省量校验 |
| `backend/core/legacy/agent.py` | 改：`run_loop` 压缩钩子（`1074-1085`）+ cap 参数（`1023`）+ 熔断状态 |
| `backend/tests/unit/core/test_context_microcompact.py` | **新建** |
| `backend/tests/unit/core/test_context_first_aid.py` | 改（若已存在） |

### 2.2 前端

| 文件 | 改动性质 |
|---|---|
| `src/pages/Chat.tsx` | 改：rAF 节流 + `useLayoutEffect` + 阈值 + 惯性保护 |
| `vite.config.ts` | 改：加 `coverage.exclude` |
| `src/features/send-message/__tests__/fixtures/fakeStream.ts` | **新建** |
| `src/pages/__tests__/Chat.auto-scroll.test.tsx` | 改：补抖动回归用例 |

### 2.3 不改动

`context_compactor.py` / `branch_summarizer.py`（约 700 行三层引擎 + 完整单测已就绪，
本期只接线，不重写）。

---

## 三、技术方案

### 3.1 后端：分层压缩

#### 3.1.1 现状与目标结构

```
run_loop 迭代边界（agent.py:1074）
  │
  ├─ ① microcompact（新建，廉价、无 LLM、精确）
  │     触发前校验：预计节省 ≥ MIN_TOKEN_SAVINGS
  │     动作：清空白名单工具的旧结果 → 哨兵串，保留 tool_call_id
  │
  ├─ ② 仍超阈值 → first_aid_compact（既有，机械截断保头尾）
  │
  ├─ ③ 仍超阈值 → ContextCompactor.compact_with_summary（接线既有引擎）
  │     Layer1 micro → Layer2 滑窗 → Layer3 BranchSummarizer
  │
  └─ ④ 连续失败熔断 / rapid-refill 检测
```

#### 3.1.2 microcompact 模块设计

新建 `backend/core/legacy/context_microcompact.py`，参照 ZCode
`core/src/compact/microcompact.ts`：

```python
# 白名单：仅这些工具的结果可被清空（对齐 ZCode 的 DEFAULT_MICROCOMPACT_COMPACTABLE_TOOLS）
# 映射 Sage 工具名（backend/domain/tool_names.py 的 FILE_TOOLS / EXEC_TOOLS 等）
MICROCOMPACTABLE_TOOLS = frozenset({
    "read_file", "write_file", "edit_file", "list_dir",
    "bash", "bash_output",
    "web_search", "web_fetch", "http_download",
})

KEEP_RECENT_TOOL_RESULTS = 5     # 最近 N 条工具结果原样保留
MIN_TOKEN_SAVINGS = 256          # 省太少不动手，防抖动
CLEARED_SENTINEL = "[旧工具结果已清除]"  # 保持 tool_call/tool_result 配对
```

**与 `first_aid_compact` 的分工**（关键，避免职责重叠）：

| | `first_aid_compact`（既有） | `microcompact`（新建） |
|---|---|---|
| 动作 | 截断保头尾 400 字符 | **清空**，替换为哨兵串 |
| 作用范围 | 所有早期消息（tool + assistant/user 长文） | 仅白名单工具的**较早**结果 |
| 保留区 | 最近 `keep_recent` 条消息 | 最近 `KEEP_RECENT_TOOL_RESULTS` 条**工具结果** |
| 触发 | 超预算即调 / 溢出后重试 | 超预算且预计节省 ≥ 256 token |
| LLM | 无 | 无 |

两者串联：先 micro（省得多就停），不够再 first_aid，再不够才 ContextCompactor。

**清空 vs 截断的正确性**：`messages` 中 `role="tool"` 的条目清空 `content` 为哨兵串，
**不删除条目**、`tool_call_id` 原样保留 → assistant(tool_calls) ↔ tool 配对不断裂，
与 `first_aid_compact` docstring 承诺的结构不变量一致。

#### 3.1.3 阈值派生

现状 `DEFAULT_RUN_CTX_BUDGET_TOKENS = 100_000` 是固定常量，与实际模型窗口脱钩
（模型可能是 32k 也可能是 200k）。改为：

```python
def effective_budget_tokens(context_window: int, max_output_tokens: int) -> int:
    """有效上下文 = 模型窗口 − output 预留（两者共享窗口）。"""
    effective = context_window - min(max_output_tokens, 21_000)
    return effective - BUFFER_TOKENS
```

对标 ZCode `compact/policy.ts:69-82`。`context_window` 来源复用既有
`_resolve_effective_window(model_id, max_context, auto_context)`
（`backend/api/legacy_routes.py`），`max_output_tokens` 取模型目录值。

保留 env `SAGE_RUN_CTX_BUDGET_TOKENS` 覆盖（显式设置时优先，`0` = 关闭），
未设置时走派生路径。**拿不到窗口时回退到现有 100k 常量**，不得因窗口未知而关闭压缩。

#### 3.1.4 熔断与 rapid-refill

```python
MAX_CONSECUTIVE_COMPACT_FAILURES = 3   # 连续失败 N 次 → 停止预防性压缩
RAPID_REFILL_RATIO = 0.9               # 压缩后立刻又回到阈值的 90%+ → 告警
```

- 熔断状态存 `run_loop` 局部变量（每轮 fresh，与 `_first_aid_attempts` 同生命周期）
- rapid-refill 检测：压缩前后各测一次，若 `after > before * RAPID_REFILL_RATIO`
  说明压缩没起作用，记 warning 并计入熔断计数

对标 ZCode `compact/policy.ts:15` + `turn-loop.ts:76-99`。

#### 3.1.5 工具结果 cap

`agent.py:1023-1024`：

| env | 现状 | 改为 |
|---|---|---|
| `SAGE_TOOL_RESULT_CAP_CHARS` | 32000 | **102400**（100 KB，对齐 ZCode `MAX_*_MODEL_BYTES`） |
| `SAGE_TOOL_RESULT_RUN_BUDGET_CHARS` | 256000 | **512000** |

两处 append（并行 `agent.py:1388` / 串行 `_post_tool_observe:2080`）已共用
`cap_result_for_context`，改参数即全局生效，无需改调用点。

### 3.2 前端：滚动稳定性

只改 `Chat.tsx`，不动渲染结构。

#### 3.2.1 rAF 节流（核心）

现状每个 delta 同步写 `scrollTop`，高频下与用户手势竞争：

```tsx
// 现状 Chat.tsx:229-252
useEffect(() => {
  if (addedUserMessage || wasAtBottomRef.current) {
    el.scrollTop = el.scrollHeight;   // 每个 token 都同步写
  }
}, [messages.length, lastMsg?.content, ...]);
```

改为 `useLayoutEffect` + rAF 合帧，同一帧内多次 delta 只写一次：

```tsx
const rafRef = useRef<number | null>(null);
useLayoutEffect(() => {
  if (!(addedUserMessage || wasAtBottomRef.current)) return;
  if (rafRef.current !== null) return;          // 本帧已排队
  rafRef.current = requestAnimationFrame(() => {
    rafRef.current = null;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  });
}, [deps...]);
```

`useLayoutEffect` 而非 `useEffect`：DOM 布局完成后、paint 前写入，避免中间帧闪动。
卸载时需 `cancelAnimationFrame`。

#### 3.2.2 底部阈值

`BOTTOM_THRESHOLD_PX`（`Chat.tsx:64`）48 → **96**。

理由：原注释说 48px 对应 ~5 行文本，但流式时每帧新增可达数行；阈值过小会让
"距底 60px" 被判为非底部，跳到最新按钮闪现。96px 约 10 行，滚轮 1-2 击仍停在阈值内。

#### 3.2.3 惯性保护

`onScroll`（`Chat.tsx:262-275`）记录上一次 `scrollTop`；检测到用户主动上滑
（`delta < 0` 且非程序滚动导致）立即置 `wasAtBottomRef = false`，
避免 auto-scroll 与手势竞争时状态被程序滚动"洗白"。

### 3.3 覆盖率口径

#### 3.3.1 `coverage.exclude`

当前**只有 `test.exclude`，没有 `coverage.exclude`**（`vite.config.ts:181-190`）。
滚动改造会引入新分支，需先排掉不该计入的目录，否则棘轮被误伤。

**原提案（`*.gen.ts` / `chat/preview/**` / `chat/artifacts/**`）经核查三条全错，未采用**：

| 提案 | 核查结果 |
|---|---|
| `**/*.gen.ts` | 仓库里 0 个匹配文件 —— 排了个寂寞 |
| `src/widgets/chat/preview/**` | 整个目录 1 个文件 5 KB，排掉只挪动分母 0.1% |
| `src/widgets/chat/artifacts/**` | 目录内有 **3 个测试文件**，排掉等于把已测代码踢出分母 —— 与本节「不为凑数」原则自相矛盾 |

改为按**职责边界**排除，且以 `coverage json-summary` 定位真实分母大头
（4 个文件贡献 5267 条语句 = 旧分母的 6.9%，任何渲染层单测都不可能覆盖）：

```ts
exclude: [
  '**/node_modules/**', '**/dist/**', '**/dist-electron/**',
  '**/.claude/**', '**/.worktrees/**',
  'extension/**',                    // 第三方 vendored（readability/turndown）
  'backend/**/export_assets/**',     // 压缩过的 hljs 副本
  'packages/**',                     // 独立 MCP 包，非渲染层代码
],
```

依据：`package.json` 的 lint 脚本已用 `--ignore-pattern` 排除 `extension/**` 与
`backend/**/export_assets` —— **覆盖率口径与 lint 口径对齐**，不是为了抬高数字挑软柿子。
`artifacts/` 已有 3 个测试文件，故不排除。

注意：v8 provider 一旦显式指定 `exclude` 就不再套用默认值，上表第 1–5 项是
vitest 自带默认，必须重列否则 `node_modules` 会被计入。

排完实测 `stmts 69.79 / branch 81.07 / funcs 67.33 / lines 69.79`，
故阈值上调为 `67 / 79 / 65 / 67`（branch 几乎没涨 —— vendored 是语句多、
分支少的纯 JS；stmts/lines 水位真实上移）。

#### 3.3.2 fakeStream fixture

`src/features/send-message/__tests__/fixtures/fakeStream.ts`：导出 NDJSON 事件序列
生成器，供 `useChat.test.ts` / `stream.test.ts` / 新的滚动测试共用，
消除当前各处手工 `listenMock.mockImplementation` 的重复。

---

## 四、实施步骤

### 里程碑 1：后端 microcompact 模块（独立可验证）

- [x] 1.1 新建 `context_microcompact.py`（白名单、省量校验、哨兵串清空）
- [x] 1.2 新建 `backend/tests/unit/test_context_microcompact.py`（22 例；
  落点为 `unit/` 而非 `unit/core/`，与 `test_context_first_aid.py` 同级）
      （覆盖：白名单命中/未命中、省量不足不动手、tool_call 配对完整性、阈值边界）
- [x] 1.3 `context_first_aid.py` 预算改窗口派生
- [x] 1.4 `agent.py:1074-1085` 钩子接入 micro → first_aid **两级**级联
      （**原计划的三级未做，第三级见下方偏差说明**）
- [x] 1.5 `agent.py:1023-1024` cap 参数上调
- [x] 1.6 熔断 + rapid-refill 检测接入 `run_loop`
- [x] 1.7 跑 `pytest backend/tests/unit/core backend/tests/integration/test_chat_auto_compaction.py`

### 里程碑 2：前端滚动稳定性（独立可验证）

- [x] 2.1 `Chat.tsx` rAF 节流 + `useLayoutEffect`
- [x] 2.2 阈值 48 → 96
- [x] 2.3 惯性保护
- [x] 2.4 补 `Chat.auto-scroll.test.tsx` 抖动回归用例
- [x] 2.5 `vitest run src/pages/__tests__/Chat` 验证

### 里程碑 3：覆盖率口径与测试基建

- [x] 3.1 加 `coverage.exclude`（原提案三条经核查全错，改为按职责边界排除，理由见 §3.3.1）
- [x] 3.2 实测覆盖率，按结果上调阈值（60/79/65/60 → **67/79/65/67**）
- [x] 3.3 新建 `fakeStream.ts` fixture 并在 `useChat.test.ts` 试用（43 例绿）
- [x] 3.4 fixture 自测 `fakeStream.test.ts`（9 例）—— 夹具坏了会让所有下游测试
      静默变空（回调不触发 → 断言"没变化"→ 假绿），故夹具自身需被测；
      变异验证：把 `listener?.(envelope)` 改成空操作 → 4/9 转红

### 4.1 实施偏差：第三级 `ContextCompactor` 未接入（已决策）

§3.1.1 排的是三级级联，实际只做了 micro → first_aid **两级**。不接第三级的原因：

1. `ContextCompactor.compact_with_summary` 会**调 LLM**。挂在迭代边界意味着每次
   两级廉价压缩都不够时多一次 LLM 往返——比它省下的 token 贵。
2. 它住在 `application/services`，而调用方是 `core/legacy/agent.py`。
   `core` 不在 import-linter 契约里（`backend/pyproject.toml` 的 layers 只有
   api/adapters/application/ports/domain），所以**静态检查不会拦**——但从
   legacy core 向上依赖 application 正是六边形重构要消除的方向，不该新增调用点。

兜底未削弱：压不下去时仍由既有的溢出急救环（`_MAX_FIRST_AID_ATTEMPTS=2`）兜底。
若将来要在预防路径接 LLM 摘要，正确做法是先把 `run_loop` 的这段搬进
`application` 层，而不是在 legacy core 里 import。

---

## 五、风险评估

### 5.1 流式行虚拟化为何本期不做

`MessageList.tsx` 换成 `useVirtualizer` 后，正在流式输出的那一行高度**每 token 变化**，
`measureElement` 会持续重测；叠加 `Message.tsx` 1142 行内含
ReactMarkdown + Shiki + mermaid + katex，测量开销与抖动风险都高。
需先在里程碑 2 稳住滚动基线，再单开 PR 引入行高 LRU cache
（`turnGrouping.ts:32/35` 的 `turn-${msg.id}` 已是稳定 key，可直接用）。

### 5.2 压缩导致模型丢失关键信息

microcompact 清空工具结果是不可逆的信息损失。缓解：
- 白名单只含「结果可重新查询」的工具（read_file/bash/web_*），不含 write_file 之外的
  不可重放操作
- 保留最近 5 条工具结果原样
- 省量不足 256 token 不动手
- 保留 `tool_call_id` 保证结构不变量

### 5.3 阈值派生的兼容性

`_resolve_effective_window` 在部分路径可能返回 None/0（模型目录缺失时）。
派生函数须在拿不到窗口时**回退到现有 100k 常量**，不得因窗口未知而关闭压缩。

### 5.4 覆盖率 exclude 误排

exclude 排得太宽会掩盖真实未覆盖代码。排完需对比 exclude 前后的
per-file 覆盖率差异，确认排掉的确实是预览/生成式代码。

### 5.5 双分支影响

本次改动涉及 `backend/core/legacy/agent.py` 与 `src/pages/Chat.tsx`，
两者在 `release/win7` 均存在。按项目双分支策略，需 cherry-pick 到 win7 并适配：

- Python 3.8 vs 3.11：本次后端改动**不使用** PEP 604（`X | Y`），
  仅标准类型注解，天然兼容
- `context_microcompact.py` 为新建文件，需 `git add` 后 cherry-pick

---

## 六、验证方式

| 项 | 命令 |
|---|---|
| 后端单测 | `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/core backend/tests/integration/test_chat_auto_compaction.py` |
| 后端 lint | `ruff check backend/core/legacy/` |
| 前端滚动测试 | `npx vitest run src/pages/__tests__/Chat` |
| 前端 lint/typecheck | `npx eslint src && npx tsc --noEmit` |
| 覆盖率实测 | `npx vitest run --coverage` |
| 架构约束 | `npm run architecture-check`（`count-lines` 可能需更新 baseline） |

> 注：初稿此处写的是 `sage-backend-py311`，实际 dev 环境是 `sage-backend`（Python 3.10），
> 已按 `.claude/CLAUDE.md` 更正。

