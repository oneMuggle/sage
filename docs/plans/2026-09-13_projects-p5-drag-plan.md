# 项目模块 P5 计划——项目区块局部拖拽登记

> 日期: 2026-09-13 · 基线: main `3af4a37e`
> 分支: `feat/projects-p5-drag` · 前置: P1 #727 / P2 #734 / P3 #739 / P4 #743

## 1. 背景与重评

拖拽文件夹登记在 P2 §2 / P3 §1 两轮被"缓行"，理由都是**全局 drop 面**
的成本：electron/main.ts 无 drop 处理、聊天附件 drop 拿不到路径语义、
侧栏全局 drop 区要处理多点嵌套高亮。本批改为**区块局部方案**绕开该成
本：只在侧边栏"项目"分组的内容区接收 drop，不触碰全局行为。

另一个前置变化：Electron `File.path`（OfficeFilePicker 已用的先例模式）
在当前 Electron 21.4.4 可用；仓库若升级 Electron ≥32 需迁移
`webUtils.getPathForFile`——在本批文档中留迁移注记。

## 2. 方案

`ProjectSection` 内容区（render 包裹层）：

- `onDragOver`：`preventDefault()` + 置 `dropActive` 状态（高亮虚线框
  + 提示文案），`onDragLeave` / drop 完成 / `onDragEnd` 复位；
- `onDrop`：
  1. 取 `e.dataTransfer.files`，过滤出带 `path` 的条目（浏览器环境
     无 `path` → 静默忽略，与 OfficeFilePicker 同判据
     `(file as File & { path?: string }).path`）；
  2. 逐个 `projectApi.register(path)`：后端 `validate_workspace` 拒绝
     不存在/非目录（400）——**不新增 IPC**，复用既有校验；
  3. 汇总结果：成功 N 个 → toast `已登记 N 个项目` 并 `refresh()`；
     失败的逐条 toast 错误信息；全部失败不改变清单；
  4. **拖拽登记不自动打开**（区别于 + 按钮的登记即打开）：拖拽是
     批量/顺手动作，静默导航会打断当前工作流；行点击即打开，
     一致且可预期。
- 无 `electronAPI`（浏览器/测试环境）→ drop 无 path 可取，行为退化为
  no-op，不报错。

## 3. 不做的事

- 不做全局 window drop 拦截（那是两轮缓行的原因）；
- 不做拖拽排序（P3 §1 已否决，与最近打开排序语义冲突）；
- 不新增 IPC / 后端端点（复用 `validate_workspace` 校验语义）。

## 4. 测试

- 拖入含 `path` 的 File → register 被调、清单刷新、toast 计数；
- 拖入无 `path` 的 File（浏览器语义）→ 不调 register、不报错；
- register 400（非目录）→ 错误 toast、清单不变；
- dragOver 高亮状态出现、dragLeave 复位。

## 5. win7 对齐

改动集中在 `ProjectSection.tsx` + 其测试 + i18n（P1 新文件体系，纯追
加）；无 IPC / 后端 / 依赖变更；`File.path` 在 Electron 21（win7 LTS
同款冻结版本）可用，两端行为一致。
