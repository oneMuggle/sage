# Skill Draft UX 闭环实施计划 (Sub-project A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Skill Draft 后台生成 → 用户审批这段体验的 4 处断裂(prompt 质量 / i18n 文案 / `/learn` 反馈 / 详情预览)补齐。

**Architecture:** 3 个独立 PR 串行实现,无跨 PR 依赖。PR-1 改 prompt + 加 schema 校验;PR-2 把前端 14 处硬编码文案替换为 i18n key;PR-3 新建 `SkillDraftDetail` 组件,用 `Dialog` + `MarkdownPreview` 渲染完整 SKILL.md content,把审批按钮从卡片移到 modal 内。

**Tech Stack:** Python 3.10 (FastAPI + `string.Template`) / TypeScript + React (Radix Dialog + react-markdown + i18n dot-namespace) / Vitest + pytest

**Spec:** [`docs/superpowers/specs/2026-09-04-skill-draft-ux-closure-design.md`](../specs/2026-09-04-skill-draft-ux-closure-design.md)

## Global Constraints

- **Python 环境**:所有后端命令必须用 `conda run -n sage-backend ...` 或 `/home/fz/anaconda3/envs/sage-backend/bin/...`,**禁止** 用系统 python / base conda
- **i18n 约定**:点分隔 key(如 `skill_draft.loading`),`{placeholder}` 插值,必须同时改 `zh.ts` + `en.ts`(`TranslationKey = keyof typeof zh` 类型约束)
- **组件复用**:优先复用 `shared/ui/Dialog/`(Radix 封装)+ `widgets/wiki/MarkdownPreview`(react-markdown),**不新建**
- **Git 流程**:每个 PR 独立 feature commit,PR-1/2/3 全部合到 main 后再做下一个(避免冲突)
- **测试覆盖率**:每个 PR ≥80%,pytest 用 `pytest.mark.unit` 标记,vitest 用 `describe/it` 结构

---

# PR-1:Prompt 质量提升(后端)

## File Structure

**Files:**
- Modify: `backend/skills/prompts/review.txt`(重写 prompt)
- Modify: `backend/skills/review_service.py`(加 `_validate_skill_schema` 方法)
- Test: `backend/tests/unit/test_review_service.py`(追加 `TestSchemaValidation` 类)

**Interfaces:**
- Consumes: `ReviewService.generate_draft()` 现有签名不变
- Produces: `_validate_skill_schema(parsed: Dict[str, Any]) -> None`(新私有方法,在 `_validate_skill_name` 之前调用)

---

### Task 1: 写 schema 校验失败测试

**Files:**
- Modify: `backend/tests/unit/test_review_service.py:315-376`(`TestErrorHandling` 类后追加)

- [ ] **Step 1: 追加 `TestSchemaValidation` 测试类**

在 `backend/tests/unit/test_review_service.py` 文件末尾追加:

```python
# ---------------------------------------------------------------------------
# Tests: schema validation (PR-1 UX closure)
# ---------------------------------------------------------------------------


class TestSchemaValidation:
    """PR-1: LLM output must satisfy the enhanced schema constraints."""

    @pytest.mark.asyncio()
    async def test_name_regex_rejects_uppercase(self):
        """Skill name must be kebab-case (lowercase + digits + hyphens)."""
        from backend.skills.review_service import ReviewService

        bad = json.dumps(
            {
                "name": "Test-Skill",  # uppercase T, S
                "description": "d",
                "when_to_use": "w" * 40,
                "content": "# Skill\n\n## 步骤\n\n1. x\n\n## 触发条件\n\nt\n\n## 示例\n\ne",
            }
        )
        provider = _make_mock_provider(bad)
        service = ReviewService(provider)

        with pytest.raises(ValueError, match="kebab-case"):
            await service.generate_draft(trigger_type="t", context={})

    @pytest.mark.asyncio()
    async def test_name_regex_rejects_too_short(self):
        """Skill name must be ≥ 3 chars."""
        from backend.skills.review_service import ReviewService

        bad = json.dumps(
            {
                "name": "ab",  # too short
                "description": "d",
                "when_to_use": "w" * 40,
                "content": "# Skill\n\n## 步骤\n\n1. x\n\n## 触发条件\n\nt\n\n## 示例\n\ne",
            }
        )
        provider = _make_mock_provider(bad)
        service = ReviewService(provider)

        with pytest.raises(ValueError, match="3..40"):
            await service.generate_draft(trigger_type="t", context={})

    @pytest.mark.asyncio()
    async def test_description_too_long(self):
        """Description must be ≤ 80 chars."""
        from backend.skills.review_service import ReviewService

        bad = json.dumps(
            {
                "name": "test-skill",
                "description": "x" * 81,
                "when_to_use": "w" * 40,
                "content": "# Skill\n\n## 步骤\n\n1. x\n\n## 触发条件\n\nt\n\n## 示例\n\ne",
            }
        )
        provider = _make_mock_provider(bad)
        service = ReviewService(provider)

        with pytest.raises(ValueError, match="≤ 80"):
            await service.generate_draft(trigger_type="t", context={})

    @pytest.mark.asyncio()
    async def test_when_to_use_too_short(self):
        """when_to_use must be ≥ 30 chars."""
        from backend.skills.review_service import ReviewService

        bad = json.dumps(
            {
                "name": "test-skill",
                "description": "d",
                "when_to_use": "too short",  # 9 chars
                "content": "# Skill\n\n## 步骤\n\n1. x\n\n## 触发条件\n\nt\n\n## 示例\n\ne",
            }
        )
        provider = _make_mock_provider(bad)
        service = ReviewService(provider)

        with pytest.raises(ValueError, match="≥ 30"):
            await service.generate_draft(trigger_type="t", context={})

    @pytest.mark.asyncio()
    async def test_content_missing_required_sections(self):
        """content must contain ## 步骤, ## 触发条件, ## 示例."""
        from backend.skills.review_service import ReviewService

        bad = json.dumps(
            {
                "name": "test-skill",
                "description": "d",
                "when_to_use": "w" * 40,
                "content": "# Skill\n\nJust a description, no sections.",
            }
        )
        provider = _make_mock_provider(bad)
        service = ReviewService(provider)

        with pytest.raises(ValueError, match="## 步骤"):
            await service.generate_draft(trigger_type="t", context={})

    @pytest.mark.asyncio()
    async def test_valid_schema_passes(self):
        """A fully compliant draft should pass all schema checks."""
        from backend.skills.review_service import ReviewService, SkillDraft

        good = json.dumps(
            {
                "name": "git-branch-hopping",
                "description": "Switch between git branches while preserving uncommitted work",
                "when_to_use": "When the user repeatedly switches branches and needs to stash/unstash changes",
                "content": "# Git Branch Hopping\n\n## 步骤\n\n1. git stash\n2. git switch <branch>\n3. git stash pop\n\n## 触发条件\n\nUser switches branches with dirty working tree\n\n## 示例\n\n```bash\ngit stash && git switch main && git stash pop\n```",
            }
        )
        provider = _make_mock_provider(good)
        service = ReviewService(provider)

        draft = await service.generate_draft(trigger_type="complex_turn", context={})
        assert isinstance(draft, SkillDraft)
        assert draft.name == "git-branch-hopping"
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_review_service.py::TestSchemaValidation -v`

