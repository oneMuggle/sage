// src/shared/lib/shortcuts.ts
//
// U18 (round4 批次 E): 应用快捷键注册表 —— ShortcutHelpOverlay 的数据源。
// 键位与各处实现保持同步：App.tsx(Cmd/Ctrl+K)、Layout.tsx(Cmd/Ctrl+B)、
// CommandPalette.tsx(Cmd/Ctrl+1..9)、InputCard.tsx(Enter/↑/Esc)、
// useEmacsKeybindings.ts(Emacs 键位)、ApprovalDialog.tsx(Esc=拒绝)。

export interface ShortcutEntry {
  /** 展示用键位（macOS/Windows 通用写法，Ctrl(Cmd) 表示平台修饰键） */
  keys: string;
  description: string;
}

export interface ShortcutGroup {
  group: string;
  items: ShortcutEntry[];
}

export const SHORTCUT_GROUPS: ShortcutGroup[] = [
  {
    group: '全局',
    items: [
      { keys: 'Ctrl(Cmd) + K', description: '打开/关闭命令面板' },
      { keys: 'Ctrl(Cmd) + 1..9', description: '命令面板内跳转到第 N 个会话' },
      { keys: 'Ctrl(Cmd) + B', description: '折叠/展开侧边栏' },
      { keys: 'Shift + /', description: '打开本快捷键帮助' },
    ],
  },
  {
    group: '消息输入',
    items: [
      { keys: 'Enter', description: '发送消息' },
      { keys: 'Shift + Enter', description: '插入换行' },
      { keys: '↑（空输入时）', description: '编辑上一条发送过的消息' },
      { keys: 'Esc', description: '关闭斜杠/@ 菜单' },
    ],
  },
  {
    group: '输入框 Emacs 键位',
    items: [
      { keys: 'Ctrl + A / E', description: '光标移到行首 / 行尾' },
      { keys: 'Ctrl + K', description: '删除光标到行尾（有选区时删除选区）' },
      { keys: 'Ctrl + U', description: '删除光标到行首' },
      { keys: 'Ctrl + W', description: '向前删除一个词' },
    ],
  },
  {
    group: '审批对话框',
    items: [{ keys: 'Esc', description: '拒绝当前审批请求（等同点击拒绝）' }],
  },
];
