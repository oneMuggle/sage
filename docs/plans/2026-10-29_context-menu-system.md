# 右键上下文菜单体系优化方案

> 日期：2026-10-29
> 状态：**待评审**（方案确认前不进入实施）
> 适用分支：`main` 与 `release/win7` 双方同步（纯前端 + Electron 主进程改动，无 Python 3.8 适配面）
> 参考基线：ChatGPT / Claude / Cherry Studio / Chatbox / Cursor (VS Code) / Notion AI

---

## 1. 背景与目标

### 1.1 背景

调研结论（详见第 2 节证据）：

1. **渲染层目前没有任何自定义右键菜单**。`src/`、`electron/`、`e2e/` 全量搜索 `onContextMenu` / `contextmenu` / `right-click` 零命中。Electron 21 不会提供 Chromium 默认右键菜单，因此**桌面端在页面内右键是完全无反应的**——包括文本输入框（剪切/复制/粘贴都只能靠快捷键）。
2. **文档已经"承诺"了右键能力**，但产品并未实现：`src/content/help/chat.md`（会话"右键删除/重命名/导出"）、`src/content/help/getting-started.md`、`docs/user-manual/03-wiki.md`（Wiki 文件树"右键新建/删除/重命名"）。这构成明确的用户预期落差，也对齐了后端已有能力（见 7.6）。
3. **动作 handler 其实已经齐备**：消息操作栏、会话项、技能卡、文件变更卡、产物查看器、项目行都已有完整动作组，且 handler 已提升到页面层。右键菜单本质是"同一批动作的第二入口"，改造成本低、收益直接。
4. **菜单/浮层实现碎片化**：至少 13 处手写弹层（`ComposerPlusMenu`、`SessionSessionMenu`、`SessionSettingsMenu`、`PermissionModeSwitch`、`RightPanel` 选项浮层、`WorkbenchProjectList` 行菜单、`GitStatusSection` 更多菜单、`TodoRowEditor` 日期浮层、`AtFileMenu` 等），各自重复实现"外部点击关闭 + Escape + 定位"。再手写一套右键菜单只会加剧碎片化。

### 1.2 目标

- **G1** 桌面端所有主要交互对象右键都有符合直觉的菜单：会话列表、聊天消息、代码块、文件引用/附件、Wiki 文件树、右栏产物/变更卡、输入框（原生兜底）。
- **G2** 菜单动作 100% 复用既有 handler；只新增少量轻量工具动作（复制路径、复制为 Markdown 围栏等）和必要 IPC，不重写业务逻辑。
- **G3** 建立**唯一**的右键菜单基座 + 声明式菜单描述（spec），后续新页面接入只需写一份 spec。
- **G4** 键盘可达（`Shift+F10` / 菜单键 / 方向键 / Escape）、ARIA 合规、中英双语文案。
- **G5** 不回归现有左键/hover/双击行为；菜单与划线引用按钮、虚拟列表、流式渲染互不干扰。

### 1.3 非目标（明确不做）

- ❌ 用户可自定义菜单项/顺序（YAGNI）。
- ❌ 右键多选批量操作（会话已有归档等批量入口，不在此扩展）。
- ❌ 一次性迁移全部 13 处手写左键浮层到统一基座（后续可渐进，不在本期）。
- ❌ 应用内区域使用 OS 原生菜单（仅可编辑控件保留原生，见 6.5）。
- ❌ 新增后端业务 API（Wiki 写操作已有，见 7.6）。

---

## 2. 现状调研（证据）

### 2.1 渲染层：零右键菜单

- 全仓库 `onContextMenu` / `contextmenu` / `button === 2` / `which === 3` 在 `src/`、`electron/`、`e2e/`、`tests/` 均为 0 命中。
- 现有"菜单"全部是左键触发的下拉/浮层。

### 2.2 Electron 侧

| 位置 | 内容 |
|---|---|
| `electron/menu.ts:16-64` | 应用菜单：文件（退出/关闭）、帮助（打开日志目录、复制日志路径） |
| `electron/tray.ts:62-96` | 托盘右键原生菜单：显示 Sage / 导出诊断包… / 退出 |
| `electron/main.ts:1110-1119` | 主窗口 `webPreferences`（contextIsolation、sandbox、preload） |
| `electron/main.ts:1148-1246` | webContents 事件仅 will-navigate / console-message / did-finish-load / did-fail-load / render-process-gone / unresponsive |