Expected: 全部 FAIL,因为 `_validate_skill_schema` 方法不存在。

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/test_review_service.py
git commit -m "test(review): add schema validation tests (PR-1)"
```

---

### Task 2: 实现 schema 校验

**Files:**
- Modify: `backend/skills/review_service.py:206-231`(`_validate_skill_name` 前追加)

- [ ] **Step 1: 在 `_validate_skill_name` 之前插入 `_validate_skill_schema`**

在 `backend/skills/review_service.py` 第 206 行(`@staticmethod` 装饰 `_validate_skill_name`)之前插入:

```python
    @staticmethod
    def _validate_skill_schema(parsed: Dict[str, Any]) -> None:
        """Validate LLM output against the enhanced skill draft schema.

        Raises ``ValueError`` if the draft violates any constraint:
        - ``name`` must match ``^[a-z][a-z0-9-]{2,40}$`` (kebab-case)
        - ``description`` must be ≤ 80 chars
        - ``when_to_use`` must be ≥ 30 chars
        - ``content`` must contain ``## 步骤``, ``## 触发条件``, ``## 示例``

        Args:
            parsed: The parsed JSON dict from LLM output.

        Raises:
            ValueError: A schema constraint is violated.
        """
        import re

        name = parsed.get("name", "")
        if not re.match(r"^[a-z][a-z0-9-]{2,40}$", name):
            raise ValueError(
                f"Skill name must be kebab-case (3..40 chars, lowercase+digits+hyphens): {name!r}"
            )

        description = parsed.get("description", "")
        if len(description) > 80:
            raise ValueError(
                f"Description must be ≤ 80 chars, got {len(description)}: {description!r}"
            )

        when_to_use = parsed.get("when_to_use", "")
        if len(when_to_use) < 30:
            raise ValueError(
                f"when_to_use must be ≥ 30 chars, got {len(when_to_use)}: {when_to_use!r}"
            )

        content = parsed.get("content", "")
        for section in ("## 步骤", "## 触发条件", "## 示例"):
            if section not in content:
                raise ValueError(
                    f"content must contain '{section}' section, got: {content[:100]!r}..."
                )
```

- [ ] **Step 2: 在 `generate_draft` 中调用 `_validate_skill_schema`**

在 `backend/skills/review_service.py` 第 187 行(`self._validate_skill_name(parsed["name"])`)之前插入:

```python
        # PR-1: Validate against enhanced schema (name regex, length constraints, content structure)
        self._validate_skill_schema(parsed)
```

- [ ] **Step 3: 运行测试,确认通过**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_review_service.py::TestSchemaValidation -v`

Expected: 全部 PASS。

- [ ] **Step 4: 运行全量 unit 测试,确认无回归**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_review_service.py -v`

Expected: 全部 PASS(包括原有测试)。

- [ ] **Step 5: Commit**

```bash
git add backend/skills/review_service.py
git commit -m "feat(review): add schema validation for skill drafts (PR-1)"
```

---

### Task 3: 重写 prompt 模板

**Files:**
- Modify: `backend/skills/prompts/review.txt`(全文替换)

- [ ] **Step 1: 重写 `review.txt`**

将 `backend/skills/prompts/review.txt` 全文替换为:

```
你是一个技能策展人。根据以下对话轨迹,提炼出一个可复用的技能。

触发类型:$trigger_type

对话上下文:
$conversation_context

