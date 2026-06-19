# 04. SKILL.md 编写指南

**最后更新**: 2026-06-19
**适用版本**: Sage v0.2+ (M4-M10 已完成)

## 4.1 什么是 SKILL.md

SKILL.md 是 Sage 兼容 [AgentSkills 开放规范](https://agentskills.io) 的 Markdown 技能描述文件。每个技能是一个独立目录,内含 `SKILL.md` 与可选的 `scripts/`、`references/`、`assets/`、`templates/` 子目录。

```
~/.sage/skills/
├── code-review/
│   ├── SKILL.md           # 技能描述 (必填)
│   └── scripts/
│       └── lint.py        # 可选: 脚本
└── commit/
    ├── SKILL.md
    └── references/
        └── style.md       # 可选: 引用文档
```

## 4.2 SKILL.md 最小骨架

```markdown
---
name: my-skill
description: 一句话描述这个技能做什么
---

# 详细指令 (Markdown 自由格式)

告诉 LLM 怎么用这个技能。例如:
- 角色设定
- 输入格式要求
- 输出格式要求
- 工作流步骤
```

**最小必填字段**: `name` (合法 slug,小写字母/数字/连字符) + `description` (非空字符串)。

## 4.3 完整 frontmatter 字段参考

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `name` | string | **必填** | 技能 slug,小写字母/数字/连字符 |
| `description` | string | **必填** | 一句话描述 |
| `triggers` | string[] | `[name]` | 触发关键词列表 (大小写不敏感) |
| `version` | string | — | 语义版本号 (展示在 UI) |
| `requires.bins` | string[] | `[]` | 依赖的可执行文件 (如 `git`, `docker`) |
| `requires.env` | string[] | `[]` | 依赖的环境变量名 |
| `requires.config` | string[] | `[]` | 依赖的配置项 (dotted path) |
| `os` | string[] | `[]` | 允许的操作系统 (`macos`/`linux`/`windows`) |
| `always` | bool | `false` | true → 跳过所有门控,始终加载 |
| `user-invocable` | bool | `false` | true → 暴露为 slash command (用户可主动调用) |
| `user-invocable-name` | string | — | slash command 名 (如 `/review`),缺省用 `/{name}` |
| `command-dispatch` | string | `auto` | `auto` (LLM 决定) / `tool` (强制工具调用) / `prompt` (注入 prompt) |
| `disable-model-invocation` | bool | `false` | true → 不进 system prompt,仅手动触发 |
| `metadata` | object | `{}` | 自由元数据 (供前端展示) |

## 4.4 典型示例

### 4.4.1 纯 prompt 技能 (最常见)

```markdown
---
name: code-review
description: 对代码 diff 做评审,关注正确性、复用、简化
triggers: [review, code review, 评审]
version: 0.2.0
user-invocable: true
user-invocable-name: /review
---

你是一个严谨的代码评审员。对每个 diff,逐项检查:

- **正确性**:边界条件、并发、错误处理
- **复用**:是否有可复用的现有 helper
- **简化**:能否用更清晰的写法

输出格式:
1. 严重问题 (必须修复)
2. 建议 (可选)
3. 总结 (1-2 句)
```

在聊天框输入 `/review` 即可触发。

### 4.4.2 带门控的技能

```markdown
---
name: docker-deploy
description: 部署 Docker 镜像到生产环境
requires:
  bins: [docker]
  env: [DOCKER_REGISTRY_TOKEN]
os: [linux, macos]
---

# Docker 部署流程
...
```

只有当 `docker` 命令存在 + `DOCKER_REGISTRY_TOKEN` 环境变量已设置 + 当前平台是 Linux/macOS 时,该技能才会被加载。

### 4.4.3 带脚本的技能 (高级)

```
~/.sage/skills/git-summary/
├── SKILL.md
└── scripts/
    └── summarize.py    # 用户脚本
```

`SKILL.md`:

```markdown
---
name: git-summary
description: 生成 git 仓库的代码摘要
user-invocable: true
user-invocable-name: /summary
---

调用 `scripts/summarize.py` 生成摘要。脚本在沙箱中执行,
用户会被询问确认。
```

执行时:用户输入 `/summary` → 弹出确认框 → 用户批准 → 沙箱执行 `summarize.py`。

## 4.5 加载位置与优先级

Sage 按以下顺序搜索 SKILL.md 目录 (找到第一个存在的):

1. `$SAGE_SKILLS_DIR` 环境变量指向的目录
2. `<cwd>/skills/`
3. `~/.sage/skills/`

**冲突处理**: 与 builtin 技能同名时,builtin 永远胜,SKILL.md 被跳过 + WARNING 日志。

## 4.6 常见错误

### 4.6.1 name 不合法

```yaml
# ❌ 错误 (大写字母/下划线/空格)
name: Code_Review

# ✅ 正确
name: code-review
```

### 4.6.2 与 builtin 冲突

若你的 SKILL.md 名为 `search`,会被 builtin 跳过。改名即可。

### 4.6.3 scripts 路径越界

脚本必须位于技能目录下。`../escape.py` 会被路径校验拒绝。

### 4.6.4 os 拼写错

```yaml
# ❌ 错误
os: [solaris]

# ✅ 正确 (仅支持 macos/linux/windows)
os: [macos, linux]
```

## 4.7 下一步

- 想把现有 builtin 转成 SKILL.md? 看 [05-skill-md-migration.md](./05-skill-md-migration.md)
- 想了解 SKILL.md 的内部机制? 看 [`../technical/24-skills-system.md`](../technical/24-skills-system.md)