**没有** `webContents.on('context-menu')`、**没有** `Menu.popup()`、**没有** 开发者"检查元素"右键项。`electron/preload.ts` 只暴露 `sage:invoke` / `sage:event:*` / 窗口控制，无菜单 IPC。

### 2.3 可复用基础设施

| 能力 | 位置 | 说明 |
|---|---|---|
| Radix DropdownMenu 封装 | `src/shared/ui/DropdownMenu/DropdownMenu.tsx` | Item/Separator/Shortcut/Checkbox/Radio/Sub 样式齐备，但仅 1 个消费方（`DeliverySendGroup.tsx`）；未从 `src/shared/ui/index.ts` 导出 |
| Radix Popover / Select / Dialog / Tooltip | `src/shared/ui/*` | 均已有封装 |
| Promise 化确认框 | `src/shared/ui/ConfirmDialog/confirmService.ts` + `ConfirmDialogHost.tsx` | 危险动作统一入口 |
| 两步删除按钮 | `src/widgets/sidebar/TwoStepDelete.tsx` | 会话/消息/技能三处复用 |
| Toast | `src/app/providers/ToastProvider.tsx`（sonner），54 处使用 | 结果反馈统一 |
| 划词引用 | `src/features/chat/selectionQuote.ts:78-96` + `SelectionQuoteButton.tsx` | 已有选区定位与"引用到输入框"链路 |
| i18n | `src/shared/lib/i18n/`（zh/en，分域词典） | 大量组件仍是硬编码中文，新菜单应走词典 |
| 剪贴板 | 无统一工具 | 各处直接 `navigator.clipboard.writeText` |

### 2.4 动作来源清单（右键菜单的直接复用对象）

| 界面对象 | 组件 | 已有动作 |
|---|---|---|
| 聊天消息 | `src/widgets/chat/MessageActionBar.tsx`、`src/pages/chat/useChatMessageActions.ts` | 复制、朗读、反馈、重新生成、编辑重发、引用到输入框；分叉、回滚、存记忆、两步删除 |
| 会话列表项 | `src/widgets/session/SessionItem.tsx:411-460` | 导出 HTML、导出 Markdown、置顶、两步删除；双击 inline 重命名（`:245-262`） |
| 代码块 | `src/widgets/chat/ShikiCodeBlock.tsx` | 复制、自动换行、折叠 |
| 表格 | `src/widgets/chat/MessageMarkdownParts.tsx`（MarkdownTable） | 复制表格（TSV） |
| 文件变更卡 | `src/widgets/chat/changes/FileChangeCard.tsx` | 接受、回退、切换 diff、在编辑器打开、在面板打开 |
| 产物 | `src/widgets/chat/artifacts/ArtifactRow.tsx`、`ArtifactViewer.tsx` | 打开、在文件管理器显示（`revealArtifact`）、复制路径、版本历史 |
| Office 文档行 | `src/features/office/OfficeDocumentList.tsx`、`useOfficeDocuments.ts` | 归档、恢复、快照、另存为、打开、在文件夹中显示（`office:show-in-folder`） |
| 技能卡 | `src/widgets/skills/SkillCard.tsx` | 钉住、归档、历史、两步删除 |
| 项目行 | `src/widgets/sidebar/sections/WorkbenchProjectList.tsx:306-420` | 项目设置、里程碑、项目规则、初始化目录、复制路径、移除 |
| Todo 行 | `src/pages/todo/TodoRowEditor.tsx`、`src/widgets/todo/TodoItem.tsx` | 完成、inline 编辑、优先级、截止日期、删除 |

### 2.5 文档与实现不一致（实施后需对齐）

- `src/content/help/chat.md:20,79,86,124`：会话列表"右键删除/重命名/导出"——实际为 hover 图标 + 双击重命名。
- `src/content/help/getting-started.md:54`：同上。
- `docs/user-manual/03-wiki.md:55`：Wiki 树"右键新建/删除/重命名"——实际无右键（但后端 API 已具备，见 7.6）。
- `docs/mcp-sage-ui-round2-optimization-plan-20261010.md:167` 提到的 `ProjectContextMenu.tsx` 代码中不存在。

---

## 3. 主流 AI 应用参考