请输出一个 JSON 对象,包含:
{
  "name": "技能名称(kebab-case,3-40 字符,小写+数字+连字符)",
  "description": "一句话描述(≤80 字)",
  "when_to_use": "何时使用这个技能(≥30 字,必须具体到触发条件和信号)",
  "content": "技能的完整 SKILL.md 内容(markdown 格式,必须包含 ## 步骤 ## 触发条件 ## 示例 三段)"
}

Schema 约束:
- name: 正则 ^[a-z][a-z0-9-]{2,40}$
- description: ≤ 80 字符
- when_to_use: ≥ 30 字符,必须具体到场景 + 信号
- content: 必须包含三个二级标题 ## 步骤 / ## 触发条件 / ## 示例

Few-shot 示例:

例 1(好的 skill):
对话轨迹: 用户反复执行 git stash → git switch → git stash pop 序列
输出:
{
  "name": "git-branch-hopping",
  "description": "在多个 git 分支间切换时保留未提交改动",
  "when_to_use": "当用户在多个分支间反复切换且需要保留未提交改动时",
  "content": "# Git Branch Hopping\n\n## 步骤\n\n1. git stash\n2. git switch <branch>\n3. git stash pop\n\n## 触发条件\n\n用户切换分支且有未提交改动\n\n## 示例\n\n```bash\ngit stash && git switch main && git stash pop\n```"
}

例 2(好的 skill):
对话轨迹: 用户连续 3 次对 LLM 输出进行格式重排
输出:
{
  "name": "format-output-reorder",
  "description": "对 LLM 输出进行结构化格式重排",
  "when_to_use": "当用户反复要求对 LLM 输出进行格式调整时",
  "content": "# Format Output Reorder\n\n## 步骤\n\n1. 识别用户期望的格式\n2. 重排内容\n3. 验证格式\n\n## 触发条件\n\n用户连续 2+ 次对输出格式不满意\n\n## 示例\n\n用户: 把这段代码改成表格形式"
}

Anti-patterns(不要提取):
- ❌ 单次操作(如"删除文件 X")
- ❌ 已有工具支持的操作(如"调用 /learn 端点")
- ❌ 过于泛化的模式(如"当用户需要帮助时提供帮助")

要求:
1. 技能应该是可复用的模式,不是单次操作
2. when_to_use 应该明确、具体到触发条件
3. content 应该包含完整的步骤、触发条件和示例
```

- [ ] **Step 2: 运行测试,确认 prompt 改动不影响现有测试**

Run: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/unit/test_review_service.py -v`

Expected: 全部 PASS(prompt 改动不影响 JSON 解析逻辑)。

- [ ] **Step 3: Commit**

```bash
git add backend/skills/prompts/review.txt
git commit -m "feat(review): rewrite prompt with few-shot + anti-patterns + schema (PR-1)"
```

---

### Task 4: 创建 PR-1

- [ ] **Step 1: Push 分支**

```bash
git push -u origin feat/skill-draft-ux-closure
```

- [ ] **Step 2: 创建 PR**

```bash
gh pr create --title "feat(review): Skill Draft UX 闭环 PR-1 — Prompt 质量提升" --body "## 变更

- 重写 \`backend/skills/prompts/review.txt\`,加 few-shot 示例 + anti-patterns + schema 约束
- 新增 \`_validate_skill_schema\` 方法,校验 name regex / description 长度 / when_to_use 长度 / content 结构
- 追加 \`TestSchemaValidation\` 测试类(7 个测试)

## Spec

\`docs/superpowers/specs/2026-09-04-skill-draft-ux-closure-design.md\`

## 测试

\`\`\`bash
pytest backend/tests/unit/test_review_service.py -v
\`\`\`

全部 PASS。"
```

- [ ] **Step 3: 等 CI 绿**

```bash
gh pr checks <PR-number> --watch
```

- [ ] **Step 4: 用户 merge PR**

用户在 GitHub UI merge。

---

# PR-2:i18n 审计 + `/learn` 反馈 i18n(前端)

## File Structure

**Files:**
- Modify: `src/shared/lib/i18n/zh.ts`(追加 14 个 key)
- Modify: `src/shared/lib/i18n/en.ts`(追加 14 个 key)
- Modify: `src/widgets/skills/SkillDraftList.tsx`(13 处硬编码 → 11 个 i18n key)
- Modify: `src/pages/Chat.tsx:253-263`(`handleLearn` 3 处硬编码 → 3 个 i18n key)
- Modify: `src/widgets/skills/__tests__/SkillDraftList.test.tsx`(更新断言)

**Interfaces:**
- Consumes: `useI18n()` hook 返回的 `t()` 函数
- Produces: 14 个新 i18n key(`skill_draft.*` 11 个 + `chat.learn_*` 3 个)

---

### Task 1: 追加 i18n key 到 zh.ts + en.ts

**Files:**
- Modify: `src/shared/lib/i18n/zh.ts:430`(`brand.alt` 后追加)
- Modify: `src/shared/lib/i18n/en.ts`(对应位置追加)

- [ ] **Step 1: 在 `zh.ts` 末尾(`brand.alt` 后,`} as const` 前)追加 14 个 key**

在 `src/shared/lib/i18n/zh.ts` 第 430 行(`'brand.alt': 'Sage 标志',`)后追加:

