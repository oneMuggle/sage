# Sage 技能 (Skills) 使用指南

本指南说明如何使用、编写和调试 Sage 的技能系统。

---

## 一、内置技能

Sage 自带 4 个 Python 内置技能，开箱即用：

| 名称       | 用途                                   |
|------------|----------------------------------------|
| `search`   | 网络搜索与信息提取                     |
| `writer`   | 长文本写作与文档生成                   |
| `coder`    | 代码生成、调试、重构                   |
| `travel`   | 旅行规划与行程推荐                     |

这些技能会被模型自动识别并在合适时机调用。

> 实际可用列表以 `backend/skills/__init__.py::register_all_skills` 注册结果为准，
> 启动时会随版本演进。文档中的名字必须能在 `backend/tests/unit/test_skill_help_doc.py`
> 校验通过。

---

## 二、SKILL.md 自定义技能

### 2.1 放置位置（按优先级）

Sage 按以下顺序扫描 SKILL.md 文件：

1. **环境变量 `$SAGE_SKILLS_DIR`**（最高优先级）
2. **Settings 中的 `skills_dir` 字段**（用户通过配置指定）
3. **当前工作目录下的 `./skills/`**
4. **`~/.sage/skills/`**（用户全局目录）
5. **打包的 shipped 目录**（只读模板，仅当以上都无同名技能时生效）

每个技能是一个目录，结构：

```
<name>/
├── SKILL.md          # 必须：元数据 + 提示词正文
└── scripts/          # 可选：脚本文件（受 ScriptRunner 安全约束）
```

也支持单文件形态 `<dir>/SKILL.md`（深度 1）。

### 2.2 SKILL.md 前置字段（frontmatter）

```yaml
---
name: my-skill                       # 必须：技能名（小写 + 短横线，≤64 字符）
description: "一句话说明"              # 必须：用途简介
version: "1.0.0"                     # 可选：语义化版本
triggers:                            # 可选：触发关键词（模型辅助识别）
  - "关键字 A"
  - "关键字 B"
when-to-use: "详细说明何时使用"        # 可选：自动激活依据 (A16)
requires:                            # 可选：加载条件
  bins: [git, docker]                #   必须存在的二进制
  env: [OPENAI_API_KEY]              #   必须存在的环境变量
  config: [permission_mode]          #   必须在 settings 中存在且有值的键
os: [macos, linux]                   # 可选：平台过滤
always: false                        # 可选：跳过 requires 检查（平台仍生效）
user-invocable: true                 # 可选：允许用户用 /name 触发
user-invocable-name: /custom         # 可选：自定义 slash 命令名
disable-model-invocation: false      # 可选：禁止模型自动调用（仅用户手动）
command-dispatch: auto               # 可选：auto / tool / prompt
license: MIT                         # 可选：许可证
compatibility: "Sage ≥ 0.2"          # 可选：兼容性声明
allowed-tools:                       # 可选：白名单工具
  - bash
  - read
---
这里是技能正文，作为 system prompt 注入到模型调用。
```

### 2.3 字段语义

- `when-to-use`（或 `when_to_use`）：自动激活依据。模型在对话中匹配到该描述时主动调用，
  **不要与 `triggers` 混淆** —— `triggers` 只是关键词提示，`when-to-use` 是完整语义匹配。
- `requires.config`：依赖 settings 表中的键。`permission_mode` / `auto_memory` 等都是
  合法的键；不存在的键会报 `unknown config key`，技能被跳过。
- `always: true`：跳过 `requires.bins/env/config` 检查，但 `os` 仍然生效。
- `user-invocable: true`：让用户能在输入框用 `/name` 触发，否则仅模型可调用。
- `command-dispatch`：`auto`（自动判断 prompt/tool）/ `tool`（强制工具调用）/
  `prompt`（强制 prompt 注入）。

---

## 三、触发方式

### 3.1 模型自动调用

模型根据 `description` / `when-to-use` / `triggers` 判断是否调用。无需用户干预。