| 应用 | 会话列表 | 消息 | 代码块 | 选区 | 备注 |
|---|---|---|---|---|---|
| **ChatGPT** | ⋯ 菜单：重命名 / 置顶 / 归档 / 删除（+共享、移动到项目） | 无右键（hover 动作按钮） | 复制 | — | 侧栏支持排序、筛选、固定 |
| **Claude** | 重命名 / 收藏 / 加入项目 / 删除 | hover 复制 / 重试 | 复制 | — | |
| **Cherry Studio** | 重命名 / 置顶 / 删除 / 导出 / 复制 | **支持**：复制 / 引用 / 编辑 / 重新生成 / 删除 / 分支 | 复制 / 下载 | 复制 / 引用（**无选区时禁用而非隐藏**） | 选区感知右键菜单，发现性最佳实践 |
| **Chatbox** | 重命名 / 删除 / 导出 | 复制 / 删除 / 重新生成 | — | — | |
| **Cursor / VS Code** | 资源管理器完整菜单：新建 / 重命名 / 删除 / 复制路径 / 在文件夹中显示 | 复制 | 复制 | "Add to Chat" / Explain | 桌面端右键重度使用 |
| **Notion AI** | — | — | — | "Ask AI" / 块级转换 | 块级右键 |

**归纳**：

1. 桌面 AI 客户端普遍把「重命名 / 置顶 / 删除 / 导出 / 复制 / 引用 / 重新生成 / 分支」作为右键核心动作——这些 Sage 全部已有 handler。
2. 消息级右键正在成为桌面客户端差异化能力（Cherry Studio 的选区感知菜单是可直接借鉴的范式）。
3. 危险操作一律红色 + 二次确认；菜单项附快捷键提示（仅显示真实绑定的快捷键，不显示假提示）。
4. 右键菜单是"高频管理动作的加速器"，但**不替代** hover 按钮——可发现性仍由可见控件承担。

参考资料：

- ChatGPT 会话菜单（Rename/Pin/Archive/Delete）：https://dev.to/robert_breen_d96e41ecd765/chatgpt-delete-the-chat-clear-the-memory-then-use-temporary-chat-a-cleanup-for-when-client-jhd
- ChatGPT 历史管理（Pin/Archive 语义）：https://aitoolsguidebook.com/en/articles/chatgpt-organize-chats/
- Cherry Studio 消息动作与右键菜单（选区感知、无选区禁用）：https://deepwiki.com/CherryHQ/cherry-studio-app/6.4-message-actions-and-context-menu
- Cherry Studio 消息右键菜单无选区时的发现性改进：https://blog.gitcode.com/1952f29fd2b2165852c12952b92f9725.html

---

## 4. 设计原则

1. **单一基座**：所有右键菜单走同一组件 + 同一套样式原子，禁止再手写第三套浮层。
2. **动作复用**：菜单项只调用既有 handler；文案/禁用态随对象类型与状态变化，不新增业务分支。
3. **上下文感知**：用户消息 vs 助手消息 vs 流式中；置顶 vs 未置顶；有选区 vs 无选区（采用"禁用态"而非隐藏，借鉴 Cherry Studio）。
4. **渐进增强**：hover 按钮/双击重命名保持不变；右键为加速入口，同时兑现文档中已宣称的能力。
5. **键盘与无障碍**：Radix 提供 menu 语义与方向键导航；Trigger 同时响应 `Shift+F10` / 上下文菜单键；危险项 `variant=destructive`。
6. **原生兜底**：可编辑控件（输入框、CodeMirror、xterm 隐藏 textarea）使用 Electron 原生菜单（剪切/复制/粘贴/全选/撤销/重做），不重造文本编辑语义。
7. **性能**：菜单项 spec 在**打开时**惰性构建（流式 token 高频渲染不重算）；Portal 仅在打开时渲染；虚拟列表（>120 条会话）每行只包一层 Trigger。
8. **i18n**：新增 `contextMenu.*` 词典域，中英双语；不延续硬编码中文。

---

## 5. 技术选型

### 方案 A（推荐）：新增 `@radix-ui/react-context-menu`，封装统一基座

- 与现有 Radix 栈（DropdownMenu/Popover/Select/Dialog）同源，样式原子可直接共享。
- 自带：指针定位与视口碰撞翻转、子菜单、checkbox/radio、键盘/typeahead 导航、ARIA `menu/menuitem`、焦点归还。
- 体积小、MIT；Chromium 106（Electron 21 / Win7）完全兼容（不依赖 popover API、`:has()` 等新特性）。
- 成本：`package.json` + lockfile 新增一个依赖，双分支同步 cherry-pick。

