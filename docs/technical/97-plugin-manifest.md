# 97 - 插件系统架构

> 日期：2026-09-26
> 作者：Claude
> 标签：插件、可扩展性、Pydantic v2

## 概述

Sage 插件系统提供可扩展的架构，允许第三方开发者通过标准化接口扩展 Sage 的功能。
系统由三个核心组件构成：

1. **插件清单（Manifest）**：定义插件元数据和能力声明
2. **生命周期管理（Lifecycle）**：管理插件的安装、启用、禁用、卸载
3. **能力注册（Capability Registry）**：动态注册插件提供的 tools/skills/hooks

## 架构设计

### 组件关系

```
┌─────────────────┐
│  plugin.json    │ ← 清单文件
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│  PluginManifest         │ ← Pydantic v2 校验
│  (manifest.py)          │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  PluginLifecycleManager │ ← 状态管理 + SQLite 持久化
│  (lifecycle.py)         │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  CapabilityRegistry     │ ← 动态注册到 Agent 系统
│  (registry.py)          │
└─────────────────────────┘
```

## 插件清单 Schema

### plugin.json 格式

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "A sample plugin",
  "author": "Developer Name",
  "homepage": "https://example.com",
  "license": "MIT",
  "min_sage_version": "0.4.0",
  "dependencies": {
    "other-plugin": ">=1.0.0"
  },
  "capabilities": {
    "tools": [
      {
        "name": "my_tool",
        "description": "A custom tool",
        "entry_point": "tools.my_tool:MyTool"
      }
    ],
    "skills": [
      {
        "name": "my_skill",
        "description": "A custom skill",
        "entry_point": "skills.my_skill:MySkill"
      }
    ],
    "hooks": [
      {
        "name": "my_hook",
        "event": "before_chat",
        "entry_point": "hooks.my_hook:on_before_chat"
      }
    ]
  },
  "permissions": {
    "network": false,
    "filesystem": ["read"],
    "database": false
  },
  "metadata": {
    "category": "productivity",
    "tags": ["example", "demo"]
  }
}
```

### PluginManifest 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | 插件唯一标识符（kebab-case） |
| `version` | string | ✅ | 语义化版本号（semver） |
| `description` | string | ✅ | 插件简短描述 |
| `author` | string | ✅ | 作者名称 |
| `homepage` | string | ❌ | 插件主页 URL |
| `license` | string | ❌ | 许可证（如 MIT、Apache-2.0） |
| `min_sage_version` | string | ❌ | 最低 Sage 版本要求 |
| `dependencies` | dict | ❌ | 依赖的其他插件及版本约束 |
| `capabilities` | dict | ✅ | 声明的能力（tools/skills/hooks） |
| `permissions` | dict | ❌ | 权限声明（network/filesystem/database） |
| `metadata` | dict | ❌ | 额外元数据（category/tags） |

## 生命周期管理

### 插件状态

```
┌─────────┐     install     ┌──────────────┐
│  Not    │ ───────────────▶ │  Installed   │
│ Installed│                 │  (disabled)  │
└─────────┘                 └──────┬───────┘
     ▲                             │ enable
     │                             ▼
     │                      ┌──────────────┐
     │      disable         │   Enabled    │
     └──────────────────────│  (running)   │
                            └──────┬───────┘
                                   │ uninstall
                                   ▼
                            ┌──────────────┐
                            │  Uninstalled │
                            └──────────────┘
```

### PluginLifecycleManager API

```python
from backend.plugins.lifecycle import PluginLifecycleManager

manager = PluginLifecycleManager()

# 安装插件
manifest = manager.install_plugin("/path/to/plugin")

# 启用插件
manager.enable_plugin("my-plugin")

# 禁用插件
manager.disable_plugin("my-plugin")

# 卸载插件
manager.uninstall_plugin("my-plugin")

# 恢复已删除的插件
manager.restore_plugin("my-plugin")

