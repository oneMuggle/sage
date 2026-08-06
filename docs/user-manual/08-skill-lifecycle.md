# 08. 技能生命周期 (Skills Lifecycle)

> **版本**: Sage main @ PR #272 (Skill Curator 生命周期)
> **用户入口**: 设置页 -> Skills 管理 -> 任意技能卡(每张卡右上角有生命周期徽章)

## 8.1 这是什么

Sage 中的"技能"(SKILL.md 文件描述的指令集)有不同的使用活跃度。**生命周期系统**自动为每个技能打一个标签,告诉你"它最近还在被用吗",同时让你**手动归档**不再需要但不想删除的技能。

简单说:**它是 Sage 帮你识别"哪些技能在吃灰、哪些该退休"的工具。**

## 8.2 三种生命周期

每个技能卡片右上角会有一个徽章,标识它的状态:

| 状态 | 含义 | 视觉 |
|---|---|---|
| **active**(活跃) | 近期被调用过(或新装的尚未分类) | 绿色 |
| **stale**(冷门) | 一定时间未被调用 | 灰色 |
| **archived**(已归档) | 用户主动归档,不再出现在推荐列表 | 半透明(透明度 60%) |

> 内部还有一个特殊状态 **"never used"**(从未使用),并入 `stale` 显示。

## 8.3 状态如何自动变化

后端的"Skill Curator"模块会:

1. **每次技能被调用**:刷新 last_used_at 时间戳
2. **每次聊天空闲期**(默认 24 小时):扫描所有技能,根据"距上次使用时间"重新计算状态
   - ≤ 阈值(默认 7 天):`active`
   - \> 阈值:`stale`
3. **手动归档**:状态变成 `archived`,即使后续被调用也**不会**自动改回(需要手动取消归档)

阈值可在 `~/.config/sage/skills/curator.json` 中调,默认如下:

```json
{
  "active_threshold_days": 7,
  "scan_interval_hours": 24
}
```

## 8.4 你能做什么

### 8.4.1 看每个技能的状态

打开 Skills 管理页:每张卡顶部都有徽章。新装的或最近用的 -> `active`,几天没用 -> `stale`,手动归档过的 -> `archived`(卡片半透明)。

### 8.4.2 手动归档(Archive)

点击技能卡的菜单 -> **"归档"**。归档后的技能:

- 在工具补全、Slash 命令列表中**不再出现**
- 卡片视觉变浅(opacity-60)以区分
- 不影响已写入的 SKILL.md 文件——你仍可在文件管理器中看到它

> built-in 技能(写死在 `backend/skills/builtin/` 的)不显示归档按钮。

### 8.4.3 取消归档(Unarchive)

在归档状态卡上点菜单 -> **"取消归档"**:

- 回到上次状态(`active` 或 `stale`)
- 重新进入补全列表
- **不会**自动变回 active——下次空闲期扫描才会重新计算

### 8.4.4 一键恢复活跃

技能归档后,如果你**确实**还要用,最简单的办法是:把 SKILL.md 移到 `archived/` 子目录,再放回根目录。也可以直接点菜单"取消归档"。

## 8.5 与"删除"的区别

| 操作 | 影响 SKILL.md 文件? | 后端条目? | 可恢复? |
|---|---|---|---|
| **删除** | ✅ 物理删除 | ✅ 移除 | ❌ 不可 |
| **归档** | ❌ 不动文件 | 修改 lifecycle 字段 | ✅ 一键恢复 |

> 删除是危险操作——文件不可找回;归档是软删除,推荐优先用归档。

## 8.6 数据存放位置

| 数据 | 路径 |
|---|---|
| SKILL.md 文件本体 | `~/.config/sage/skills/<name>/SKILL.md` |
| 生命周期元数据 | sqlite `skills` 表的 `lifecycle` 字段 |
| 阈值配置 | `~/.config/sage/skills/curator.json` |

## 8.7 故障排查

| 现象 | 处理 |
|---|---|
| 徽章一直显示 active,从不转 stale | curator 后台任务没起;检查后端日志,或手动重启 Sage |
| 归档后还能在补全里看到 | 浏览器/Tauri 缓存旧列表;刷新页面或重启客户端 |
| 想永久删除某个技能 | 归档不满足 -> 用删除按钮(不可恢复) |
| built-in 技能显示但无归档按钮 | 这是预期的:built-in 走专门流程,不可用户归档 |

## 8.8 进一步阅读

- 技术细节(后台扫描、阈值计算、curator worker):[`../technical/24-skills-system.md`](../technical/24-skills-system.md)
- curator 设计 spec:[`../superpowers/specs/2026-08-02-skill-curator-lifecycle-design.md`](../superpowers/specs/2026-08-02-skill-curator-lifecycle-design.md)
- 编写自己的技能:[`04-skill-md-authoring.md`](./04-skill-md-authoring.md)