### 方案 B：复用现有 DropdownMenu 受控打开（零新依赖）

- 用受控 `open` + 在光标处渲染零尺寸 Trigger 模拟锚点。
- 缺点：Radix DropdownMenu 的定位锚定 Trigger 而非光标（文本选区场景需 hack）；`Shift+F10`/菜单键支持要自写；与 DropdownMenu 语义混用，后续维护两套心智。
- 结论：可作为"禁止新增依赖"时的降级方案，不作为首选。

### 方案 C：全量 Electron 原生菜单（`webContents.on('context-menu')` + IPC 下发模板）

- 优点：OS 原生观感、零渲染层依赖。
- 缺点：与应用设计系统割裂（Win7 原生菜单尤其陈旧）；动态启用态/checkbox 需 IPC 往返；无法用组件测试覆盖；浏览器模式（Vite 开发）不可用。
- 结论：**仅用于可编辑控件兜底**（混合策略），不用于应用内区域。

**混合策略（A + C 的裁剪）**：应用内对象 → 自绘 Radix 菜单；可编辑控件 → 主进程原生菜单。

---

## 6. 架构与接口设计

### 6.1 模块布局

```
src/shared/ui/ContextMenu/
  ContextMenu.tsx        // Radix 封装：Root/Trigger/Content/Item/CheckboxItem/RadioItem/Separator/Label/Sub/Shortcut
  ContextMenuItems.tsx   // 声明式渲染器：items: ContextMenuItemSpec[] → 菜单树（含子菜单）
  types.ts               // ContextMenuItemSpec
  menuClasses.ts         // 从 DropdownMenu 抽取的共享样式原子（两组件共用，避免样式漂移）
  __tests__/
src/shared/lib/clipboard.ts        // copyToClipboard(text, { toastLabel? }) 统一复制 + 反馈
src/shared/lib/i18n/locales/zh/contextMenu.ts
src/shared/lib/i18n/locales/en/contextMenu.ts
electron/contextMenu.ts            // 可编辑控件原生菜单注册（含 dev 检查元素）
```

### 6.2 菜单描述接口（核心抽象）

```ts
import type { LucideIcon } from 'lucide-react';

export type ContextMenuItemSpec =
  | {
      kind?: 'item';
      id: string;
      label: string;
      icon?: LucideIcon;
      shortcut?: string;            // 仅显示真实绑定，避免假提示
      destructive?: boolean;
      disabled?: boolean;
      hidden?: boolean;
      onSelect: () => void | Promise<void>;
      submenu?: ContextMenuItemSpec[];
    }
  | { kind: 'checkbox'; id: string; label: string; checked: boolean;
      onCheckedChange: (next: boolean) => void }
  | { kind: 'separator'; id: string }
  | { kind: 'label'; id: string; label: string };
```

约定：**spec 以函数形式按需构建**（打开时求值），以天然反映"是否流式中""是否已置顶"等状态：

```tsx
// 使用示例（会话列表项）
<ContextMenu
  items={() => buildSessionContextMenu({ session, pinned, onRename, onTogglePin, onExport, onDelete })}
>
  <SessionItem ... />
</ContextMenu>
```

### 6.3 选区联动（消息右键）

- 打开时读取 `window.getSelection()?.toString()`；有选区时菜单顶部追加「复制选区」「引用选区到输入框」；无选区时**禁用**（不隐藏）。
- 引用动作复用 `src/features/chat/selectionQuote.ts` 与 Chat 页既有 `onQuote` 链路；菜单打开时隐藏 `SelectionQuoteButton` 浮层，避免两个浮层叠加。
- 右键不清除选区（Radix ContextMenu 保留原生选区行为，需回归测试锁定）。

### 6.4 危险动作

- 删除类菜单项统一 `destructive` 样式，`onSelect` 后先关闭菜单再调用 `confirmDialog({ danger: true })`（`confirmService`）。
- 菜单中不使用行内 `TwoStepDelete`（菜单关闭后按钮状态不可见），避免状态丢失。

### 6.5 Electron 主进程

```ts
// electron/contextMenu.ts（新）
webContents.on('context-menu', (_event, params) => {
  if (!params.isEditable) return;          // 非可编辑 → 由渲染层自绘菜单处理
  Menu.buildFromTemplate([
    { role: 'undo' }, { role: 'redo' }, { type: 'separator' },
    { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' },
  ]).popup({ window: BrowserWindow.fromWebContents(webContents) ?? undefined });
});
```

