# Skill Draft UX 闭环设计 — Sub-project A

> **日期**:2026-09-04
> **作者**:Claude (with user)
> **状态**:Draft — 待用户 review
> **分支**:`feat/skill-draft-ux-closure` (base: main)
> **Worktree**:`.worktrees/feat-skill-draft-ux-closure`

## 背景与目标

Sage 的 Background Review 系统(`complex_turn` / `low_success_rate` / `explicit_learn` 触发 LLM 提炼可复用 skill 草案)已完整落地:后端管线、`/learn` 端点、`/skill-drafts` 审批 API、前端 `SkillDraftList` + `/learn` 斜杠命令、Win7 parity(PR #340)。**但"生成 → 审批"这一段 UX 仍有几处断裂**:

1. LLM 生成的草稿质量参差不齐 — 偶有把单次操作当 skill 提取,或 schema 不合规
2. 前端 skill draft 列表的中文/英文硬编码文案未走 i18n
3. `/learn` 命令的反馈文案也是英文硬编码
4. 用户在审批草稿时只能看 name/description/when_to_use,看不到完整 SKILL.md content,容易盲批

**目标**:把上述 4 处断裂补齐,让"后台生成草稿 → 用户审批"这段体验可见、可读、可控、可追溯。

## 范围与非范围

**范围(Sub-project A)**:
- (4) Prompt 质量提升:重写 `prompts/review.txt`,加 few-shot、anti-pattern、schema 校验
- (6) i18n 审计:`SkillDraftList.tsx` + `Chat.tsx` `/learn` 反馈文案走 i18n
- (2) `/learn` 即时反馈 i18n(并入 (6))
- (3) 草稿详情预览:modal 渲染完整 SKILL.md content,审批按钮移至 modal 内

**非范围(Sub-projects B 和 C,独立 spec)**:
- Sub-project B:后台通知子系统(IPC 事件总线 + skill 草稿通知 consumer)— 跨模块基建
- Sub-project C:草稿历史(`status=approved/rejected` 列表 + 详情页)

## 关键发现(设计过程中)

写设计时重新盘点了现状,发现大部分能力已存在,**实际工作量比最初预估小得多**:

| 项 | 现状 | 实际要做 |
|---|---|---|
| `/learn` 行为 | 已实现 `toast.info` + API + `toast.success` + `navigate` + `toast.error`(`Chat.tsx:253-263`) | 仅 i18n 替换 3 条文案 |
| 后端 list 返回 content | `_draft_to_dict` 已含 `content`(line 2716) | 不需要新后端端点 |
| Markdown 渲染库 | 项目用 `react-markdown`,`MarkdownPreview.tsx` 已有 | 直接复用 |
| Modal 组件 | `shared/ui/Dialog/` + `Modal.tsx` 已有 | 直接复用 |

## 设计

### 子项 1:Prompt 质量提升

**文件**:`backend/skills/prompts/review.txt`

**现状**:简单 JSON 输出要求,无 few-shot、无 anti-pattern、无 schema 约束。

**提议** — 4 段式 prompt:
1. **角色定义 + 输出要求**(保留现有)
2. **强制 schema 约束**:
   - `name`:严格 kebab-case,正则 `^[a-z][a-z0-9-]{2,40}$`
   - `description`:一句话,≤80 字
   - `when_to_use`:≥30 字,必须具体到触发条件(场景 + 信号)
   - `content`:完整 SKILL.md,必须包含 `## 步骤` `## 触发条件` `## 示例` 三段

3. **Few-shot 示例**(2 个):
   - 例 1(好的 skill):"用户反复执行 `git stash → git switch → git stash pop` 序列" → 提取出 `git-branch-hopping` skill,`when_to_use` 写明"当用户在多个分支间反复切换且需要保留未提交改动时"
   - 例 2(好的 skill):"用户连续 3 次对 LLM 输出进行格式重排" → 提取出 `format-output-reorder` skill

4. **Anti-patterns**(3 条):
   - ❌ 不要把单次操作当 skill(比如"删除文件 X")
   - ❌ 不要提取已经在项目里有工具支持的操作(比如"调用 /learn 端点")
   - ❌ 不要提取太泛的模式(比如"当用户需要帮助时提供帮助")

**数据流不变**:trigger → ReviewQueue → ReviewService → LLM → SkillDraft → SkillDraftStore。只改 LLM 输入侧。

**错误处理**:
- LLM 返回 JSON 缺必填字段 → 现有 `_REQUIRED_FIELDS` 校验已能捕获,抛 ValueError
- 新增 schema 校验失败 → 同样抛 ValueError,ReviewQueue 会 `_mark_failed`,事件保留在 `review_events` 表里可追溯

**测试**:
- Unit test:给 ReviewService 注入 fake LLM provider(返回合格 JSON + 各种不合规 JSON),验证 schema 校验逻辑
- 可选 Integration test:用真实 LLM provider 跑一次,验证草稿符合 schema

**回滚**:把 `review.txt` 回退到旧版本即可。

### 子项 2:i18n 审计 + `/learn` 反馈 i18n

**文件**:
- `src/widgets/skills/SkillDraftList.tsx` — 9 处文案替换
- `src/pages/Chat.tsx` — 3 处文案替换(handleLearn)
- `src/shared/lib/i18n/zh.ts` — 追加 14 个 key(11 SkillDraftList + 3 Chat.tsx /learn)
- `src/shared/lib/i18n/en.ts` — 追加 14 个 key(同上)
- `src/widgets/skills/__tests__/SkillDraftList.test.tsx` — 更新断言

**i18n 约定**(复用现有):
- 点分隔 key(如 `skill_draft.loading`)
- `{placeholder}` 插值(如 `{name}`)
- 必须同时改 zh + en(`TranslationKey = keyof typeof zh` 类型约束)

**SkillDraftList 新增 key**(11 个):

| Key | zh | en |
|---|---|---|
| `skill_draft.loading` | 加载草稿中... | Loading drafts... |
| `skill_draft.load_failed` | 加载失败: {error} | Failed to load: {error} |
| `skill_draft.retry` | 重试 | Retry |
| `skill_draft.no_drafts` | 暂无待审草稿 | No pending drafts |
| `skill_draft.when_to_use` | 何时使用: {text} | When to use: {text} |
| `skill_draft.approve` | 批准 | Approve |
| `skill_draft.reject` | 拒绝 | Reject |
| `skill_draft.approved` | 已批准 {name} | Approved {name} |
| `skill_draft.approve_failed` | 批准失败: {error} | Approve failed: {error} |
| `skill_draft.rejected` | 已拒绝 {name} | Rejected {name} |
| `skill_draft.reject_failed` | 拒绝失败: {error} | Reject failed: {error} |

**aria-label 同步 i18n**:现有 `Approve ${draft.name}` / `Reject ${draft.name}` 也走 i18n,
组合方式:`${t('skill_draft.approve')} ${draft.name}`(无需额外 key)。

**Chat.tsx /learn 新增 key**(3 个):

| Key | zh | en |
|---|---|---|
| `chat.learn_reviewing` | 正在生成技能草稿... | Reviewing... |
| `chat.learn_queued` | 已加入审核队列 — 查看待审草稿 | Review queued — check Pending Drafts |
| `chat.learn_failed` | 审核失败: {error} | Review failed: {error} |

**测试**:
- 复用 `<I18nProvider defaultLocale="zh">` 包
- 现有 `SkillDraftList.test.tsx` 更新断言字符串为 `t('...')`
- 现有 `ChatInput.learn.test.tsx` 不需改(只测命令识别)
- 可选新增 snapshot test 验证 zh/en 都能渲染

**回滚**:纯文案替换,无行为变化,git revert 即可。

### 子项 3:草稿详情预览(纯前端)

**文件**:
- `src/widgets/skills/SkillDraftList.tsx` — 加 "Preview" 按钮 + `selectedDraft` state
- `src/widgets/skills/SkillDraftDetail.tsx` — **新组件**,封装 modal 内容
- `src/widgets/skills/__tests__/SkillDraftDetail.test.tsx` — **新测试**

**复用组件**(无需新建):
- `src/shared/ui/Dialog/Dialog.tsx` — modal 容器(含 ESC 关闭 + backdrop 关闭)
- `src/widgets/wiki/MarkdownPreview.tsx` — markdown 渲染

**交互流程**:
```
用户在 /skills?tab=drafts
    ↓ 点击卡片上的 "Preview" 按钮
Modal 打开:
  ├── 顶部: skill name + trigger_type badge
  ├── 中部: draft.description + draft.when_to_use
  ├── 分隔线
  ├── 主体: draft.content 用 MarkdownPreview 渲染
  └── 底部: Cancel / Reject / Approve 按钮
    ↓ 用户决策
  成功: toast + modal 关闭 + card 移除
```

**`SkillDraftDetail` 组件结构**(示意):
```tsx
function SkillDraftDetail({ draft, onApprove, onReject, onClose }: Props) {
  return (
    <Dialog open={!!draft} onClose={onClose} title={draft.name}>
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted px-1.5 py-0.5 bg-bg-muted rounded">
            {draft.trigger_type}
          </span>
          <span className="text-sm text-muted">{draft.description}</span>
        </div>
        <div className="text-sm">
          <strong>何时使用:</strong> {draft.when_to_use}
        </div>
        <div className="border-t pt-4">
          <MarkdownPreview content={draft.content} />
        </div>
        <div className="flex items-center gap-2 justify-end border-t pt-4">
          <Button variant="outline" onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="error" onClick={() => onReject(draft)}>{t('skill_draft.reject')}</Button>
          <Button variant="success" onClick={() => onApprove(draft)}>{t('skill_draft.approve')}</Button>
        </div>
      </div>
    </Dialog>
  );
}
```

**SkillDraftList 修改**:
- 卡片底部按钮从 "Approve / Reject" 改为单一 "Preview"
- 新增 `selectedDraft` state 控制 modal 打开
- Approve/Reject 移到 modal 内(`SkillDraftDetail` 内)
- 操作成功后 `setSelectedDraft(null)` 关闭 modal

**额外 i18n key**:
- `skill_draft.preview` → 预览 / Preview
- `common.cancel`(已存在,复用)→ 取消 / Cancel

**风险**:
- Modal ESC 关闭 + focus trap:Dialog 已有,复用即可
- MarkdownPreview 渲染大型 SKILL.md 可能慢:内容 > 10KB 时显示 loading 态(可后续优化)

**测试**:
- `SkillDraftDetail.test.tsx`:
  - 点击 "Preview" → modal 打开
  - modal 内显示 draft.content 渲染后的 markdown
  - 点 Approve → 调 onApprove + 调 onClose
  - 点 Reject → 调 onReject + 调 onClose
  - ESC / 点 backdrop → 调 onClose
- 现有 `SkillDraftList.test.tsx` 更新:不再直接测试 approve/reject(现在在 SkillDraftDetail 内)

**回滚**:git revert 即可,无后端变更。

## 实施顺序

1. **PR-1: Prompt 质量提升**(后端)— 0.5 天,0 前端依赖
2. **PR-2: i18n 审计 + /learn 反馈 i18n**(前端,合并)— 0.5 天,0 后端依赖
3. **PR-3: 草稿详情预览**(前端)— 1 天,无新依赖

## 风险评估

| 风险 | 影响 | 缓解 |
|---|---|---|
| Prompt 改动导致草稿质量显著下降 | 中 | 用 fixture 跑 LLM 输出,人工评估 ≥5 个案例再合 PR-1;git revert 即可 |
| i18n 框架不支持 `{placeholder}` 插值 | 低 | 已确认 `chat.compact_success` 等现有 key 已用 `{placeholder}` 风格 |
| MarkdownPreview 对 SKILL.md 特殊语法(slash command 块等)渲染异常 | 低 | SKILL.md 是标准 markdown,无特殊语法;若有,可降级为 `<pre>` 展示 |
| Dialog 组件 focus trap 不完整 | 低 | Dialog 已有测试,先复用它;若有缺陷再单独修 |
| `/learn` 在无 session_id 时触发 | 已处理 | `Chat.tsx:254` 已 `if (!currentSessionId \|\| isLoading) return;` |

## 测试策略

- **每个 PR 单独 unit + integration 测试**
- PR-1:ReviewService fake LLM provider + schema 校验测试
- PR-2:现有 `SkillDraftList.test.tsx` 更新 + `<I18nProvider>` 包验证
- PR-3:`SkillDraftDetail.test.tsx` + 更新 `SkillDraftList.test.tsx`
- **E2E 测试**(可选,不阻塞):`/learn → /skills?tab=drafts → Preview → Approve` 完整流程

## PR 拆分

| PR | 子项 | 文件 | 估时 |
|---|---|---|---|
| PR-1 | (4) Prompt 质量 | `prompts/review.txt` + `test_review_service.py` | 0.5 天 |
| PR-2 | (6) + (2) i18n | `zh.ts` / `en.ts` / `SkillDraftList.tsx` / `Chat.tsx` / 测试 | 0.5 天 |
| PR-3 | (3) 草稿详情预览 | `SkillDraftList.tsx` / `SkillDraftDetail.tsx` / 测试 | 1 天 |

**总计**:约 2 天(单 PR 串行)。

## 后续(Sub-projects B 和 C)

本 spec 不覆盖以下两项,各自独立 spec:

- **Sub-project B — 后台通知子系统**:当 `complex_turn` / `low_success_rate` 后台自动 enqueue 草稿时,主动通知用户(而不是等用户去 Skills 页看)。需要新建 IPC 事件总线 + 全局 toast consumer。
- **Sub-project C — 草稿历史**:让用户能看到已批准/已拒绝的草稿列表,需要后端新端点 + 前端新 tab。
