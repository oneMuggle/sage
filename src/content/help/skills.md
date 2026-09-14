# 技能系统

Sage 支持通过**技能(Skills)**扩展功能,让你可以自定义 AI 的行为和能力。

## 什么是技能?

技能是一组预定义的指令或工具,用于:

- **扩展 AI 能力**: 让 AI 执行特定任务(如代码审查、数据分析)
- **自定义行为**: 调整 AI 的回复风格和格式
- **集成外部工具**: 调用脚本、API 或其他服务

## 技能类型

### 1. 内置技能(Builtin)

Sage 预装的技能,开箱即用:

| 技能名 | 用途 | 触发方式 |
|---|---|---|
| `code-review` | 代码审查 | `@code-review` 或自动识别 |
| `commit` | 生成 commit message | `@commit` 或提交代码时 |
| `office` | Office 文档处理 | 自动识别文档操作 |
| ... | ... | ... |

### 2. 用户技能(SKILL.md)

你可以创建自定义技能:

- **位置**: `~/.sage/skills/<技能名>/SKILL.md`
- **格式**: Markdown + frontmatter
- **功能**: 自定义 prompt、脚本、工具调用

## 使用技能

### 1. 在对话中调用

使用 `@技能名` 前缀:

```
@code-review 帮我审查这段代码
```

或让 AI 自动识别:

```
这段代码有什么问题?
```

(AI 会自动调用 code-review 技能)

### 2. 通过命令面板

1. 按 `Ctrl/Cmd + K` 打开命令面板
2. 输入技能名或斜杠命令
3. 选择技能并执行

### 3. 在设置中配置

1. 打开**设置** → **技能**
2. 查看已安装的技能列表
3. 启用/禁用特定技能
4. 调整技能参数

## 技能页面

### 打开技能页面

1. 点击左侧导航栏的**技能**图标
2. 查看所有可用技能

### 技能卡片

每个技能显示:

- **名称**: 技能标识符
- **描述**: 一句话说明
- **版本**: 版本号(如有)
- **来源**: `builtin` 或 `skillmd`
- **状态**: 活跃 / 已冷 / 已归档
- **使用次数**: 历史调用次数

### 技能详情

点击技能卡片查看:

- **完整描述**: 详细说明
- **触发条件**: 何时自动触发
- **使用示例**: 典型用法
- **配置选项**: 可调整的参数

## 技能生命周期

### 三种状态

| 状态 | 含义 | 显示 |
|---|---|---|
| **活跃(Active)** | 最近使用过 | 绿色徽章 |
| **已冷(Stale)** | 30 天未使用 | 灰色徽章 |
| **已归档(Archived)** | 用户主动归档 | 橙色徽章 |

### 归档技能

1. 找到要归档的技能
2. 点击"归档"按钮
3. 技能从默认列表隐藏(可随时恢复)

### 取消归档

1. 在"已归档"视图中找到技能
2. 点击"取消归档"
3. 技能恢复到活跃列表

### 删除技能

> **注意**: 只有用户技能可以删除,内置技能不能删除

1. 找到要删除的技能
2. 点击"删除"按钮
3. 确认删除(不可恢复)

## 创建自定义技能

### 基本结构

```
~/.sage/skills/
└── my-skill/
    ├── SKILL.md           # 技能描述(必填)
    ├── scripts/           # 可选: 脚本
    │   └── process.py
    └── references/        # 可选: 引用文档
        └── guide.md
```

### SKILL.md 格式

```markdown
---
name: my-skill
description: 一句话描述这个技能
triggers: [my-skill, 自定义]
version: 1.0.0
user-invocable: true
---

# 技能指令

你是一个专业的 XX 助手。当用户请求时:

1. 分析输入
2. 执行特定处理
3. 返回格式化结果

## 输出格式

```json
{
  "result": "...",
  "confidence": 0.95
}
```
```

### Frontmatter 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | 技能标识符(必填) |
| `description` | string | 一句话描述(必填) |
| `triggers` | string[] | 触发关键词 |
| `version` | string | 版本号 |
| `user-invocable` | bool | 是否可通过斜杠命令调用 |
| `always` | bool | 是否始终加载(跳过门控) |

### 脚本集成

在 `scripts/` 目录放置脚本:

```python
# scripts/analyze.py
import sys

def main():
    data = sys.stdin.read()
    # 处理数据
    print("分析结果")

if __name__ == "__main__":
    main()
```

在 SKILL.md 中引用:

```markdown
## 工具调用

使用 `scripts/analyze.py` 处理数据。
```

## 技能示例

### 示例 1: 代码审查技能

```markdown
---
name: code-review
description: 审查代码变更,关注正确性和安全性
triggers: [review, 审查]
user-invocable: true
---

你是一个严谨的代码审查员。对每个 diff:

1. 检查边界条件和错误处理
2. 识别潜在的安全问题
3. 建议可复用的现有代码
4. 提出简化建议

输出格式:
- 问题列表(按严重程度排序)
- 改进建议
- 总体评价
```

### 示例 2: 数据分析技能

```markdown
---
name: data-analyst
description: 分析 CSV/Excel 数据并生成报告
triggers: [analyze, 分析]
---

你是一个数据分析师。当用户提供数据时:

1. 读取并理解数据结构
2. 执行统计分析
3. 生成可视化图表
4. 输出 insights 报告

使用 pandas 和 matplotlib 处理数据。
```

## 常见问题

### Q: 如何安装社区技能?

A:
1. 从 GitHub 下载技能目录
2. 放到 `~/.sage/skills/` 目录
3. 重启 Sage 或刷新技能列表

### Q: 技能会消耗 Token 吗?

A:
- 技能的 prompt 会占用一些 Token
- 但通常只占对话总 Token 的 5-10%
- 可以在设置中查看技能 Token 消耗

### Q: 如何调试技能?

A:
1. 打开开发者工具(Ctrl+Shift+I)
2. 查看 Console 日志
3. 检查技能是否正确加载
4. 验证触发条件是否匹配

### Q: 技能可以调用外部 API 吗?

A:
- 可以,通过 `scripts/` 目录的脚本
- 脚本可以调用任何 API
- 需要在脚本中处理认证和错误

### Q: 如何分享我的技能?

A:
1. 将技能目录上传到 GitHub
2. 创建 SKILL.md 说明文档
3. 分享到社区或技能市场

## 下一步

- 学习[编写 SKILL.md](../../../docs/user-manual/04-skill-md-authoring.md)详细指南
- 了解[技能生命周期](../../../docs/user-manual/08-skill-lifecycle.md)管理
- 探索[Office 文档处理](./office.md)技能用法
