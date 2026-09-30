# UX-IA Round 1 · 批次 D：会话控件移入输入框

## 1. 目标
参考 ChatGPT / Claude 的 composer 布局：跟"这一轮怎么发"相关的控件（模型、上下文占用、权限档位）放在发送按钮旁边，页面头部只保留会话身份信息。

## 2. 入口迁移
| 控件 | 原位置 | 新位置 |
|---|---|---|
| SessionModelPicker（模型） | 页头左侧 | 输入框右下，紧挨发送按钮 |
| ContextMeter（上下文占用） | 页头左侧 | 输入框右下 |
| PermissionModeSwitch（权限三档） | 页头右侧 | 输入框右下 |
| SessionUsageBadge / ProjectBadge / 分支 / 临时对话 | 页头 | **不变** |

## 3. 实现
- `InputCard` 新增 `composerControls` 插槽（`data-testid=composer-controls`），渲染在发送 / 停止按钮左侧，流式输出期间仍然可见。
- `ChatInput` 通过 `Pick<InputCardProps,'composerControls'>` 透传，不超过 800 行上限。
- `ContextMeter` 和 `PermissionModeSwitch` 的弹层由 `top-full` 改为 `bottom-full`（向上弹出），避免在窗口底部被裁掉。这两个组件只在 Chat 使用。

## 4. 测试
- 新增 `InputCard.composerControls.test.tsx`（3 例）；`src/widgets/chat` 与 `src/pages` 下 803 个测试全部通过。

## 5. PR
- main：#1850（`f1b1bc3d4`）
- win7（release/win7）：#1851