- 覆盖：Chat 输入框、设置页输入框、CodeMirror、xterm 隐藏 textarea、Webview 内表单（role 文案由 Chromium 本地化）。
- 开发模式：在渲染层菜单尾部追加「检查元素」，经 IPC `devtools:inspect` 调用 `webContents.inspectElement(x, y)`（仅非打包环境注册）。
- 兼容性验证点：确认渲染层 `preventDefault()` 后主进程事件不重复弹原生菜单（Electron 21 实测；若行为不一致，用「params.isEditable + 渲染层不注册 Trigger」的约定保证互斥）。

### 6.6 剪贴板与反馈

- 新增 `copyToClipboard(text, { toastLabel })`：统一 `navigator.clipboard.writeText` + 失败兜底（临时 textarea + `document.execCommand('copy')`，Chromium 106 可用）+ 成功/失败 toast。
- 逐点替换"复制"类菜单项的实现，后续可渐进替换既有散落调用（不在本期强制）。

### 6.7 i18n

- 新增 `src/shared/lib/i18n/locales/{zh,en}/contextMenu.ts`，在 `zh.ts` / `en.ts` 聚合。
- 键命名：`contextMenu.session.rename`、`contextMenu.message.regenerate`、`contextMenu.common.copy`、`contextMenu.common.delete` 等。

---

## 7. 分区菜单清单

优先级定义：**P0** = 高频、动作已齐、收益最大；**P1** = 高价值但需少量新基建（IPC/前端写操作接入）；**P2** = 锦上添花，按需排期。

### 7.1 会话列表（P0）

触发：`SessionItem` 行内任意空白处右键（按钮区域除外）。

| 菜单项 | 来源 | 条件 |
|---|---|---|
| 打开 | 既有 onOpen | 始终 |
| 重命名 | 触发既有 inline 编辑（`:245-262`） | 始终 |
| 置顶 / 取消置顶 | 既有 pin handler | 文案随状态 |
| 复制标题 | 新（clipboard util） | 始终 |
| 导出 Markdown | 既有 | 始终 |
| 导出 HTML | 既有 | 始终 |
| 查看分叉树 | 既有 ForkTreeModal | 仅 fork 徽标存在时 |
| ──── | separator | |
| 删除… | 既有删除 + confirmDialog（红色） | 始终 |

参考：ChatGPT ⋯ 菜单、Cherry Studio 会话菜单。

### 7.2 聊天消息（P0）

触发：`Message` 气泡（含 `data-quote-scope="message-body"` 区域）。

| 菜单项 | 用户消息 | 助手消息 | 流式中 |
|---|---|---|---|
| 复制选区 / 引用选区到输入框 | 有选区时启用，无选区禁用 | 同左 | 同左 |
| 复制 | ✅ | ✅ | ✅（已生成部分） |
| 复制为 Markdown | ✅ | ✅ | ✅ |
| 引用到输入框 | ✅ | ✅ | 禁用 |
| 编辑并重新发送 | ✅ | — | 禁用 |
| 朗读 | — | ✅ | 禁用 |
| 重新生成 | — | ✅ | 禁用 |
| 有帮助 / 没帮助（check 态） | — | ✅ | 禁用 |
| 从此处分叉 | — | ✅ | 禁用 |
| 回滚到此 | — | ✅ | 禁用 |
| 保存到记忆 | — | ✅ | 禁用 |
| ──── | | | |
| 删除…（红色） | ✅ | ✅ | 禁用 |

动作全部来自 `MessageActionBar` / `useChatMessageActions`，不新写逻辑。

### 7.3 代码块 / 表格 / 图片（P0）

- 代码块（`ShikiCodeBlock`）：复制代码 / 复制为 Markdown 围栏 / 全选代码。**"下载为文件"**视现有保存 IPC 能力决定（若无通用 save IPC，本期不做，降级为复制）。
- 表格（`MarkdownTable`）：复制表格（TSV）（已有）。
- 图片（`MarkdownImage`）：查看大图（复用 Lightbox）/ 复制图片（`ClipboardItem`，Chromium 106 支持）/ 另存为（同 save IPC 约束）。

### 7.4 输入框（P0，原生兜底）

- 撤销 / 重做 / ── / 剪切 / 复制 / 粘贴 / 全选（Electron role，见 6.5）。
- 开发模式（非打包）：检查元素。
- xterm 终端自动获得同一菜单（其隐藏 textarea 为可编辑控件）。

