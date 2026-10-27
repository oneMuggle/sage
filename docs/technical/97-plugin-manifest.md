# 97 - 插件系统架构

> 日期：2026-09-26
> 作者：Claude
> 标签：插件、可扩展性、Pydantic v2

> **当前契约（R82/R83/R86/R90/R92/R94/R95/R96/R97/R98/R99/R100/R101/R102/R103/R104/R105/R106/R107/R108/R109/R110/R111，2026-10-27）**：本文后半部分保留了早期设计示例，
> 个别 JSON/API 形态已经过时。现行实现以 `backend/plugins/manifest.py` 的
> 数组形 `capabilities` 为准：R82 只保存生命周期记录且不执行代码；R83 只显式
> 托管带 entry_point 的 Python `tool`，子进程不是安全沙箱；R86 提供
> `python -m backend.cli.plugin` 脚手架、静态校验与离线索引；R90 只把已显式
> 启动且声明 object 形 `input_schema` 的进程外 tool 以
> `plugin__<plugin>__<capability>` 发布到聊天 `ToolRegistry`，并在 runtime
> stop/fail 时同步注销；R92 起 agent profile 工具白名单除完整名外还承认
> `plugin__*` / `plugin__<plugin>__*` 两种受限通配（schema 过滤、并行
> 预检与执行边界共用 `domain/tool_names.py` 的 matcher，调用仍逐次
> 审批）；R94 起 `GET /api/v1/plugins/runtime/tools` 返回桥接已发布
> 工具的只读快照（完整名、描述、风险与规范化权限），且只刷新已运行
> session、不启动插件，Agent 编辑页据此生成完整名复选框（通配覆盖
> 项禁用）；R95 起审批「记住我的选择」可显式选精确工具或整个
> 插件，待审批请求的 `plugin_name` 只来自桥接已发布记录，客户
> 端只传 `remember_scope`，`plugin__<plugin>__*` 权限规则只能
> 由服务端校验归属后派生；R96 起 `PermissionEnforcer` 匹配这
> 两种受限插件通配时改用执行边界从桥接当前发布记录得到的权威
> `plugin_name`，不再只做字符串前缀 fnmatch，legacy agent 与
> `InprocToolAdapter` 共用该口径，身份未知或不匹配时该通配不
> 命中（普通字符串规则不在本轮变更内）；R97 起
> `GET /api/v1/permissions/rules` 与
> `POST /api/v1/permissions/rules/delete`（带 Origin
> 守卫）让设置页能按 `parse_rules` 口径查看并逐条删除已保存
> 规则，规则创建仍只能由审批 remember 或服务端派生；R98 起
> profile 白名单的受限插件通配同步改结构化：registry 用已
> 注册 `PluginTool` 自带的发布身份、agent 三道闸查桥接当前
> 发布记录、前端覆盖镜像用已发布快照的 `plugin_name`，身份
> 缺失或不匹配时通配不命中，精确条目不变；R99 起 remember
> 落规则时对完全相同的 `(tool_pattern, decision)` 去重
> （同 pattern 不同 decision 照常追加），删除端点改按内容
> 定位第一条完全一致的规则而非列表下标，期间新记规则不会
> 让删除删错行，删除体中的 pattern 只作撤销选择子、不能
> 创建或放宽任何规则；R100 起
> `POST /api/v1/permissions/rules/clear`（无请求体、带
> Origin 守卫）可一键把规则列表写空，设置页对应「全部
> 删除」按钮先经 confirmDialog 确认——只撤销全部持久信任，
> 不提供按条件删除的写面；R101 起规则列表响应附带只读
> 派生的 `plugin_name`/`plugin_status` 归属标注（归属只认
> 生命周期记录 + 结构化命名空间，不切分工具名猜名；
> 卸载/无记录才在设置页显徽标，标注永不落盘也不影响
> 求值）；R102 起
> `POST /api/v1/permissions/rules/delete-by-plugin` 以
> 生命周期在册的权威插件名为唯一选择子整组删除其已
> 保存规则（删除集合与 R101 归属判定同源，名字不在册
> 400、索引不可用 503，均不写存储），设置页据归属
> 汇总出按插件删除操作；R103 起插件页 best-effort 复用
> 同一标注计数，在已卸载插件卡片上提示其孤儿规则并
> 可就地走 R102 删除（卸载本身仍不联动删规则）；
> R104 起无生命归属的 missing 孤儿可经
> `delete-orphans` 整组清理（服务端同口径选集）；
> R105 起审批记住可只记本次会话（进程内会话规则与
> 持久规则同按 deny > allow > ask 合并，重启即失）；
> R106 起会话规则可在聊天顶栏查看并逐条撤销/整会
> 话清空（只删不建，删除恒为回到逐次询问）；
> R107 起 Agent 白名单中未发布的插件形条目在编辑
> 表单内按同归属口径标注（已卸载/无记录/未发布，
> 纯前端复用发布快照与生命周期名单）并可就地移
> 除草稿条目；
> R108 起审批弹窗与审批等待通知展示工具的所属插
> 件（只读后端注入的权威 plugin_name）；
> R109 起规则管理器标注被更高优先级规则遮蔽、恒
> 不生效的已保存规则（只读派生，保守可证）；
> R110 起聊天顶栏弹层的自动放行审计标注所属插件、
> 会话规则同口径标注遮蔽（纯前端复用共享派生）；
> R111 起聊天转录的通用工具卡亦标注所属插件（名
> 单经共享缓存 hook 供数，读不到不标）。
> 开发
> 步骤请先看
> [插件开发：30 分钟跑通第一个插件](../user-manual/21-plugin-development.md)。

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
