# 技能系统

> 本页保留旧版文档链接。技能系统的实现已迁移到 SKILL.md 适配层和 Electron/REST 链路，旧版 `SkillManager`、`SkillStore` 和技能商店设计不代表当前代码。

## 当前文档

- [Skills 系统端到端技术文档](./technical/24-skills-system.md)
- [SKILL.md 规范一致性](./technical/28-skill-md-spec-conformance.md)
- [SKILL.md 编写指南](./user-manual/04-skill-md-authoring.md)
- [技能生命周期用户手册](./user-manual/08-skill-lifecycle.md)
- [渐进式功能披露](./technical/44-progressive-disclosure.md)

## 当前实现概览

- **内置技能**位于 `backend/skills/builtin/`，由 `SkillRegistry` 注册。
- **用户技能**使用 `SKILL.md`，由 `backend/skills/skill_md/loader.py` 从以下根目录发现：`$SAGE_SKILLS_DIR`、项目目录 `./skills`、用户目录 `~/.sage/skills`。
- **桌面入口**是顶级 `/skills` 页面；Electron IPC 将技能操作转发到 `/api/v1/skills*` REST 路由。
- **生命周期状态**由 `skill_lifecycle` 和 `skill_usage` SQLite 表支持；归档不会删除技能文件。

本页不再描述不存在的管理器、远程技能商店或 Tauri 命令。旧链接可以继续打开本页，但应以当前技术文档和用户手册为准。
