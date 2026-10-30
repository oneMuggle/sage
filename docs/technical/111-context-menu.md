# 右键上下文菜单体系

> 状态：已实现（2026-10-29，对应计划 `docs/plans/2026-10-29_context-menu-system.md`，已归档删除）
> 适用分支：`main` / `release/win7`（纯前端 + Electron 主进程，无 Python 版本差异）

## 1. 背景

- Electron 21 不提供浏览器默认右键菜单；此前渲染层也没有任何自绘菜单，桌面端页面内右键**完全无反应**（包括输入框的剪切/复制/粘贴）。
- 帮助文档早已宣称会话列表、Wiki 文件树支持右键操作，但产品未实现。
- 各界面动作 handler 已齐备（消息操作栏、会话项、技能卡、变更卡、产物），右键菜单仅作为"第二入口"接线。

## 2. 架构

### 2.1 渲染层基座

```
src/shared/ui/ContextMenu/
  ContextMenu.tsx           # 声明式包装：items（可传函数，打开时求值）/ enabled / onOpenChange
  ContextMenuPrimitives.tsx # Radix ContextMenu 原语 + 样式封装（无状态，避免循环导入）
  ContextMenuItems.tsx      # ContextMenuItemSpec[] → 菜单树（item/checkbox/radio/separator/label/submenu）
  menuClasses.ts            # 与 DropdownMenu 共用的样式原子，两套菜单观感一致
  types.ts                  # ContextMenuItemSpec 类型
  contextMenuEvents.ts      # 全局打开态（供划词引用按钮让位）
```

依赖：`@radix-ui/react-context-menu`（MIT，React 18，Chromium 106 兼容）。

核心约定：

1. **菜单项在打开时求值**：`items={() => build...()}`，直接读取当次点击时的状态（是否置顶、是否流式中、是否有选区），不在流式渲染路径上重复计算。
2. **动作复用**：菜单只编排既有 handler（`MessageActionBar` / `useChatMessageActions` / `SessionItem` / store actions），不新增业务逻辑。
3. **危险动作**：删除/回滚统一 `destructive` 渲染 + `confirmService` 二次确认（菜单内不使用行内两步删除）。
4. **嵌套菜单**：Trigger 在 `onContextMenu` 上 `stopPropagation()`，代码块/表格等内层菜单不会同时弹出消息菜单。
5. **可编辑态让位**：`enabled={false}` 时不挂监听（如会话/Wiki 行内重命名输入框），交给 Electron 原生编辑菜单。

### 2.2 选区联动

- 消息气泡右键时读取 `getQuotableSelection(window.getSelection(), bubbleRef.current)`：
  - 有选区 → 菜单顶部追加「复制选区」「引用选区到输入框」；
  - 无选区 → 不显示选区项；
  - 流式中 → 生成类动作禁用。
- `contextMenuEvents.ts` 维护全局打开计数；`SelectionQuoteButton` 订阅 `sage:context-menu-open` 并在菜单打开时隐藏，避免双浮层叠加。

### 2.3 Electron 主进程（可编辑控件）

`electron/contextMenu.ts`：

- `registerEditableContextMenu(webContents, { isDev })` 监听 `webContents 'context-menu'`，**仅 `params.isEditable` 时**弹出原生菜单（撤销/重做/剪切/复制/粘贴/全选，按 `editFlags` 禁用）。
- 覆盖：Chat 输入框、CodeMirror、xterm 隐藏 textarea、设置页输入框。
- 开发期（`!app.isPackaged`）追加「检查元素」（`inspectElement(x, y)`）。
- 非可编辑区域由渲染层 Radix 菜单处理；主进程直接 return，不会重复弹菜单。

### 2.4 开发期「检查元素」

- 渲染层菜单在 `import.meta.env.DEV` 且存在 `window.electronAPI.devtools` 时自动追加「检查元素」项（`buildMenuSnapshot`），按右键坐标经 IPC `sage:devtools:inspect` 请求主进程 `inspectElement`。
- 主进程 handler 双重门禁：`app.isPackaged` 直接忽略 + `isTrustedRenderer` 校验。
- 生产构建中 `import.meta.env.DEV === false`，整段逻辑被 tree-shake。

## 3. 接入矩阵（P0 / P1 已实现）