### 7.5 文件引用 / 附件 chips（P1）

对象：`MessageClientMeta` 的 `file_refs` / `office_refs` / `knowledge_refs`；`InputCard` 的文件/图片/音频 chip；`FileAttachment`、`KnowledgeChip`。

| 菜单项 | 说明 |
|---|---|
| 打开 | Office 走 `office:open`；Wiki 走 `/wiki/read` + 页面跳转；普通文件需泛化 IPC（见风险 R6） |
| 在文件夹中显示 | 已有 `office:show-in-folder`（office 已覆盖管理文件）；工作区文件需新增泛化 reveal IPC + 路径白名单校验 |
| 复制路径 | `copyToClipboard` |
| 复制文件名 | 同上 |
| 移除（仅输入侧 chip） | 既有 remove handler |

### 7.6 Wiki 文件树（P1）

对象：`WikiFileTree`（`src/widgets/wiki/WikiFileTree.tsx`）。后端与前端 API 均已具备写能力：`/wiki/write`、`/wiki/rename`、`/wiki/delete`（`backend/api/wiki_routes.py:531,554,624`；前端 `src/shared/api-client/wiki.ts:111,115,140`）。

| 菜单项 | 说明 |
|---|---|
| 打开 | 既有选中/打开逻辑 |
| 新建文件 / 新建文件夹（目录节点） | `/wiki/write` |
| 重命名 | `/wiki/rename`（inline 弹框或复用现有对话框模式） |
| 删除…（红色） | `/wiki/delete` + confirmDialog |
| 复制路径 / 复制文件名 | clipboard util |

与 `docs/user-manual/03-wiki.md:55` 宣称的能力对齐。

### 7.7 右栏（P1）

- **文件变更卡**（`FileChangeCard`）：接受、回退、切换 diff 模式、在编辑器中打开、在面板打开。
- **产物**（`ArtifactRow` / `ArtifactViewer`）：打开、在文件管理器显示（`revealArtifact`）、复制路径、版本历史。
- **Progress 内 Todo 行**：完成/取消完成、编辑、删除。

### 7.8 P2（按需排期）

- Todo 页行（`TodoRowEditor` / `TodoItem`）：完成、优先级、截止日期、复制标题、删除。
- 提示词模板行：编辑、插入到输入框、复制、删除、导出。
- 技能卡（`SkillCard`）：钉住、归档、历史、删除（均已存在）。
- 项目行（`WorkbenchProjectList`）：复用既有 "..." 菜单全部项。
- Git 变更文件行：复制路径、复制 diff、在编辑器中打开（暂不提供 git 写操作）。
- 记忆条目（Memory 页）：编辑、忘记、复制（需确认后端语义）。
- 命令面板/`@` 候选行：右键"固定为首选"等（优先级最低）。

---

## 8. 涉及文件与模块

### 8.1 新增

| 文件 | 用途 |
|---|---|
| `src/shared/ui/ContextMenu/ContextMenu.tsx` | Radix 封装 + 样式原子 |
| `src/shared/ui/ContextMenu/ContextMenuItems.tsx` | 声明式 spec 渲染器（子菜单/check/radio/分隔/禁用） |
| `src/shared/ui/ContextMenu/types.ts` | `ContextMenuItemSpec` |
| `src/shared/ui/ContextMenu/menuClasses.ts` | 与 DropdownMenu 共享的样式（从 `DropdownMenu.tsx` 抽取） |
| `src/shared/ui/ContextMenu/__tests__/*` | 基座单测 |
| `src/shared/lib/clipboard.ts` | `copyToClipboard`（含兜底与 toast） |
| `src/shared/lib/i18n/locales/{zh,en}/contextMenu.ts` | 菜单文案词典 |
| `electron/contextMenu.ts` | 可编辑控件原生菜单 + dev inspect |

### 8.2 修改

