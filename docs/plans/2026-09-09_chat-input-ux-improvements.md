# 2026-09-09 chat 输入框 UX 优化

## 背景与目标

`src/widgets/chat/InputCard.tsx` 是 Sage 桌面端的聊天主输入框，目前存在以下体验问题：

1. **Ctrl+A 全选失效**（用户反馈）—— `useEmacsKeybindings` 把 Ctrl+A 截获为「光标移到行首」(Emacs 习惯)，但 Windows/Linux 上 Ctrl+A 是「全选」语义，preventDefault 后浏览器原生行为不再触发，用户必须逐字删除。
2. **IME 合成期间按 Enter 误发送** —— 中/日/韩用户用输入法时，Enter 用来确认候选词，会被误识别为「发送消息」。
3. **Ctrl+Backspace 在 Windows 上无反应** —— Windows 用户习惯 `Ctrl+Backspace = 删除前一个词`，当前 hook 只支持 `Ctrl+W`。
4. **无字符计数提示** —— 长 prompt 接近模型上下文上限时无视觉反馈。

## 与已存在代码的关系

> 草稿持久化（C 项）**已由 OpenWorker U13 通过 `useSessionDraft` 实现**（`src/shared/lib/hooks/useSessionDraft.ts`，ChatInput.tsx:112 已接入）。本计划不重复实现。

## 涉及的文件与模块

| 文件 | 改动 |
|---|---|
| `src/shared/lib/hooks/useEmacsKeybindings.ts` | 移除 `case 'a':`；新增 `case 'Backspace':` |
| `src/shared/lib/hooks/__tests__/useEmacsKeybindings.test.ts` | 4 个 Ctrl+A 用例改写为「passes through」语义；新增 Ctrl+Backspace 用例 |
| `src/widgets/chat/InputCard.tsx` | Enter 守卫 `nativeEvent.isComposing`；新增字符计数 UI |
| `src/widgets/chat/__tests__/InputCard.test.tsx` | 改写 Ctrl+A 用例；新增 IME / 字符计数用例 |
| `src/shared/lib/i18n/zh.ts`、`en.ts` | 新增 `chat.charCount` 文案 |

## 技术方案

### A. Ctrl+A 走浏览器默认

`useEmacsKeybindings.ts:178-181` 删除整段 `case 'a'`，浏览器原生 select-all 恢复生效。
hook 注释中的「Cmd+A 在 macOS 不被拦截」承诺不变：macOS 用户仍可 Cmd+A 全选；Windows 用户 Ctrl+A = select-all。
其余 Emacs 键位（Ctrl+E/K/U/W、Alt+B/F）保留。

### B. IME 合成安全

React 18+ 在 `compositionend` 之前不应触发提交，但 Enter 在合成结束瞬间可能抢先触发 keydown。
守卫（仅在 InputCard 局部加，不动 hook）：

```ts
if (e.key === 'Enter' && !e.shiftKey) {
  if (e.nativeEvent.isComposing) return; // IME 候选确认不发送
  e.preventDefault();
  onSubmit();
}
```

`nativeEvent.isComposing` 是 W3C 标准，所有主流 IME（拼音 / 假名 / 韩文）遵守。

### D. Ctrl+Backspace

在 `useEmacsKeybindings` 的 `ctrlOnly` 分支新增：

```ts
case 'Backspace': {
  event.preventDefault();
  if (hasSelection) {
    killRange(start, end);
  } else if (start > 0) {
    killRange(Math.max(findWordBackward(text, start), lineStartOf(text, start)), start);
  }
  return true;
}
```

行为对齐 `Ctrl+W`，但用 `Backspace` 键触发，照顾 Windows 习惯。
不跨行删除（与 Ctrl+W 一致）。

### E. 字符计数

阈值常量 `CHAR_WARN_THRESHOLD = 4000`：

- `value.length > 3000`：灰色「X / 4000」提示
- `value.length > 4000`：变红
- 其余情况不渲染

UI 位置：textarea 与按钮行下方（与 `hint` 同位 / 紧邻），不抢占输入高度。

## 实施步骤

- [x] 同步 main 分支（rebase）
- [x] 建 `feat/chat-input-ux-improvements` 分支
- [x] 写计划文档（本文件）
- [ ] A：useEmacsKeybindings 移除 Ctrl+A + 改写 4 个用例
- [ ] D：useEmacsKeybindings 加 Ctrl+Backspace + 新增用例
- [ ] B：InputCard Enter 守卫 + 1 个用例
- [ ] E：InputCard 字符计数 + i18n 2 文案 + 1 个用例
- [ ] `npm run typecheck` 通过
- [ ] `npm run test:run` 全绿
- [ ] `npm run lint` 通过
- [ ] 提交 + push + 开 PR

## 风险评估

| 风险 | 缓解 |
|---|---|
| Ctrl+A 改动破坏 Power user 的 Emacs 习惯 | hook 仍保留 Ctrl+E/K/U/W；macOS 用户仍可 Cmd+A；emacs user 可在 Issue 里提加 Option+A 备份 |
| IME 守卫漏判（小语种 / 罕见 IME） | `nativeEvent.isComposing` 是 W3C 标准；如漏报只会「多按一次 Enter」，不破坏正确路径 |
| 字符计数阈值 4000 不准 | 常量集中管理，改 UI 即可 |
| 现有 4 个测试直接断言 Ctrl+A → 行首，会失败 | 改写为「passes through」而非删除，保留测例总数 |
| C 项（草稿持久化）误以为需要重做 | 文档明确标注已存在；不重复实现 |