```typescript
  // ─── Skill Draft (PR-2 UX closure) ─────
  'skill_draft.loading': '加载草稿中...',
  'skill_draft.load_failed': '加载失败: {error}',
  'skill_draft.retry': '重试',
  'skill_draft.no_drafts': '暂无待审草稿',
  'skill_draft.when_to_use': '何时使用: {text}',
  'skill_draft.approve': '批准',
  'skill_draft.reject': '拒绝',
  'skill_draft.approved': '已批准 {name}',
  'skill_draft.approve_failed': '批准失败: {error}',
  'skill_draft.rejected': '已拒绝 {name}',
  'skill_draft.reject_failed': '拒绝失败: {error}',
  'skill_draft.preview': '预览',

  'chat.learn_reviewing': '正在生成技能草稿...',
  'chat.learn_queued': '已加入审核队列 — 查看待审草稿',
  'chat.learn_failed': '审核失败: {error}',
```

- [ ] **Step 2: 在 `en.ts` 对应位置追加相同 14 个 key(英文)**

在 `src/shared/lib/i18n/en.ts` 对应位置追加:

```typescript
  // ─── Skill Draft (PR-2 UX closure) ─────
  'skill_draft.loading': 'Loading drafts...',
  'skill_draft.load_failed': 'Failed to load: {error}',
  'skill_draft.retry': 'Retry',
  'skill_draft.no_drafts': 'No pending drafts',
  'skill_draft.when_to_use': 'When to use: {text}',
  'skill_draft.approve': 'Approve',
  'skill_draft.reject': 'Reject',
  'skill_draft.approved': 'Approved {name}',
  'skill_draft.approve_failed': 'Approve failed: {error}',
  'skill_draft.rejected': 'Rejected {name}',
  'skill_draft.reject_failed': 'Reject failed: {error}',
  'skill_draft.preview': 'Preview',

  'chat.learn_reviewing': 'Reviewing...',
  'chat.learn_queued': 'Review queued — check Pending Drafts',
  'chat.learn_failed': 'Review failed: {error}',
```

- [ ] **Step 3: 运行 TypeScript 类型检查,确认无错**

Run: `npx tsc --noEmit`

Expected: 无错(新 key 同时存在于 zh + en,`TranslationKey` 类型约束满足)。

- [ ] **Step 4: Commit**

```bash
git add src/shared/lib/i18n/zh.ts src/shared/lib/i18n/en.ts
git commit -m "feat(i18n): add 14 keys for skill draft + /learn feedback (PR-2)"
```

---

### Task 2: 更新 SkillDraftList.tsx 使用 i18n

**Files:**
- Modify: `src/widgets/skills/SkillDraftList.tsx`(13 处硬编码 → 11 个 key)

- [ ] **Step 1: 在文件顶部导入 `useI18n`**

在 `src/widgets/skills/SkillDraftList.tsx` 第 13 行(`import { skillDraftsApi, type SkillDraft } from '../../shared/api';`)后追加:

```typescript
import { useI18n } from '../../shared/lib/i18n';
```

- [ ] **Step 2: 在组件内部解构 `t`**

在 `src/widgets/skills/SkillDraftList.tsx` 第 21 行(`const [error, setError] = useState<string | null>(null);`)后追加:

```typescript
  const { t } = useI18n();
```

- [ ] **Step 3: 替换 13 处硬编码文案**

逐处替换:

**Line 44**:`toast.success(`已批准 ${draft.name}`);` → `toast.success(t('skill_draft.approved', { name: draft.name }));`

**Line 46**:`toast.error(`批准失败: ${(err as Error).message}`);` → `toast.error(t('skill_draft.approve_failed', { error: (err as Error).message }));`

**Line 54**:`toast.success(`已拒绝 ${draft.name}`);` → `toast.success(t('skill_draft.rejected', { name: draft.name }));`

**Line 56**:`toast.error(`拒绝失败: ${(err as Error).message}`);` → `toast.error(t('skill_draft.reject_failed', { error: (err as Error).message }));`

**Line 63**:`<p className="text-muted">加载草稿中...</p>` → `<p className="text-muted">{t('skill_draft.loading')}</p>`

**Line 71**:`<p className="text-error">加载失败: {error}</p>` → `<p className="text-error">{t('skill_draft.load_failed', { error })}</p>`

**Line 77**:`重试` → `{t('skill_draft.retry')}`

**Line 86**:`<p className="text-muted">暂无待审草稿</p>` → `<p className="text-muted">{t('skill_draft.no_drafts')}</p>`

**Line 106**:`<strong className="text-text">何时使用:</strong> {draft.when_to_use}` → `<strong className="text-text">{t('skill_draft.when_to_use', { text: '' }).replace(': {text}', '')}</strong> {draft.when_to_use}`

(注意:`when_to_use` key 带 `{text}` 占位符,但这里 label 和 value 是分开的,所以用 `t('skill_draft.when_to_use', { text: '' }).replace(': {text}', '')` 提取 label 部分。或者更简单:直接用 `t('skill_draft.when_to_use_label')` 单独一个 key。但 spec 里没这个 key,所以用现有 key + replace。)

**Line 112**:`aria-label={`Approve ${draft.name}`}` → `aria-label={`${t('skill_draft.approve')} ${draft.name}`}`

**Line 115**:`Approve` → `{t('skill_draft.approve')}`

**Line 120**:`aria-label={`Reject ${draft.name}`}` → `aria-label={`${t('skill_draft.reject')} ${draft.name}`}`

**Line 123**:`Reject` → `{t('skill_draft.reject')}`

- [ ] **Step 4: 运行 TypeScript 类型检查**

