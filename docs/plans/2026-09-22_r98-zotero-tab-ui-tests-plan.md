# R98 批次计划 —— ZoteroTab UI 测试

日期：2026-09-22 ｜ worktree：`.worktrees/feat-r98-zotero-tab`（基于 origin/main 0b9b35e8）

## 背景

r94 收口了 Zotero 的路由与 client；ZoteroTab（426 行，设置页最复杂的只读浏览
组件之一）仍无 UI 测试。该组件含状态卡片、路径保存、300ms 防抖搜索、分类
筛选、详情/批注展开多条异步链路。

## 批次内容

新增 `src/pages/settings/__tests__/ZoteroTab.test.tsx`（7 用例）：

- 状态卡片：加载中 '检测中…'；连接成功 '已连接' + 统计数字与标签渲染 +
  分类下拉填充；不可用 '未连接' + 错误文案透出 + 搜索入口隐藏。
- 路径保存：'保存路径' 点击 → `setPath` 收到 trim 后的值 → '路径已保存'
  出现 → 状态自动重载（status 二次调用）。
- 搜索：空查询且无筛选不触发 search（防抖窗口静默）；输入 300ms 防抖后
  search 收到 {q, collection_key: undefined, tag: undefined, limit: 30} 并
  渲染结果标题；点击结果加载详情与批注（getItem/getAnnotations 通道 +
  摘要/批注计数展开区渲染）。

实现要点：zoteroClient 模块 vi.mock 替身；真实 I18nProvider zh 文案断言；
fake timers 驱动防抖（fake timers 下 RTL waitFor 轮询不走虚拟时钟，改用
`act + advanceTimersByTimeAsync(0)` microtask 冲刷——已踩坑记录）。

## 验证矩阵

- 本机 vitest：7/7 通过（junction + 即摘协议）。
- CI：Frontend (TypeScript) lint + typecheck + vitest。

## 不做

- 不改生产代码（组件无 testid 也能以文本稳定断言，故不动源码）。
- demoChatScript 演示数据维持不测。