| 文件 | 改动 |
|---|---|
| `package.json` + lockfile | `@radix-ui/react-context-menu`（双分支同步） |
| `src/shared/lib/i18n/zh.ts` / `en.ts` | 聚合 contextMenu 词典 |
| `src/shared/ui/DropdownMenu/DropdownMenu.tsx` | 样式原子迁至 `menuClasses.ts`（顺带清理其内部 `dropdown-menu-copy-snapshot` 审计占位 span，如确认无测试依赖） |
| `electron/main.ts` | 注册 `contextMenu.ts`；新增 `devtools:inspect` IPC（dev-only） |
| `electron/preload.ts` | 暴露 inspect（若走 IPC）；泛化 reveal 通道（若采纳） |
| `src/widgets/session/SessionItem.tsx`（+ `VirtualSessionList` 验证） | 包 Trigger，接入会话菜单 |
| `src/widgets/chat/Message.tsx` | 包 Trigger，接入消息菜单 |
| `src/widgets/chat/MessageActionBar.tsx`（可选） | "更多"内联展开可改为复用同一 spec，减少两套动作列表 |
| `src/widgets/chat/ShikiCodeBlock.tsx` | 代码块菜单 |
| `src/widgets/chat/MessageMarkdownParts.tsx` | 表格/图片菜单 |
| `src/widgets/chat/MessageClientMeta.tsx`、`InputCard.tsx`、`FileAttachment.tsx`、`KnowledgeChip.tsx` | 引用/附件 chip 菜单 |
| `src/widgets/wiki/WikiFileTree.tsx` | Wiki 文件树菜单（接入 `/wiki/*` 写 API） |
| `src/widgets/chat/changes/FileChangeCard.tsx`、`artifacts/ArtifactRow.tsx`、`ArtifactViewer.tsx` | 右栏菜单 |
| P2：`TodoRowEditor.tsx`、`PromptTemplatesTab.tsx`、`SkillCard.tsx`、`WorkbenchProjectList.tsx` | 按需 |
| `docs/technical/110-context-menu.md`（新章节） | 完成后归档技术文档 |
| `src/content/help/*.md`、`docs/user-manual/*.md` | 校对右键相关表述，消除文档漂移 |

---

## 9. 实施步骤（里程碑）

每个里程碑独立可验证、可单独合并（建议每个里程碑一个 PR，main → cherry-pick release/win7）。

- [ ] **M0 基础设施（0.5–1 天）**
  - 新增依赖 + `ContextMenu` 基座 + 声明式渲染器 + `menuClasses` 抽取 + `clipboard` util + i18n 词典。
  - 单测：打开/关闭（Escape、外部点击、滚动）、键盘导航、禁用态、check 态、destructive 样式、ARIA role、`Shift+F10`。
  - 验收：一个 demo 挂载点手动验证后移除；基座覆盖率达标（按本分支门禁）。

- [ ] **M1 会话列表菜单（0.5 天）**
  - `SessionItem` + `VirtualSessionList` 接入；删除走 confirmDialog；与双击重命名、hover 按钮、拖拽排序互不干扰。
  - 测试：菜单项随置顶/fork 状态变化；虚拟列表滚动时菜单正常关闭。

- [ ] **M2 消息菜单 + 选区联动 + 代码块/表格/图片（1–1.5 天）**
  - 用户/助手/流式三态；选区项启用/禁用；与 `SelectionQuoteButton` 互斥；代码块与表格菜单。
  - 测试：三态菜单快照（断言菜单项集合与禁用态）；右键后选区保留；流式期间重新生成禁用。

- [ ] **M3 Electron 原生输入框菜单 + dev inspect（0.5 天）**
  - `electron/contextMenu.ts` 注册；输入框/CodeMirror/xterm 手测；确认与渲染层菜单互斥。
  - 验收：Win7 与 Linux 各一次手测记录（Electron 21 行为差异检查）。

- [ ] **M4 引用/附件 chips（0.5–1 天）**
  - Office 通道复用；工作区文件 reveal/open 若新增 IPC，先过 security-reviewer（路径白名单）。
  - 测试：路径校验拒绝越界路径（单测 + 手工样例）。

- [ ] **M5 Wiki 文件树（1 天）**
  - 新建/重命名/删除接入 `/wiki/*`；删除二次确认；操作后刷新树（react-query invalidate）。
  - 测试：三操作的成功/失败提示；删除确认取消路径。

- [ ] **M6 右栏 + P2 按需（1 天起，可拆分）**
  - 文件变更卡、产物、Todo/提示词/技能/项目行逐个接入；每接入一处复用同一 spec 模式。

- [ ] **M7 文档对齐与归档（0.5 天）**
  - 新增 `docs/technical/110-context-menu.md`；修正 `src/content/help/*`、`docs/user-manual/*` 中与实现不符的右键描述；本计划文档按规范删除（并入技术文档后不保留历史版本）。

---

## 10. 测试策略

