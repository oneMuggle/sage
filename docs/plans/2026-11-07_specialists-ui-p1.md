# 专家页面 P1 优化（筛选 + 搜索 + 空态）

- 日期：2026-11-07
- 分支：`feat/specialists-ui-p1`
- worktree：`.worktrees/feat-specialists-ui-p1`（后端 8882 / 前端 1537）

## 背景与目标

P0（卡片 UX）已双分支落地。本计划交付 P1 的信息架构优化（纯前端本地过滤，不新增后端 API）：

1. **分类筛选**：全部 / 内置 / 我的 / 导入（基于 `AgentProfile.source`）
2. **搜索**：按名称 / 标语本地模糊过滤
3. **卡片丰富信息**：元信息行显示技能数（`agent.skills.length`，零成本）
4. **空态增强**：
   - 无专家：引导文案 + 主 CTA「从模板创建」
   - 搜索无结果：「无匹配专家」+ 清除搜索
   - 筛选无结果：「该分类下暂无专家」+ 清除筛选

> 知识绑定数 / 最近使用时间需要后端新字段（count 聚合 / last_used_at），不在本计划范围（P2 或独立后端 PR）。

## 涉及文件与模块

- `src/pages/Specialists.tsx`：工具栏（分类 Tab + 搜索）+ 派生过滤列表 + 空态分支
- `src/widgets/specialists/SpecialistCard.tsx`：元信息行加技能数
- `src/pages/__tests__/Specialists.test.tsx`（新增）：筛选 / 搜索 / 空态回归测试

## 技术方案

### 筛选与搜索（本地派生）

```tsx
type SourceFilter = 'all' | 'builtin' | 'user' | 'imported';

const filteredAgents = useMemo(() => {
  const q = searchQuery.trim().toLowerCase();
  return agents.filter((a) => {
    if (sourceFilter !== 'all' && (a.source ?? 'user') !== sourceFilter) return false;
    if (!q) return true;
    const haystack = `${a.name} ${readTagline(a)}`.toLowerCase();
    return haystack.includes(q);
  });
}, [agents, sourceFilter, searchQuery]);
```

标签：

- 全部（默认）
- 内置（source = builtin）
- 我的（source = user）
- 导入（source = imported）

### 工具栏 UI

```tsx
<div className="mb-4 flex items-center gap-2">
  {/* 分类 Tabs */}
  <div role="tablist" className="flex items-center gap-1 rounded-lg border border-border bg-bg-subtle/50 p-1">
    {SOURCE_FILTERS.map(({ key, label }) => (
      <button role="tab" aria-selected={sourceFilter === key} ...>{label}</button>
    ))}
  </div>
  {/* 搜索 */}
  <input
    type="search"
    data-testid="specialists-search"
    placeholder="搜索专家名称或标语…"
    value={searchQuery}
    onChange={(e) => setSearchQuery(e.target.value)}
    className="..."
  />
</div>
```

### 空态

三态：

1. `agents.length === 0`（没有任何专家）→ 引导 + 主 CTA：
   ```
   🎨 还没有专家
   创建一个专家，让它帮你完成专业任务。
   [✨ 从模板创建]  [➕ 新建专家]
   ```
2. `filteredAgents.length === 0 && (searchQuery || sourceFilter !== 'all')` → 「没有匹配的专家」+ 按钮「清除筛选」。
3. 正常 → 网格渲染。

### 卡片技能数

元信息行（`{sourceLabel} · {roleLabel} · {permission}`）后追加 `· {skillCount} 项技能`；无技能不显示。

## 实施步骤

- [x] M1 SpecialistCard 元信息加技能数
- [x] M2 Specialists 页筛选 Tab + 搜索 + 派生过滤
- [x] M3 空态增强（无专家 / 无匹配）
- [x] M4 新增 `Specialists.test.tsx`（筛选 / 搜索 / 清空 / 空态）
- [x] M5 验证：tsc / eslint / prettier / vitest
- [ ] M6 提交推送开 PR；合并后同步 win7 并归档文档

## 风险评估

| 风险                       | 缓解                                                               |
| -------------------------- | ------------------------------------------------------------------ |
| 页面测试需 mock 大量子组件 | mock `agentsApi` + 轻量子组件替身（SpecialistCard 用替身渲染名称） |
| 搜索性能                   | 本地数组 + useMemo，专家数量级小（几十），无问题                   |
| 与 P0 卡片改动冲突         | SpecialistCard 仅追加一行元信息，冲突面小                          |