Run: `npx tsc --noEmit`

Expected: 无错。

- [ ] **Step 5: Commit**

```bash
git add src/widgets/skills/SkillDraftList.tsx
git commit -m "feat(i18n): replace 13 hardcoded strings in SkillDraftList (PR-2)"
```

---

### Task 3: 更新 Chat.tsx `/learn` 反馈使用 i18n

**Files:**
- Modify: `src/pages/Chat.tsx:253-263`(`handleLearn` 函数)

- [ ] **Step 1: 替换 `handleLearn` 中的 3 处硬编码**

在 `src/pages/Chat.tsx` 第 253-263 行的 `handleLearn` 函数中:

**Line 256**:`toast.info('Reviewing...');` → `toast.info(t('chat.learn_reviewing'));`

**Line 258**:`toast.success('Review queued — check Pending Drafts');` → `toast.success(t('chat.learn_queued'));`

**Line 261**:`toast.error(`Review failed: ${e instanceof Error ? e.message : String(e)}`);` → `toast.error(t('chat.learn_failed', { error: e instanceof Error ? e.message : String(e) }));`

- [ ] **Step 2: 运行 TypeScript 类型检查**

Run: `npx tsc --noEmit`

Expected: 无错。

- [ ] **Step 3: Commit**

```bash
git add src/pages/Chat.tsx
git commit -m "feat(i18n): replace 3 hardcoded strings in Chat.tsx /learn (PR-2)"
```

---

### Task 4: 更新 SkillDraftList.test.tsx 断言

**Files:**
- Modify: `src/widgets/skills/__tests__/SkillDraftList.test.tsx`(更新断言字符串)

- [ ] **Step 1: 更新测试断言**

现有测试已经用 `<I18nProvider defaultLocale="zh">` 包裹,所以断言字符串应该用中文(因为 zh.ts 的 value 是中文)。

检查现有断言:
- Line 61: `expect(screen.getByText(/加载草稿中/i)).toBeInTheDocument();` → ✅ 已匹配 `t('skill_draft.loading')` = `加载草稿中...`
- Line 71: `expect(await screen.findByText(/暂无待审草稿/i)).toBeInTheDocument();` → ✅ 已匹配 `t('skill_draft.no_drafts')` = `暂无待审草稿`
- Line 94: `await screen.findByRole('button', { name: /approve alpha-skill/i });` → ❌ 不匹配,应改为 `/批准 alpha-skill/i`
- Line 110: `await screen.findByRole('button', { name: /reject alpha-skill/i });` → ❌ 不匹配,应改为 `/拒绝 alpha-skill/i`
- Line 150: `await screen.findByRole('button', { name: /approve alpha-skill/i });` → ❌ 同上
- Line 163: `expect(screen.getByRole('button', { name: /重试/i })).toBeInTheDocument();` → ✅ 已匹配 `t('skill_draft.retry')` = `重试`

替换 Line 94, 110, 150:

**Line 94**:`const approveBtn = await screen.findByRole('button', { name: /approve alpha-skill/i });` → `const approveBtn = await screen.findByRole('button', { name: /批准 alpha-skill/i });`

**Line 110**:`const rejectBtn = await screen.findByRole('button', { name: /reject alpha-skill/i });` → `const rejectBtn = await screen.findByRole('button', { name: /拒绝 alpha-skill/i });`

**Line 150**:`const approveBtn = await screen.findByRole('button', { name: /approve alpha-skill/i });` → `const approveBtn = await screen.findByRole('button', { name: /批准 alpha-skill/i });`

- [ ] **Step 2: 运行测试,确认通过**

Run: `npx vitest run src/widgets/skills/__tests__/SkillDraftList.test.tsx`

Expected: 全部 PASS。

- [ ] **Step 3: Commit**

```bash
git add src/widgets/skills/__tests__/SkillDraftList.test.tsx
git commit -m "test(i18n): update SkillDraftList test assertions (PR-2)"
```

---

### Task 5: 创建 PR-2

- [ ] **Step 1: Push 分支**

```bash
git push origin feat/skill-draft-ux-closure
```

- [ ] **Step 2: 创建 PR**

```bash
gh pr create --title "feat(i18n): Skill Draft UX 闭环 PR-2 — i18n 审计 + /learn 反馈" --body "## 变更

- 追加 14 个 i18n key(\`skill_draft.*\` 11 个 + \`chat.learn_*\` 3 个)到 zh.ts + en.ts
- 替换 \`SkillDraftList.tsx\` 13 处硬编码文案为 i18n key
- 替换 \`Chat.tsx\` \`handleLearn\` 3 处硬编码文案为 i18n key
- 更新 \`SkillDraftList.test.tsx\` 断言匹配 i18n 后的中文文案

## Spec

\`docs/superpowers/specs/2026-09-04-skill-draft-ux-closure-design.md\`

## 测试

\`\`\`bash
npx vitest run src/widgets/skills/__tests__/SkillDraftList.test.tsx
\`\`\`

全部 PASS。"
```

- [ ] **Step 3: 等 CI 绿 + 用户 merge**

(同 PR-1)

---

# PR-3:草稿详情预览(前端)

## File Structure

