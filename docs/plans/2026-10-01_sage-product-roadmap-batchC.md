# 批次 C（第二阶段）实施方案：来源可追溯 + 技能/定时任务联动

- 日期：2026-10-01
- 适用范围：主线 `feat/sage-product-roadmap-main-20261001` 与 Win7 LTS
  `feat/sage-product-roadmap-win7-20261001`，逐文件针对各自基线实施，不做分支合并。
- 上游方案：`docs/plans/2026-10-01_sage-product-roadmap.md` §5（C1 上下文/来源可检查、
  C2 任务配方与复用）。
- 前置实施：批次 A/B 已合并进本分支；批次 C 已完成的“任务配方保存、能力感知入口、
  来源说明校准”不在本方案范围内。

## C1 上下文/来源可追溯

### 现状（已核实，不是假设）

- `backend/chat/context_sources.py` 对最终请求 payload 的 system 消息按固定标记切段，
  产出 `[{key, tokens, count, trimmed?}]`——**只有分类与 token 数，没有单条标识**。
- 可取得真实标识的块（来自装配器实际输出的格式）：
  - 项目资料：`--- <material_id> [status] (来源消息 <msg_id>) ---`，单条截断在内容尾部追加
    `[截断]`，超预算的资料在块尾汇总为“另有 N 条资料超出预算被排除。”
  - 技能清单：`<available-skills>` 内 `- /<name>：<desc>`
  - 自动激活技能：`Skill '<name>' auto-activated: <desc>`
  - 附件：`<attachments>` 内 `=== <source_ref> ===`
- 取不到标识的块：记忆召回（只有正文）、项目指令/概览/约束（正文无路径或 id）。

### 改动

1. `backend/chat/context_sources.py`（纯函数，无副作用）：
   - 新增 `extract_source_items(key, block_text) -> list[dict]`：只按上面**真实存在的格式**
     提取标识，返回 `[{id, label?, truncated: bool}]`；取不到标识的来源返回 `[]`。
   - 新增 `EXCLUDED_RE`：解析资料块尾的“另有 N 条资料超出预算被排除。”
   - `compute_context_sources` 的输出条目在原有 `key/tokens/count/trimmed` 之外追加：
     - `items`：本轮**实际注入**的单条标识（上限 20 条，超出只记数量，不伪造明细）
     - `excluded`：被预算排除的条数（仅资料块有）
     - `identifiable`：该来源是否携带可追溯标识（布尔，供前端决定是否展示明细）
   - 不改动任何装配链路、不改动预算阈值、不新增估算口径。
2. 前端 `src/shared/api/usageApi.ts`：`ContextSource` 增加可选 `items/excluded/identifiable`。
3. 前端 `src/widgets/chat/ContextMeter.tsx`：来源面板支持展开单条明细，并给出四态：
   - **已注入**：出现在 `items` 中
   - **已截断**：该来源 `trimmed > 0`（保留开头，尾部被截）
   - **被排除**：`excluded > 0`（整条未进入）
   - **未核验**：对所有来源统一声明（不证明事实或引用已核验，非发送前预览）
   - 取不到标识的来源显示“该来源未提供可追溯标识”，**不虚构跳转、不显示假路径**。

### 测试

- `backend/tests/unit/chat/test_context_sources.py`：资料 id/截断/排除、技能名、附件 ref、
  记忆来源无标识、上限截断、标记与装配器标题同步（沿用现有用例风格）。
- `src/widgets/chat/__tests__/ContextMeter.sources.test.tsx`：四态渲染与“未提供标识”文案。

## C2 技能 × 定时任务 / 配方联动

### 现状（已核实）

- `ScheduledTask` 只有 `content: string`（提示词正文），后端调度模型没有技能字段；
  技能列表来自 `skillsApi.list()`（返回真实注册的 `Skill`，含 `name/enabled/triggers`）。
- 已有“任务配方”保存在本地（`src/features/task-brief/taskRecipes.ts`），未与定时任务连通。

### 改动

1. 新增 `src/features/scheduled/skillLink.ts`（纯函数）：
   - `parseSkillRefs(content)`：从任务正文解析 `/<name>` 形式的技能引用。
   - `validateSkillRefs(content, skills)`：`{ known, unknown, disabled }`——**按真实技能列表
     校验**，不按名字猜测能力；引用未注册或已停用的技能时明确报出。
   - `insertSkillRef(content, name)` / `removeSkillRef(content, name)`：幂等插入/移除。
2. `src/features/scheduled/CreateTaskModal.tsx`：
   - 增加技能选择器（列出真实技能，含停用标记），插入/移除引用。
   - 保存前校验：存在未注册/已停用引用时给出明确提示并要求用户确认，**不静默丢弃**。
3. 定时任务列表（`CronJobSection.tsx`）：按正文解析显示关联技能徽标；技能已停用/未注册时
   显示“失效引用”而非隐藏。（**本轮延后**：列表侧需独立加载技能列表，与 C3/C4 一起做，
   不为展示而新增后端字段。）
4. 配方联动：配方列表提供“用此配方创建定时任务”，仅预填名称与正文（含简报与边界声明），
   **跳转后仍需用户确认时间、会话与启用状态**；不自动创建、不自动运行、不在后台静默创建。
   （**本轮延后**：需要配方 UI 与调度弹窗的联动入口，待 C1/C2 稳定后在下一轮接入。）

### 明确不做

- 不改后端调度 schema、不改执行链路；技能引用只是 `content` 文本的一部分，删除技能后前端
  按“失效引用”呈现。
- 不自动执行技能，不因引用而扩大权限或文件访问范围。

### 测试

- `src/features/scheduled/__tests__/skillLink.test.ts`：解析/校验/插入/移除/幂等/停用技能。
- 定时任务弹窗与列表的渲染测试（引用徽标、失效引用提示、保存前确认）。

## 本轮不做（继续 pending）

- C3 能力感知路由（含模型能力未知显示、禁止静默降级）。
- C4 单任务硬预算（计划明确要求**由后端执行并验证**，不能用 prompt 或客户端标签冒充）。
- Office 生成管线本体改造。

## 验证与门禁

- 主线：Python 3.11.16（`sage-backend`）跑定向 pytest；Win7：Python 3.8.20
  （`sage-backend-py38`）跑同一批用例（新增代码保持 Py3.8 语法）。
- 两条线：`npx vitest run <定向文件>`、`npm run typecheck`、`eslint`、`prettier`、
  `node scripts/architecture-check.mjs`、`ruff check backend/`。
- 不自动推送/合并；CI 是最终门禁。远端推送若受网络限制，沿用 Git Data API 逐对象提交并
  公开记录（远端 sha 与本地一致）。
