# 项目模块 P3 计划——Chat 头部当前项目徽标

> 日期: 2026-09-13 · 基线: main `f42a48a2`（P2 #734 合入后）
> 分支: `feat/projects-p3` · 前置: P1 #727 / P2 #734

## 1. 定位与裁剪

P2 方案 §6 列了三个 P3 候选，本批落地一个、否决两个（均有据）：

| 候选 | 结论 | 依据 |
| --- | --- | --- |
| **Chat 头部当前项目徽标** | ✅ 落地 | 主流工具（Cursor 标题栏 workspace 名 / Claude Code 会话头仓库名）都在会话面展示当前项目上下文；Chat 现有 `useCurrentWorkspace()` 只用于 Office 注入（Chat.tsx L123→L836），用户在对话中看不到自己"在哪个项目里"——真实产品缺口 |
| 项目清单拖拽排序 | ❌ 否决 | 项目清单的语义是**最近打开排序**（last_opened_at，Cursor Recent 同款）；本地手动排序与 recency 语义打架（每次打开项目都会重排），做 dnd 是负价值 |
| 拖拽文件夹登记 | ⏸ 继续缓行 | 同 P2 §2：应用无全局 drop 面，侧栏 drop 区成本高于收益 |

## 2. 设计

- 新组件 `src/widgets/chat/ProjectBadge.tsx`（纯新文件，win7 零冲突）：
  - props: `workspacePath: string | undefined | null`（Chat 已有的
    `useCurrentWorkspace()` 值透传，组件不依赖 provider，测试只喂 prop）；
  - 无绑定 → 不渲染；有绑定 → Folder 图标 + 项目名 chip；
  - 名称解析：`projectApi.list()` 按 `path === workspacePath` 精确匹配
    登记项目名；未登记（历史绑定）回退 `basename(path)`；
  - tooltip = 完整路径；`data-testid="chat-project-badge"`；
  - 拉取失败静默降级为 basename 展示。
- 插入点：Chat.tsx 页面头部 L664 `对话` h2 之后（1 行改动）。

## 3. 不做的事（边界）

- 不加"在文件管理器中显示"：现有 `showOfficeDocumentInFolder` 仅接受
  受管文件 ref，通用路径 reveal 需新增 Electron IPC——扩 win7 对齐面，
  收益不成比例；
- 不做徽标点击跳转/菜单：display-only，避免为 P3 引入交互分叉。

## 4. 测试

- `src/widgets/chat/__tests__/ProjectBadge.test.tsx`（新文件）：
  无绑定不渲染 / 登记项目显示注册名 / 未登记回退 basename /
  tooltip 完整路径 / 拉取失败降级。
- 全量前端套件基线对照（3 个 Windows 环境存量失败文件不变）。

## 5. win7 对齐

`ProjectBadge.tsx` 及其测试为纯新增；Chat.tsx 改动为 1 行 JSX 插入
（该文件 win7 分支有分歧，cherry-pick 时机械重放即可）；无 IPC/后端/
依赖变更。
