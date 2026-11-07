# 专家卡片 UX 优化（P0）

- 日期：2026-11-07
- 分支：`feat/specialist-card-ux`
- worktree：`.worktrees/feat-specialist-card-ux`（后端 8879 / 前端 1534）

## 背景与目标

当前专家页面（`/specialists`）存在以下 UX 问题：

1. **卡片底部 7 个平级按钮**（试聊/编辑/知识/资产/版本/评测/导出），主次不分，视觉噪音大
2. **卡片视觉同质化**：扁平 border + bg-surface，缺乏辨识度
3. **禁用态不明显**：仅 opacity-60，缺少灰度+图标+tooltip
4. **主操作不突出**：「试聊」应更大更显眼

参考主流 AI 应用（GPTs Store / Coze Bot 广场 / Character.ai）的设计模式，本计划交付 P0 优化：

- 主操作放大：「试聊」改为主按钮，其他操作收进更多菜单
- 卡片色调：基于 avatar emoji 生成柔和渐变背景，增加视觉辨识度
- 禁用态增强：灰度 + 禁用图标 + tooltip

## 涉及文件与模块

**前端**
- `src/widgets/specialists/SpecialistCard.tsx`：主操作 + 更多菜单 + 色调 + 禁用态
- `src/widgets/specialists/__tests__/SpecialistCard.test.tsx`：更新测试（DOM 结构变化）

**可能新增**
- `src/widgets/specialists/SpecialistCardMoreMenu.tsx`：更多菜单下拉组件（可选）

**参考组件**
- `src/shared/ui/Button.tsx`：Button 组件（primary/secondary/ghost）
- `src/shared/ui/ContextMenu.tsx`：Radix ContextMenu（更多菜单）
- `src/shared/ui/Tooltip.tsx`：Radix Tooltip（禁用态提示）

## 技术方案

### 1. 主操作放大 + 更多菜单

**结构**
```
┌─────────────────────────────┐
│  🤖 写作专家          v1   │
│     专业写作助手...         │
│                             │
│  🎯 技能: 3    📚 知识: 2   │
│                             │
│  ┌─────────────────────┐   │
│  │    💬 开始试聊       │   │  ← 主操作，大按钮
│  └─────────────────────┘   │
│                             │
│  编辑  知识  资产  ···     │  ← 次操作 + 更多菜单
└─────────────────────────────┘
```

**实现**
- 试聊按钮：`<Button variant="primary" size="lg" className="w-full">💬 开始试聊</Button>`
- 次操作：编辑/知识/资产（图标按钮，hover 显示 tooltip）
- 更多菜单：版本/评测/导出（Radix ContextMenu 或 DropdownMenu）

### 2. 卡片色调

**算法**
```typescript
function generateCardTone(avatar: string): React.CSSProperties {
  const hue = (avatar.charCodeAt(0) * 37) % 360;
  return {
    background: `linear-gradient(135deg, hsl(${hue} 80% 95%), hsl(${hue + 30} 80% 90%))`,
  };
}
```

- 基于 avatar 首字符生成 HSL 色相
- 浅色模式下：饱和度高（80%），亮度高（95%/90%）
- 深色模式下：降低饱和度（40%），降低亮度（15%/10%）
- 通过 Tailwind `dark:` 前缀或 CSS 变量实现

### 3. 禁用态增强

**视觉**
```
┌─────────────────────────────┐
│  🤖 写作专家    ⚠️ 已禁用   │  ← 灰度 + 禁用图标
│     专业写作助手...         │
│                             │
│  ┌─────────────────────┐   │
│  │  💬 开始试聊        │   │  ← 按钮 disabled + tooltip
│  └─────────────────────┘   │
└─────────────────────────────┘
```

**实现**
- 卡片容器：`filter: grayscale(100%)` + `opacity: 0.7`
- 顶部右侧：禁用徽章 `<span className="text-warning">⚠️ 已禁用</span>`
- 按钮：`disabled` 属性 + `<Tooltip>请先在智能体页启用</Tooltip>`

### 4. 测试更新

- 现有测试可能依赖 DOM 结构（按钮顺序/类名）
- 更新 `SpecialistCard.test.tsx`：
  - 主操作按钮存在且可点击
  - 更多菜单存在
  - 禁用态显示灰度 + 徽章 + tooltip
  - 色调生成（可选，快照测试）

## 实施步骤

- [ ] M1 重构 SpecialistCard 结构（主操作 + 次操作分离）
- [ ] M2 添加色调生成函数（基于 avatar 首字符）
- [ ] M3 增强禁用态（灰度 + 徽章 + tooltip）
- [ ] M4 更新/新增测试
- [ ] M5 验证：tsc / eslint / prettier / vitest
- [ ] M6 提交推送开 PR

## 风险评估与依赖

| 风险 | 缓解 |
|---|---|
| 现有测试失败 | 更新测试用例，确保 DOM 结构变化后测试通过 |
| 深色模式色调不协调 | 使用 CSS 变量或 Tailwind `dark:` 前缀，手动验证深色模式 |
| Radix 组件未安装 | 检查 `package.json`，若缺失则 `npm install @radix-ui/react-dropdown-menu` |
| 用户偏好未考虑 | P0 为最小可行优化，后续 P1/P2 可加用户偏好（如关闭色调） |

## 验收标准

- 卡片主操作「试聊」占据主要视觉（大按钮）
- 次操作收进更多菜单（减少视觉噪音）
- 每个卡片有独特色调（基于 avatar）
- 禁用态明显（灰度 + 徽章 + tooltip）
- 测试全过（tsc / eslint / prettier / vitest）
- CI 全绿

## 后续（P1/P2，本计划不实施）

- P1：分类筛选 + 搜索 + 卡片丰富信息（技能数/知识数/最近使用）+ 空态增强
- P2：常用专家置顶 + 卡片点击进入详情页 + 批量操作 + 视觉微动效