**Files:**
- Create: `src/widgets/skills/SkillDraftDetail.tsx`(新组件,Dialog + MarkdownPreview)
- Modify: `src/widgets/skills/SkillDraftList.tsx`(加 Preview 按钮 + `selectedDraft` state,把 Approve/Reject 移到 modal 内)
- Create: `src/widgets/skills/__tests__/SkillDraftDetail.test.tsx`(新测试)
- Modify: `src/widgets/skills/__tests__/SkillDraftList.test.tsx`(更新测试,Preview 按钮取代直接 Approve/Reject)

**Interfaces:**
- Consumes: `SkillDraft` 类型(from `shared/api`),`Dialog` + `MarkdownPreview` 组件
- Produces: `SkillDraftDetail` 组件(export default),`SkillDraftList` 渲染 Preview 按钮

---

### Task 1: 写 SkillDraftDetail 测试

**Files:**
- Create: `src/widgets/skills/__tests__/SkillDraftDetail.test.tsx`

- [ ] **Step 1: 创建测试文件**

创建 `src/widgets/skills/__tests__/SkillDraftDetail.test.tsx`:

```typescript
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { I18nProvider } from '../../../shared/lib/i18n';
import SkillDraftDetail from '../SkillDraftDetail';

// --------------- mocks --------------- //

vi.mock('../../wiki/MarkdownPreview', () => ({
  MarkdownPreview: ({ content }: { content: string }) => (
    <div data-testid="markdown-preview">{content}</div>
  ),
}));

// --------------- helpers --------------- //

function renderDetail(draft: any, onApprove = vi.fn(), onReject = vi.fn(), onClose = vi.fn()) {
  return render(
    <I18nProvider defaultLocale="zh">
      <SkillDraftDetail draft={draft} onApprove={onApprove} onReject={onReject} onClose={onClose} />
    </I18nProvider>,
  );
}

const makeDraft = () => ({
  id: 'draft-1',
  name: 'test-skill',
  description: 'test description',
  when_to_use: 'when testing the skill',
  content: '# Test Skill\n\n## 步骤\n\n1. Step 1\n\n## 触发条件\n\nWhen testing\n\n## 示例\n\nExample',
  trigger_type: 'complex_turn',
  source_session_id: 'session-abc',
  source_context: {},
  status: 'pending' as const,
  created_at: 1700000000000,
});

// --------------- tests --------------- //

describe('SkillDraftDetail component', () => {
  it('renders draft name + trigger_type badge', () => {
    const draft = makeDraft();
    renderDetail(draft);

    expect(screen.getByText('test-skill')).toBeInTheDocument();
    expect(screen.getByText('complex_turn')).toBeInTheDocument();
  });

  it('renders description + when_to_use', () => {
    const draft = makeDraft();
    renderDetail(draft);

    expect(screen.getByText('test description')).toBeInTheDocument();
    expect(screen.getByText(/when testing the skill/)).toBeInTheDocument();
  });

  it('renders markdown content via MarkdownPreview', () => {
    const draft = makeDraft();
    renderDetail(draft);

    expect(screen.getByTestId('markdown-preview')).toBeInTheDocument();
    expect(screen.getByText(/# Test Skill/)).toBeInTheDocument();
  });

  it('calls onApprove + onClose when Approve button clicked', () => {
    const draft = makeDraft();
    const onApprove = vi.fn();
    const onClose = vi.fn();
    renderDetail(draft, onApprove, vi.fn(), onClose);

    const approveBtn = screen.getByRole('button', { name: /批准/i });
    fireEvent.click(approveBtn);

    expect(onApprove).toHaveBeenCalledWith(draft);
    expect(onClose).toHaveBeenCalled();
  });

  it('calls onReject + onClose when Reject button clicked', () => {
    const draft = makeDraft();
    const onReject = vi.fn();
    const onClose = vi.fn();
    renderDetail(draft, vi.fn(), onReject, onClose);

    const rejectBtn = screen.getByRole('button', { name: /拒绝/i });
    fireEvent.click(rejectBtn);

    expect(onReject).toHaveBeenCalledWith(draft);
    expect(onClose).toHaveBeenCalled();
  });

  it('calls onClose when Cancel button clicked', () => {
    const draft = makeDraft();
    const onClose = vi.fn();
    renderDetail(draft, vi.fn(), vi.fn(), onClose);

    const cancelBtn = screen.getByRole('button', { name: /取消/i });
    fireEvent.click(cancelBtn);

    expect(onClose).toHaveBeenCalled();
  });

  it('does not render when draft is null', () => {
    renderDetail(null);

    expect(screen.queryByText('test-skill')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `npx vitest run src/widgets/skills/__tests__/SkillDraftDetail.test.tsx`

Expected: FAIL(`SkillDraftDetail` 模块不存在)。

- [ ] **Step 3: Commit**

```bash
git add src/widgets/skills/__tests__/SkillDraftDetail.test.tsx
git commit -m "test(skill-draft): add SkillDraftDetail tests (PR-3)"
```

---

### Task 2: 实现 SkillDraftDetail 组件

**Files:**
- Create: `src/widgets/skills/SkillDraftDetail.tsx`

- [ ] **Step 1: 创建组件文件**

创建 `src/widgets/skills/SkillDraftDetail.tsx`:

```typescript
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '../../shared/ui/Dialog';
import { MarkdownPreview } from '../wiki/MarkdownPreview';
import { useI18n } from '../../shared/lib/i18n';
import type { SkillDraft } from '../../shared/api';

interface SkillDraftDetailProps {
  draft: SkillDraft | null;
  onApprove: (draft: SkillDraft) => void;
  onReject: (draft: SkillDraft) => void;
  onClose: () => void;
}

