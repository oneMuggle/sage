# UX N2：思考过程保留 + 使用统计曲线图（2026-11-01）

> 分支：`feat/ux-n2-thinking-chart`  
> 基线：`origin/main`（N1 合并后）

## 1. 思考过程保留

问题：流结束/切换会话时消息 id 被服务端 id 替换，`Message` 重挂载，
`ThinkingPanel` 的 `useState(false)` 把刚展开的思考面板立即折叠；刷新后也默认折叠。

实现：

- 新增 `src/widgets/chat/thinkingExpansionStore.ts`
  - 以 `reasoning` 内容哈希为键（长度 + djb2）保存展开态；
  - 内存 Map 吸收 id 替换导致的重挂载；显式展开/折叠写 `sessionStorage`
    （`sage:thinking-expanded:<hash>`），刷新后保留；
  - 流式自动展开只写内存，避免每个 delta 落盘。
- `ThinkingPanel`
  - 初始展开态从 store 读取；
  - 折叠时标题显示首行预览（≤60 字），用户不用点开也能确认内容仍在；
  - 切换展开/折叠写回 store。

## 2. 使用统计曲线图

问题：趋势图是堆叠柱；用户希望参考 CC Switch 使用曲线。

实现：

- `UsageTrendChart` 保持自绘 SVG（无新依赖）：
  - 输入/输出两条平滑曲线（`monotonePath`，无过冲）；
  - 曲线下方渐变面积；
  - 成本继续右轴虚线；
  - 网格、hover 详情卡、键盘导航、空态/加载态全部保留；
  - 透明热区仍按时间桶工作。

## 3. 实施步骤

- [x] thinkingExpansionStore + ThinkingPanel 接入
- [x] 折叠预览 + 测试（重挂载保留展开态）
- [x] UsageTrendChart 柱状 → 曲线/面积
- [x] 图表测试同步
- [x] typecheck / eslint / Vitest / architecture

## 4. 验证

- Vitest：`UsageTrendChart` 11 条 + `Message` 16 条 → **27 passed**；
- `npm run typecheck` 通过；`eslint` 改动文件无输出；
- `architecture-check` 通过（81 baselined）。

## 5. 不在本批

欢迎页 slash、设置页标题层级/美化、桌宠安装包发布。
