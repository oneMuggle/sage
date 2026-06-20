# 05. 从 builtin 迁移到 SKILL.md

**最后更新**: 2026-06-19
**适用版本**: Sage v0.2+

## 5.1 为什么迁移

Sage 内置 4 个 Python 技能 (`search` / `writer` / `coder` / `travel`),写死在 `backend/skills/` 目录。这些 builtin 与外部生态 (Hermes Agent / OpenClaw / Claude Skills) 不兼容。

迁移到 SKILL.md 的好处:

- **开放规范**: 兼容 agentskills.io,可与生态互操作
- **用户可定制**: 不改 Python 源码即可调整 prompt / 添加脚本
- **多源加载**: 个人技能 (`~/.sage/skills/`)、项目技能 (`<cwd>/skills/`)、环境变量覆盖

## 5.2 builtin vs SKILL.md 对照

| builtin (Python) | SKILL.md (Markdown) | 可迁移? |
|---|---|---|
| `search` (网络搜索) | ❌ 需 web_search tool,无 SKILL.md 替代 | 否 |
| `writer` (写文档) | ✅ 纯 prompt 技能 | 是 |
| `coder` (写代码) | ✅ 纯 prompt 技能 | 是 |
| `travel` (行程规划) | ✅ 纯 prompt 技能 | 是 |

**关键判断标准**:
- ✅ 可迁移: 仅用 LLM 推理 + prompt 模板
- ❌ 不可迁移: 依赖 Python 工具函数 (`web_search` 等)、外部 API key、或特定运行时

## 5.3 迁移步骤

### 5.3.1 找到 builtin 的 prompt 模板

```bash
# builtin prompt 在 backend/skills/ 下
grep -A 30 "def execute" backend/skills/writer.py | head -50
```

通常在 `execute()` 方法的 docstring 或返回的 `content` 字段里。

### 5.3.2 创建 SKILL.md 目录

```bash
mkdir -p ~/.sage/skills/writer
```

### 5.3.3 写 frontmatter + body

```markdown
---
name: writer
description: 帮我写各类文档(邮件、报告、文章)
triggers: [write, 写, 帮我写]
version: 0.1.0
user-invocable: true
user-invocable-name: /write
---

# 写作助手

[粘贴原 builtin prompt 的核心指令]

## 输出格式

- 邮件:主题 + 正文 + 签名
- 报告:标题 + 摘要 + 要点 + 结论
- 文章:标题 + 引言 + 主体 + 结尾
```

### 5.3.4 重启 Sage,验证

1. 重启后端 (`python backend/main.py`)
2. 打开 Skills 面板 → 应看到 `writer` 标记为 `skillmd` (不是 builtin)
3. 输入 `/write` 验证 slash command 工作

## 5.4 注意事项

### 5.4.1 builtin 永远胜

如果你的 SKILL.md 与 builtin 同名,builtin 会"霸占"这个名字,SKILL.md 被跳过 + WARNING。两种选择:

1. 改 SKILL.md 的 `name` (推荐,如 `writer-custom`)
2. 改 `user-invocable-name` 为 `/my-write`,让 builtin 仍是 `writer` 但你用 `/my-write` 调用自定义版本

### 5.4.2 不要破坏 builtin

迁移到 SKILL.md 是"并存"而非"替换"。builtin 始终可用,你的 SKILL.md 是新增。

### 5.4.3 prompt 差异

SKILL.md 的 body 是 Markdown 自由格式,builtin 用 Python docstring。转换时:

- 把 `"""..."""` 里的核心指令搬到 body
- 移除 Python 特有的语法 (`f-string`, 类型注解等)
- 保留所有"角色设定"和"输出格式要求"

## 5.5 回滚

如果你想撤回迁移:

```bash
# 删除自定义 SKILL.md 即可,builtin 仍可用
rm -rf ~/.sage/skills/writer
```

## 5.6 下一步

- 不确定 frontmatter 怎么写? 看 [04-skill-md-authoring.md](./04-skill-md-authoring.md)
- 想给迁移后的技能加脚本? 在 `scripts/` 目录加 `.py` 文件,见 §4.4.3