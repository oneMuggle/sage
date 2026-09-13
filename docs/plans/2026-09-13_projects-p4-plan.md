# 项目模块 P4 计划——子行会话删除 + 清单自动刷新

> 日期: 2026-09-13 · 基线: main `59a569e0`（P3 #739 合入后）
> 分支: `feat/projects-p4` · 前置: P1 #727 / P2 #734 / P3 #739

## 1. 缺口分析（P1-P3 收尾后）

| 缺口 | 现状 | 影响 |
| --- | --- | --- |
| 子列表会话无法就地删除 | P2 子行只有"点击进入" | 用户必须去会话列表搜标题——子列表场景下"这个项目里有哪些会话、清掉没用的"是自然操作闭环 |
| 项目计数/子列表陈旧 | ProjectSection 仅挂载时 `refresh()` 一次 | 在会话区删除/新增会话后，侧栏项目行会话计数与展开子列表不更新，直到重启 |

## 2. 方案

1. **子行删除**：子行 hover 显现 `TwoStepDelete`（复用侧栏既有组件，
   两步防误触）→ `sessionApi.delete(sessionId)` → 刷新该行子列表 +
   `loadSessions()` + `refresh()`。删除失败 toast，不破坏展开态。
   复用既有 `sidebar.new_chat` 之外的 i18n：新增
   `sider.project.delete_session` / `delete_session_confirm`。
2. **会话数量联动**：订阅 store 的 `sessions` 数组长度，长度变化
   （任意来源的会话增删）→ 防抖 `refresh()` 项目清单（后端聚合的
   session_count 是唯一事实源，不本地推算）。已展开项目的子列表同步
   `refreshSubSessions`。

## 3. 不做的事

- 子行重命名/置顶：SessionItem 已有完整实现，子列表内复制会形成
  双入口漂移；重命名/置顶请回会话列表（子行 tooltip 已给指引性文案）；
- 本地推算计数：单一事实源留在后端聚合查询。

## 4. 测试

- 子行 hover 出现删除按钮 → 两步确认 → `sessionApi.delete` 被调 +
  子列表刷新；
- store `sessions` 长度变化 → `projectApi.list` 被重新调用（防抖）；
- 删除失败不收起子列表。

## 5. win7 对齐

全部改动位于 P1/P2 系列的新文件（ProjectSection/测试），纯追加；
无后端/IPC/依赖变更。