- **单元测试（Vitest + RTL）**：基座行为（定位碰撞由 Radix 负责，不断言像素）、键盘、ARIA、spec 渲染（disabled/hidden/check/submenu）。
- **组件测试**：每个接入点断言"对象状态 → 菜单项集合 + 禁用态"；危险动作断言 `confirmService` 被调用；动作断言既有 handler 被调用（不重复实现逻辑）。
- **回归**：hover 按钮、双击重命名、拖拽排序、划线引用、虚拟列表、流式渲染性能（菜单 spec 不在 token 渲染路径上求值）。
- **E2E（Playwright，可选 1–2 条）**：`page.click({ button: 'right' })` 会话删除全流程、消息复制。
- **双分支 CI**：main 与 release/win7 各自覆盖率门禁数值不同（按各分支实测），不引用另一分支数值。
- **手工验收清单**：Win7 SP1 实机（Electron 21）+ Linux 开发机，各覆盖 7.1–7.6 一至两个动作。

---

## 11. 风险评估与依赖

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R1 | 右键清除文本选区 / 与 `SelectionQuoteButton` 浮层叠加 | 选区动作失效或双浮层 | 打开时捕获选区；菜单打开时隐藏引用按钮；回归测试锁定 |
| R2 | 虚拟列表（>120 会话）中 Trigger 成本或行卸载导致菜单悬挂 | 性能/交互异常 | 打开时惰性构建 spec；删除等动作先关菜单再执行；滚动即关闭 |
| R3 | 流式消息高频重渲染导致 spec 重复计算 | 卡顿 | `items` 仅在 open 时求值；菜单内容独立于消息渲染树 |
| R4 | 渲染层自绘菜单与主进程原生菜单重复弹出 | 双菜单 | 约定：可编辑区域不注册 Trigger；启动前实测 Electron 21 `preventDefault` 行为，必要时用 `isEditable` + 显式 IPC 标志互斥 |
| R5 | Electron 21 / Chromium 106 / Win7 兼容性 | 菜单不显示/样式异常 | 仅使用 Radix（已验证同栈在用）；避免 popover API、`:has()`、新 CSS 特性；Win7 实机冒烟 |
| R6 | 泛化 reveal/open IPC 的路径穿越 | 安全 | 仅允许工作区根目录与 Office 托管目录白名单内路径；规范化 + 前缀校验；合并前过 security-reviewer |
| R7 | 双分支依赖漂移 | win7 无菜单或构建失败 | `package.json` + lockfile 与代码同一 cherry-pick；win7 CI 必跑 |
| R8 | 文档仍有不实描述（如 Wiki 若只交付部分能力） | 用户预期落差 | M7 逐条核对；未实现项改文案或删除 |
| R9 | 快捷键提示与实际绑定不一致 | 误导 | 只显示真实绑定的快捷键，否则不显示 |
| R10 | 菜单项与"更多"内联展开出现两套动作清单 | 维护分叉 | M2 可选将"更多"改为复用同一 spec |

依赖：

- `@radix-ui/react-context-menu`（新增，MIT，React 18 兼容）。
- 既有：Radix、lucide-react、sonner、@tanstack/react-query、i18n。
- 后端：无新增业务 API；Wiki 写接口与 Office open/reveal 通道均已存在。
- Electron 21 role 菜单：支持。

---

## 12. 待决策点（默认值已给出，可评审时调整）

1. **技术选型**：默认方案 A（Radix ContextMenu），备选方案 B（零新依赖）。
2. **P2 范围**：默认首轮只交付 P0 + P1；Todo/提示词/技能/项目行按需。
3. **左键浮层迁移**：默认不迁移 13 处手写浮层，仅新增右键；后续单独排期。
4. **"更多"按钮改造**：建议 M2 时把消息"更多"改为同一 spec（一处实现两处复用）。
5. **泛化 reveal/open IPC**：若安全评审不通过，M4 降级为"仅 Office 托管文件 + 复制路径"。

---

## 13. 参考资料

- 调研证据：`src/shared/ui/DropdownMenu/DropdownMenu.tsx`、`src/widgets/chat/MessageActionBar.tsx`、`src/widgets/session/SessionItem.tsx`、`electron/menu.ts`、`electron/tray.ts`、`electron/main.ts`、`backend/api/wiki_routes.py`、`src/shared/api-client/wiki.ts`。
- 主流应用对照来源见第 3 节链接。