### 3.2 实体引用 `@skill:<name>`

在输入框使用 `@skill:<name>` 显式提示模型使用该技能。例如：

```
请用 @skill:writer 帮我写一份技术报告
```

> 注意：不是 `@writer` 也不是 `@技能名`，必须用 `@skill:<name>` 格式。
> 参见 `backend/chat/entity_refs.py::_ENTITY_RE`。

### 3.3 Slash 命令 `/name`

如果 SKILL.md 设置了 `user-invocable: true`，可以用 `/name` 直接触发：

```
/writer 写一份 Q1 总结
```

> Slash 命令只列出 `user-invocable: true` 的技能；其他技能仅模型可调用。

---

## 四、技能调试

- 技能加载失败会记录在启动日志中，常见原因：
  - `parse_error`：YAML 格式错误
  - `invalid_name`：`name` 字段不匹配 `^[a-z0-9-]{1,64}$`
  - `missing bin: <name>`：依赖的二进制未安装
  - `missing env: <name>`：依赖的环境变量未设置
  - `missing config: <key>`：settings 中该键未设置或为空
  - `unknown config key: <key> (not in settings whitelist)`：settings 中不存在该键
  - `platform mismatch`：当前 OS 不在 `os` 列表内
  - `builtin_conflict`：与内置技能同名（内置永远优先）
  - `duplicate_skillmd`：多个目录有同名 SKILL.md（高优先级目录优先）
  - `reload_failed`：热重载时解析或门控失败
- 在聊天输入框输入 `/` 可查看当前可用的 slash 命令列表。
- 技能变更后（新建 / 编辑 / 删除 SKILL.md），前端会收到通知并自动刷新 slash 列表，
  无需重启应用（见 `/api/v1/skills/notifications` NDJSON 端点）。

---

## 五、技能管理

### 5.1 导入

- 通过设置面板导入 `.sk` 技能包或包含 SKILL.md 的目录。
- 也可直接把 SKILL.md 放到 `~/.sage/skills/<name>/SKILL.md`。

### 5.2 编辑

- 直接编辑磁盘上的 SKILL.md 文件。文件保存后，可通过 `POST /api/v1/skills/rescan`
  触发重扫（或直接等通知机制识别文件变化）。
- 编辑后 slash 菜单会自动更新。

### 5.3 删除

- 通过设置面板或 `DELETE /api/v1/skills/{name}` 物理删除。
- 内置技能不可删除。

### 5.4 归档

- 归档是软删除（`POST /api/v1/skills/{name}/archive`），文件保留但不再参与自动激活
  和 slash 候选。可恢复。

---

## 六、常见问题

**Q：我写的 SKILL.md 没被加载？**
A：检查启动日志中的 skip 原因（见第四节）。最常见是 `name` 格式错误、`requires` 条件
不满足、或放置位置不在扫描路径。

**Q：模型没调用我的技能？**
A：`description` 和 `when-to-use` 写得不够明确。把它们当成给同事的说明 —— 如果同事
看不懂什么时候该用，模型也看不懂。

**Q：slash 菜单不显示新装的技能？**
A：确认 SKILL.md 中有 `user-invocable: true`。技能变更后通知中枢会自动推送刷新。

**Q：为什么我的技能被标记为 `missing config: permission_mode`？**
A：`permission_mode` 必须在 settings 表中有值。通过设置面板配置该项，或者把 `requires.config`
从 SKILL.md 中移除。

---

## 七、与外部系统的关系

- **Prompt 模板**：技能是"长期提示词"的载体；模板是"一次性提示词"。技能适合反复使用
  的工作流（如 `writer` / `coder`），模板适合一次性任务（如"生成会议纪要"）。
- **Memory**：技能可调用 `memory` 相关工具读写记忆，形成"有状态的技能"。
- **Entity refs**：`@skill:<name>` 是显式触发；模型自动调用是隐式触发。两者最终都
  走 `InprocSkillAdapter.execute`。
