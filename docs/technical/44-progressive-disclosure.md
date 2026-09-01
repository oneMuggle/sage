# 44 — 渐进式功能披露

**最后更新**：2026-08-30
**适用范围**：侧边栏高级入口的 sticky-unlock 机制

## 概览

Sage 对少数“多数用户不需要”的功能使用渐进式披露：入口首次使用前不显示在侧边栏，用户访问对应路由后永久解锁，之后在同一设备上持续显示。当前受该机制控制的是：

- `/orchestration` → `orchestration`
- `/office` → `office`

**`/skills` 不受门控**。技能页是 SKILL.md 体系的主要 UI 入口，如果把它隐藏到“先访问后解锁”，用户将无法通过侧边栏发现它，形成自锁。因此 `/skills` 始终作为顶级导航入口显示。

## 状态存储

实现位于 `src/shared/lib/hooks/useFeatureUnlock.ts`：

- localStorage key：`sage-feature-unlock`
- 存储值：已解锁 feature key 的 JSON 字符串数组，例如 ` ["office", "orchestration"] `
- 写入采用幂等逻辑，重复解锁不会增加重复项
- localStorage 不可用或内容无法解析时，安全回退为空集合
- 同标签页通过 `sage:feature-unlock` 自定义事件同步；跨标签页通过浏览器 `storage` 事件同步

该状态是设备/浏览器侧的可见性偏好，不是后端权限，也不代表功能启用状态。

## 生命周期

1. `Sidebar` 根据 `ADVANCED_FEATURE_BY_PATH` 判断当前路径是否对应高级功能。
2. 访问高级路径时调用 `unlockFeature(featureKey)`。
3. `useFeatureUnlock(featureKey)` 从 localStorage 初始化并订阅同步事件。
4. 未解锁的高级入口在侧边栏不渲染；已解锁后持续显示。
5. 隐藏的高级功能仍可通过命令面板或直接 URL 访问，访问成功后完成解锁。

## 设计边界

渐进式披露只控制侧边栏入口的展示，不控制：

- React Router 路由是否存在；
- 后端 API 是否可用；
- 功能的权限、配置或运行时开关；
- `/skills` 页面及其技能列表。

如果需要新增受门控入口，必须同时确认该入口存在另一条可发现的访问路径，避免产生自锁；核心能力和唯一 UI 入口不应加入 `ADVANCED_FEATURE_BY_PATH`。

## 相关实现与文档

- 实现：`src/shared/lib/hooks/useFeatureUnlock.ts`
- 侧边栏：`src/widgets/layout/Sidebar.tsx`
- 技能页面：`src/pages/Skills.tsx`
- [技能生命周期用户手册](../user-manual/08-skill-lifecycle.md)