| 界面             | 组件                                                            | 菜单动作                                                                                                                                                                             |
| ---------------- | --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 会话列表         | `src/widgets/session/SessionItem.tsx` + `sessionContextMenu.ts` | 打开 / 重命名 / 置顶·取消置顶 / 复制标题 / 导出 Markdown / 导出 HTML /（分叉树）/ 删除…（确认框）                                                                                    |
| 聊天消息         | `src/widgets/chat/Message.tsx` + `messageContextMenu.ts`        | 复制选区·引用选区\* / 复制（渲染后纯文本） / 复制为 Markdown（源文本） / 引用到输入框 / 编辑重发（用户） / 重新生成（助手） / 有帮助·没帮助 / 分叉 / 回滚 / 存记忆 / 删除…（确认框） |
| 代码块           | `ShikiCodeBlock.tsx`                                            | 复制代码 / 复制为 Markdown 围栏                                                                                                                                                      |
| 表格             | `MessageMarkdownParts.tsx`（MarkdownTable）                     | 复制表格（TSV）                                                                                                                                                                      |
| 图片             | `MarkdownImage.tsx`                                             | 查看大图                                                                                                                                                                             |
| 文件引用 chip    | `MessageClientMeta.tsx`                                         | 复制路径 / 复制文件名                                                                                                                                                                |
| Office 引用 chip | `OfficeRefChip.tsx`（输入区与消息共用）                         | 打开 / 在文件夹中显示 / 复制文件名 /（输入区）移除；历史消息按 `client_meta.office_refs[].workspace_path` 定位原工作区文档                                                           |
| 知识库 chip      | `KnowledgeChip.tsx`、`MessageClientMeta.tsx`                    | 复制名称 /（输入区）移除                                                                                                                                                             |
| 附件 chip        | `FileAttachment.tsx`、`MessageClientMeta.tsx`                   | 复制文件名 /（图片）查看大图 /（输入区）移除                                                                                                                                         |
| Wiki 文件树      | `src/widgets/wiki/WikiFileTree.tsx`                             | 文件：打开/重命名/复制路径/复制文件名/删除…；目录：新建文件/复制路径/复制文件名/删除…（目录递归确认）                                                                                |
| 文件变更卡       | `FileChangeCard.tsx`                                            | 展开·收起 / 接受 / 回滚…（确认）/ 切换 diff 视图 / 在编辑器打开 / 在右栏查看 / 复制路径                                                                                              |
| 产物行           | `ArtifactRow.tsx`                                               | 打开产物 / 在文件管理器显示 /（Office）交付工作台 / 复制路径                                                                                                                         |
| 可编辑控件       | `electron/contextMenu.ts`                                       | 原生撤销/重做/剪切/复制/粘贴/全选；开发期检查元素                                                                                                                                    |

\* 选区项仅在存在文字选区时出现。

## 4. 安全边界

- **Office 打开/定位**：复用既有 `office:open` / `office:show-in-folder` 通道（主进程校验托管文件路径），不新增泛化 reveal IPC。
- **工作区普通文件**：本期按计划降级为「复制路径/文件名」，不新增 `shell.openPath`/`shell.showItemInFolder` 泛化通道（需路径白名单评审后再做）。
- **Wiki 文件操作**：仅调用后端既有 `/wiki/write|rename|delete`（后端 `secure_*` 系列已做路径穿越/符号链接防护）；名称含 `/` 或 `..` 在前端直接拒绝。
- **dev inspect IPC**：非打包环境 + 可信渲染器双重校验，不暴露任意窗口操作。

## 5. 测试

- 基座：`src/shared/ui/ContextMenu/__tests__/ContextMenu.test.tsx`（打开/键盘/禁用/checkbox/隐藏/延迟求值/全局打开态/嵌套 stopPropagation）。
- 构建器：`sessionContextMenu.test.ts`、`messageContextMenu.test.ts`（菜单项集合、禁用态、状态文案）。
- 界面接入：`SessionItem.contextMenu.test.tsx`、`Message.contextMenu.test.tsx`、`ShikiCodeBlock.contextMenu.test.tsx`、`MarkdownImage.contextMenu.test.tsx`、`OfficeRefChip.test.tsx`、`AttachmentChips.contextMenu.test.tsx`、`MessageClientMeta.contextMenu.test.tsx`、`WikiFileTree.contextMenu.test.tsx`、`FileChangeCard.contextMenu.test.tsx`、`ArtifactRow.contextMenu.test.tsx`。
- Electron：`electron/__tests__/contextMenu.test.ts`（editable 门禁、角色映射、dev inspect 坐标）。
- 既有组件测试因新增 `useI18n` 依赖补包 `I18nProvider`（断言未变）。

## 6. 兼容性与双分支

- Chromium 106 / Electron 21 / Win7：只使用 Radix React 原语，不依赖 popover API、`:has()` 等新特性。
- 新增依赖 `@radix-ui/react-context-menu` 与 `package-lock.json` 必须与代码同一 cherry-pick 到 `release/win7`；无 Python 3.8 适配面。
- i18n 新增 `contextMenu.*` 词典域（`locales/{zh,en}/contextMenu.ts`），英文词典键集由中文词典类型约束，不会漂移。

## 7. 维护指南（新增一处右键菜单）

1. 纯数据型菜单：在组件同目录写 `buildXxxMenuItems(params)`（参考 `sessionContextMenu.ts`），只注入 handler，单测断言菜单项集合与禁用态。
2. 组件接入：`<ContextMenu items={() => buildXxx(...)}><div .../></ContextMenu>`；行内编辑态传 `enabled={false}`。
3. 新文案：在 `locales/{zh,en}/contextMenu.ts` 同步加键；带参文案用 `fillTemplate`。
4. 危险操作：`destructive: true` + `confirmDialog({ danger: true })`。
5. 若涉及新 IPC：先过 security-reviewer，并在 `electron/__tests__` 增加门禁测试。

## 8. 已知边界（未纳入本期）

- P2 列表（Todo 页、提示词模板、技能卡、项目行、Git 变更行）仍走既有 hover/"..." 按钮，未接右键。
- 消息操作栏"更多"仍为内联展开（与菜单动作同源，但未合并为同一 spec）。
- Wiki 目录不支持重命名（后端 `secure_rename_path` 仅正则文件）；不提供"新建文件夹"（无 mkdir API，新建文件会自动创建父目录）。
- 进展区 Todo 行是 agent 只读快照，无用户动作，未提供菜单。
- 图片 `复制图片`、代码块 `下载为文件` 需要保存/剪贴板图片加工，暂未提供。
