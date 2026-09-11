# 用户手册

> Sage 终端用户的操作指南。本目录面向"会用 Sage 的人",不涉及开发实现。

## 章节目录

| 编号 | 标题                                                     | 一句话简介                                                              |
| ---- | -------------------------------------------------------- | ----------------------------------------------------------------------- |
| 01   | [桌面端安装与启动](./01-desktop.md)                      | 系统要求 / 安装步骤 / 启动与故障排查                                     |
| 02   | [指标监控](./02-metrics.md)                              | 性能指标查看 / 资源占用 / 调试开关                                       |
| 03   | [Wiki 知识库](./03-wiki.md)                              | 创建/编辑文档 / 版本管理 / LLM 问答                                      |
| 04   | [SKILL.md 编写指南](./04-skill-md-authoring.md)          | 自定义技能: frontmatter 字段 / scripts/ 脚本 / gating 条件 / dispatch   |
| 05   | [从 builtin 迁移到 SKILL.md](./05-skill-md-migration.md) | 内置技能转 SKILL.md 的路径与限制                                        |
| 06   | [诊断与日志](./06-diagnostics.md)                       | 日志文件位置 / 查看方式 / 反馈问题步骤 / 保留策略 / 隐私说明            |
| 07   | [产物面板 (Artifacts Panel)](./07-artifacts-panel.md) | Chat 右侧抽屉 Artifacts Tab：write_file 写盘追踪 / 多格式预览 / 在文件管理器中定位 |
| 08   | [技能生命周期 (Skills Lifecycle)](./08-skill-lifecycle.md) | 技能 active/stale/archived 三态徽章 / 手动归档与取消归档 / 与删除的区别 |
| 09   | [Office 文档管理](./09-office.md) | 在 Sage 中用自然语言增删改查 docx/xlsx/pptx 文档：创建 / 修改 / 归档 / 恢复 / chat 内 @文件名引用 + write_file 二进制防护 |
| 10   | [用量与缓存面板](./10-usage-and-cache.md) | 设置 → 通用 → 用量卡片：请求/Token/成本汇总 + 缓存命中率 + 4 个 range tab + 请求明细分页 + SVG 趋势图 + CSV 导出（UTF-8 BOM，Excel 双击不乱码） |
| 11   | [sage doctor CLI](./11-sage-doctor.md) | 安装/环境级 self-check：Win7 LTS、白屏、conda 错配一键诊断（退出码 0/1/2 + --json 机器可读） |
| 12   | [本地开发环境助手](./12-local-development-assistant.md) | 设置 → 开发环境 Tab：自动发现 Python/Node.js 运行时 + 项目诊断 + 试跑代码片段 |
| 13   | [期刊模板面板](./13-journal-template-panel.md) | Office 页面底部：模板规范抽取 / 论文格式校验 / 结构化填充生成符合期刊要求的 Word 文档 |
| 14   | [可插拔更新源](./14-update-providers.md) | 设置 → 更新源 tab：添加 GitHub/Gitee/GitLab/自建 HTTP 源 + 设为默认 + 测试连接 + 删除；token 用 safeStorage 加密存储，IPC 返回自动 mask |

---

_本目录文档命名规则:`XX-topic-name.md`(XX 为两位数字)。_