/**
 * SkillDraftDetail — modal preview of a skill draft's full SKILL.md content.
 *
 * Renders the draft's metadata (name, trigger_type, description, when_to_use)
 * and the full content via MarkdownPreview. Provides Approve / Reject / Cancel
 * buttons in the footer.
 *
 * Used by SkillDraftList (PR-3 UX closure).
 */
export default function SkillDraftDetail({
  draft,
  onApprove,
  onReject,
  onClose,
}: SkillDraftDetailProps) {
  const { t } = useI18n();

  if (!draft) return null;

  return (
    <Dialog open={!!draft} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <DialogTitle className="text-lg">{draft.name}</DialogTitle>
            <span className="text-xs text-muted px-1.5 py-0.5 bg-bg-muted rounded">
              {draft.trigger_type}
            </span>
          </div>
          <DialogDescription>{draft.description}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="text-sm">
            <strong className="text-text">{t('skill_draft.when_to_use', { text: '' }).replace(': {text}', '')}</strong>{' '}
            {draft.when_to_use}
          </div>

          <div className="border-t pt-4">
            <MarkdownPreview content={draft.content} />
          </div>
        </div>

        <div className="flex items-center gap-2 justify-end border-t pt-4">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-xs rounded-radius-sm border border-border hover:bg-bg-hover transition-colors"
          >
            {t('common.cancel')}
          </button>
          <button
            type="button"
            onClick={() => onReject(draft)}
            className="px-3 py-1.5 text-xs rounded-radius-sm bg-error/10 text-error hover:bg-error/20 transition-colors"
          >
            {t('skill_draft.reject')}
          </button>
          <button
            type="button"
            onClick={() => onApprove(draft)}
            className="px-3 py-1.5 text-xs rounded-radius-sm bg-success/10 text-success hover:bg-success/20 transition-colors"
          >
            {t('skill_draft.approve')}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2: 运行测试,确认通过**

Run: `npx vitest run src/widgets/skills/__tests__/SkillDraftDetail.test.tsx`

Expected: 全部 PASS。

- [ ] **Step 3: 运行 TypeScript 类型检查**

Run: `npx tsc --noEmit`

Expected: 无错。

- [ ] **Step 4: Commit**

```bash
git add src/widgets/skills/SkillDraftDetail.tsx
git commit -m "feat(skill-draft): add SkillDraftDetail modal component (PR-3)"
```

---

### Task 3: 更新 SkillDraftList 使用 SkillDraftDetail

**Files:**
- Modify: `src/widgets/skills/SkillDraftList.tsx`(加 Preview 按钮 + `selectedDraft` state,移除卡片内 Approve/Reject 按钮)

- [ ] **Step 1: 导入 SkillDraftDetail**

在 `src/widgets/skills/SkillDraftList.tsx` 第 14 行(`import { useI18n } from '../../shared/lib/i18n';`)后追加:

```typescript
import SkillDraftDetail from './SkillDraftDetail';
```

- [ ] **Step 2: 添加 `selectedDraft` state**

在 `src/widgets/skills/SkillDraftList.tsx` 第 22 行(`const [error, setError] = useState<string | null>(null);`)后追加:

```typescript
  const [selectedDraft, setSelectedDraft] = useState<SkillDraft | null>(null);
```

- [ ] **Step 3: 修改 handleApprove / handleReject,成功后关闭 modal**

**Line 43**:`setDrafts((prev) => prev.filter((d) => d.id !== draft.id));` 后追加:

```typescript
      setSelectedDraft(null);
```

**Line 53**:`setDrafts((prev) => prev.filter((d) => d.id !== draft.id));` 后追加:

```typescript
      setSelectedDraft(null);
```

- [ ] **Step 4: 替换卡片底部的 Approve/Reject 按钮为 Preview 按钮**

将 `src/widgets/skills/SkillDraftList.tsx` 第 108-125 行的按钮区域:

```typescript
          <div className="flex items-center gap-2 mt-auto pt-2">
            <button
              type="button"
              onClick={() => handleApprove(draft)}
              aria-label={`${t('skill_draft.approve')} ${draft.name}`}
              className="flex-1 px-3 py-1.5 text-xs rounded-radius-sm bg-success/10 text-success hover:bg-success/20 transition-colors"
            >
              {t('skill_draft.approve')}
            </button>
            <button
              type="button"
              onClick={() => handleReject(draft)}
              aria-label={`${t('skill_draft.reject')} ${draft.name}`}
              className="flex-1 px-3 py-1.5 text-xs rounded-radius-sm bg-error/10 text-error hover:bg-error/20 transition-colors"
            >
              {t('skill_draft.reject')}
            </button>
          </div>
```

替换为:

```typescript
          <div className="mt-auto pt-2">
            <button
              type="button"
              onClick={() => setSelectedDraft(draft)}
              aria-label={`${t('skill_draft.preview')} ${draft.name}`}
              className="w-full px-3 py-1.5 text-xs rounded-radius-sm bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
            >
              {t('skill_draft.preview')}
            </button>
          </div>
```

- [ ] **Step 5: 在组件 return 末尾渲染 SkillDraftDetail**

在 `src/widgets/skills/SkillDraftList.tsx` 第 128 行(`</div>`)前追加:

```typescript
      <SkillDraftDetail
        draft={selectedDraft}
        onApprove={handleApprove}
        onReject={handleReject}
        onClose={() => setSelectedDraft(null)}
      />
```

- [ ] **Step 6: 运行 TypeScript 类型检查**

Run: `npx tsc --noEmit`

Expected: 无错。

- [ ] **Step 7: Commit**

```bash
git add src/widgets/skills/SkillDraftList.tsx
git commit -m "feat(skill-draft): wire up Preview button + SkillDraftDetail modal (PR-3)"
```

---

### Task 4: 更新 SkillDraftList.test.tsx 测试 Preview 流程

**Files:**
- Modify: `src/widgets/skills/__tests__/SkillDraftList.test.tsx`(更新 approve/reject 测试走 Preview → modal 流程)

- [ ] **Step 1: 更新 approve/reject 测试**

现有测试直接点卡片上的 Approve/Reject 按钮,但现在按钮在 modal 内。需要更新:

**Line 84-99**(`approve button calls API and removes draft from list`):

替换为:

```typescript
  it('preview button opens modal, approve calls API and removes draft', async () => {
    const drafts = [makeDraft('d1', 'alpha-skill')];
    listMock.mockResolvedValue({ drafts });
    approveMock.mockResolvedValue({
      status: 'approved',
      skill_name: 'alpha-skill',
      draft_id: 'd1',
    });

    renderDraftList();
    const previewBtn = await screen.findByRole('button', { name: /预览 alpha-skill/i });
    fireEvent.click(previewBtn);

    // Modal opens — find Approve button inside modal
    const approveBtn = await screen.findByRole('button', { name: /批准/i });
    fireEvent.click(approveBtn);

    await waitFor(() => expect(approveMock).toHaveBeenCalledWith('d1'));
    await waitFor(() => expect(screen.queryByText('alpha-skill')).not.toBeInTheDocument());
  });
```

**Line 101-115**(`reject button calls API and removes draft from list`):

替换为:

```typescript
  it('preview button opens modal, reject calls API and removes draft', async () => {
    const drafts = [makeDraft('d1', 'alpha-skill')];
    listMock.mockResolvedValue({ drafts });
    rejectMock.mockResolvedValue({
      status: 'rejected',
      draft_id: 'd1',
    });

    renderDraftList();
    const previewBtn = await screen.findByRole('button', { name: /预览 alpha-skill/i });
    fireEvent.click(previewBtn);

    // Modal opens — find Reject button inside modal
    const rejectBtn = await screen.findByRole('button', { name: /拒绝/i });
    fireEvent.click(rejectBtn);

    await waitFor(() => expect(rejectMock).toHaveBeenCalledWith('d1'));
    await waitFor(() => expect(screen.queryByText('alpha-skill')).not.toBeInTheDocument());
  });
```

**Line 144-156**(`approve failure shows error and keeps draft`):

替换为:

```typescript
  it('approve failure shows error and keeps draft (via modal)', async () => {
    const drafts = [makeDraft('d1', 'alpha-skill')];
    listMock.mockResolvedValue({ drafts });
    approveMock.mockRejectedValue(new Error('network error'));

    renderDraftList();
    const previewBtn = await screen.findByRole('button', { name: /预览 alpha-skill/i });
    fireEvent.click(previewBtn);

    const approveBtn = await screen.findByRole('button', { name: /批准/i });
    fireEvent.click(approveBtn);

    await waitFor(() => expect(approveMock).toHaveBeenCalledWith('d1'));
    // Draft should still be visible after failure
    await waitFor(() => expect(screen.getByText('alpha-skill')).toBeInTheDocument());
  });
```

- [ ] **Step 2: 运行测试,确认通过**

Run: `npx vitest run src/widgets/skills/__tests__/SkillDraftList.test.tsx`

Expected: 全部 PASS。

- [ ] **Step 3: Commit**

```bash
git add src/widgets/skills/__tests__/SkillDraftList.test.tsx
git commit -m "test(skill-draft): update SkillDraftList tests for Preview flow (PR-3)"
```

---

### Task 5: 创建 PR-3

- [ ] **Step 1: Push 分支**

```bash
git push origin feat/skill-draft-ux-closure
```

- [ ] **Step 2: 创建 PR**

```bash
gh pr create --title "feat(skill-draft): Skill Draft UX 闭环 PR-3 — 草稿详情预览" --body "## 变更

- 新建 \`SkillDraftDetail.tsx\` 组件(Dialog + MarkdownPreview 渲染完整 SKILL.md)
- \`SkillDraftList.tsx\` 卡片底部 Approve/Reject 按钮改为 Preview 按钮,审批移到 modal 内
- 新建 \`SkillDraftDetail.test.tsx\`(7 个测试)
- 更新 \`SkillDraftList.test.tsx\` 测试 Preview → modal → Approve/Reject 流程

## Spec

\`docs/superpowers/specs/2026-09-04-skill-draft-ux-closure-design.md\`

## 测试

\`\`\`bash
npx vitest run src/widgets/skills/__tests__/SkillDraftDetail.test.tsx
npx vitest run src/widgets/skills/__tests__/SkillDraftList.test.tsx
\`\`\`

全部 PASS。"
```

- [ ] **Step 3: 等 CI 绿 + 用户 merge**

(同 PR-1)

---

# 完成

3 个 PR 全部合到 main 后,Sub-project A(Skill Draft UX 闭环)完成。

**后续**:
- Sub-project B:后台通知子系统(独立 spec)
- Sub-project C:草稿历史(独立 spec)