# 查询插件状态
status = manager.get_plugin_status("my-plugin")
print(status.state)  # PluginState.ENABLED
```

### 状态持久化

插件状态存储在 SQLite 数据库中：

- **默认路径**：`~/.sage/plugins.db`
- **表名**：`plugin_state`
- **字段**：
  - `name TEXT PRIMARY KEY` - 插件名称
  - `state TEXT` - 状态（not_installed/installed/enabled/disabled）
  - `install_path TEXT` - 安装路径
  - `installed_at TIMESTAMP` - 安装时间
  - `enabled_at TIMESTAMP` - 启用时间
  - `disabled_at TIMESTAMP` - 禁用时间
  - `uninstalled_at TIMESTAMP` - 卸载时间

## 能力注册

### CapabilityRegistry API

```python
from backend.plugins.registry import CapabilityRegistry

registry = CapabilityRegistry()

# 注册工具
registry.register_tool(
    plugin_name="my-plugin",
    tool_name="my_tool",
    tool_class=MyToolClass,
    description="A custom tool"
)

# 注册技能
registry.register_skill(
    plugin_name="my-plugin",
    skill_name="my_skill",
    skill_class=MySkillClass
)

# 注册钩子
registry.register_hook(
    plugin_name="my-plugin",
    hook_name="my_hook",
    event="before_chat",
    callback=on_before_chat
)

# 查询已注册的能力
tools = registry.list_tools()
skills = registry.list_skills()
hooks = registry.get_hooks_for_event("before_chat")

# 卸载插件的所有能力
registry.unregister_plugin("my-plugin")
```

### 能力类型

| 类型 | 说明 | 示例 |
|------|------|------|
| **Tools** | Agent 可调用的工具函数 | 代码执行、文件操作、API 调用 |
| **Skills** | 预定义的技能模板 | 写作辅助、数据分析、翻译 |
| **Hooks** | 事件回调函数 | 聊天前处理、消息后处理 |

## 安全检查

### 权限模型

插件必须在清单中声明所需权限：

```json
{
  "permissions": {
    "network": true,
    "filesystem": ["read", "write"],
    "database": true
  }
}
```

安装时，Sage 会：

1. 验证权限声明
2. 提示用户确认
3. 在沙箱环境中运行插件

### 依赖冲突检测

```python
# 检查依赖是否满足
if not manager.check_dependencies(manifest):
    missing = manager.get_missing_dependencies(manifest)
    raise PluginDependencyError(f"Missing dependencies: {missing}")
```

## 文件位置

| 文件 | 说明 |
|------|------|
| `backend/plugins/manifest.py` | 清单模型和校验 |
| `backend/plugins/lifecycle.py` | 生命周期管理 |
| `backend/plugins/registry.py` | 能力注册表 |
| `backend/plugins/__init__.py` | 模块导出 |
| `backend/tests/unit/test_plugin_manifest.py` | 清单测试（23 测试） |
| `backend/tests/unit/test_plugin_lifecycle.py` | 生命周期测试（21 测试） |

## 测试覆盖

```bash
# 运行插件系统测试
pytest backend/tests/unit/test_plugin_manifest.py -v
pytest backend/tests/unit/test_plugin_lifecycle.py -v
```

**测试统计**：
- 清单校验：23 测试
- 生命周期管理：21 测试
- 总计：44 测试

## 示例插件

### 最小插件结构

```
my-plugin/
├── plugin.json
├── README.md
└── tools/
    └── my_tool.py
```

### plugin.json

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "My first Sage plugin",
  "author": "Your Name",
  "capabilities": {
    "tools": [
      {
        "name": "hello_world",
        "description": "Says hello",
        "entry_point": "tools.my_tool:HelloWorldTool"
      }
    ]
  }
}
```

### tools/my_tool.py

```python
from backend.tools.base import BaseTool

class HelloWorldTool(BaseTool):
    name = "hello_world"
    description = "Says hello to the world"

    async def execute(self, **kwargs):
        return "Hello, World!"
```

## 相关文档

- [24 - 技能系统](24-skills-system.md) - 技能注册和执行
- [27 - 多 Agent 编排](27-multi-agent-orchestration.md) - Agent 系统架构
- [插件开发指南](../user-manual/plugin-development.md) - 用户手册

## 变更日志

| 日期 | 版本 | 变更内容 | 作者 |
|------|------|----------|------|
| 2026-09-26 | v1.0 | 初始版本 | Claude |
