# 想法池 (Ideas)

> 这里是"未来可能要做"的功能想法的轻量暂存区。

## 这不是

- ❌ **不是** `specs/`（已决定要做且完成设计）
- ❌ **不是** `plans/`（已决定要做且完成实施步骤）
- ❌ **不是** `docs/technical/`（已完成的归档）
- ❌ **不是** `docs/plans/`（feature-development.md 流程，进行中/完成后删除）

## 这是

- ✅ 一个想法刚萌芽，还没有 spec
- ✅ 知道大致动机，但设计细节未定
- ✅ 有触发条件（"X 之后做"），但还没到那个时点
- ✅ 想让未来某个时刻的自己/同事能想起来

## 文件格式

每个想法一个文件，命名 `YYYY-MM-DD-<slug>.md`（**无** `-design` 后缀，跟 specs/plans 区分）：

```markdown
# 想法：<一句话标题>

> 状态：💭 Backlog | 🎯 Next Up | 📋 Planned
> 日期：YYYY-MM-DD
> 关联：<相关 spec / plan / issue / 外部参考>

## 动机
为什么想做？解决什么痛点？

## 想法草图
2-3 段，越模糊越好（这是想法不是设计）

## 触发条件 / 何时做
- 哪个 PR / 功能上线之后？
- 哪个用户痛点出现之后？
- 没有明确触发条件 = 默认 Backlog

## 升级路径
升级到 specs/ 时：
- 移动到 `docs/superpowers/specs/YYYY-MM-DD-<slug>-design.md`
- 在本文件加 `> 已升级到: specs/<...>.md (commit xxx)`
- 删除本文件（feature-development.md 约定）
```

## 工作流

```
💭 想法诞生
   ↓ 写下 docs/superpowers/ideas/<date>-<slug>.md (轻量)
🎯 决定要做了 → 升级
   ↓ 移动到 docs/superpowers/specs/<date>-<slug>-design.md (写正式设计)
📋 决定实施了
   ↓ 移动到 docs/superpowers/plans/<date>-<slug>.md (写实施步骤)
✅ 完成
   ↓ 归档到 docs/technical/<XX>-<topic>.md，删除中间产物
```

## 状态分类

| 状态 | 含义 | 下一步动作 |
|------|------|-----------|
| 💭 Backlog | 没有明确触发条件，只是"觉得有用" | 偶尔 review，决定升级或删除 |
| 🎯 Next Up | 触发条件已满足或很快满足 | 近期（1-2 周内）升级到 specs/ |
| 📋 Planned | 已经粗略计划过，但还没动笔写 spec | 视情况升级到 specs/ 或保持 |

## 维护建议

- **每月扫一次**：把所有 💭 Backlog 过一遍，决定升级/删除/保持
- **完成触发条件时立即检查**：本目录里所有 🎯 Next Up 该升级的就升级
- **不要让想法超过 10 条**：超过 10 条说明该 archive 一些（合并相似、删除过时）
- **不要在这里写正式设计**：超过 1 页的想法说明该升级到 specs/

## 跟其他机制的关系

- **CHANGELOG `[Unreleased]`** — 记录**已实现但未发布**的功能，不是想法
- **GitHub Issues** — 用于**协作/通知**，想法池是脑外备份
- **`docs/plans/`** — feature-development.md 流程，**进行中**的计划
- **`.superpowers/sdd/progress.md`** — **单个 feature** 的任务进度，不是项目级 roadmap