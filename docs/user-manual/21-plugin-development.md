# 插件开发：30 分钟跑通第一个插件

> 适用范围：Sage 插件 manifest schema 1.0、R82 生命周期记录、R83 进程外宿主、R86 生态工具、R90 聊天工具桥与 R94 运行中插件工具动态选择器。

本指南带你从零生成一个 Python tool 插件，静态校验后在独立子进程里调用一次，再把它登记到可离线校验的静态索引。完成标准不是“生成了一堆文件”，而是这条链全部退出 0：

```text
init -> validate -> dev(invoke) -> index build -> index validate/search
```

## 1. 先分清三个状态

Sage 刻意把“登记”“启用”和“运行”拆开：

| 动作 | 实际发生什么 | 会不会执行插件代码 |
| --- | --- | --- |
| 安装插件记录 | 保存 manifest、版本和本地安装路径 | 否 |
| 启用插件记录 | 把生命周期状态改成 enabled | 否 |
| 启动运行 | 为 enabled 记录拉起独立 Python worker，并加载 tool 入口 | **是** |

进程外 worker 提供崩溃隔离、超时和资源边界，但它仍以当前 OS 用户运行，**不是安全沙箱**。只运行你审阅过的代码。manifest 权限声明用于安装确认与审计，不等于操作系统级文件/网络强制隔离。

当前宿主只执行 Python `tool` capability；进程外工具会进入插件 `CapabilityRegistry` 并可在设置页调用。声明了参数 `input_schema` 的 tool 在 runtime 被显式启动后，还会以 `plugin__<plugin>__<capability>` 发布给聊天 Agent 的 `ToolRegistry`；runtime 停止或失败时同步消失。安装或启用记录本身不会暴露工具。`skill`、`hook`、`mcp_server` 与 `command` 可以写进 manifest，宿主成熟度见模板表。

## 2. 前置条件

1. 已克隆 Sage 仓库，并按根目录 `CONTRIBUTING.md` 准备好能运行后端的 Python 环境；
2. 在仓库根目录执行下文命令；
3. 插件代码兼容 Python 3.8。脚手架生成代码只依赖标准库，不 import `backend.*`，所以插件自己的仓库也能独立测试。

先确认 CLI 可用：

```bash
python -m backend.cli.plugin templates
```

打包环境若提供 `sage plugin` wrapper，可把 `python -m backend.cli.plugin` 等价替换为 `sage plugin`。

## 3. 30 分钟路径

### 3.1 生成插件（约 3 分钟）

```bash
python -m backend.cli.plugin init hello-tool \
  --template tool \
  --output /tmp/hello-tool \
  --display-name "Hello Tool" \
  --author "Your Name"
```

Windows PowerShell 可把 `/tmp/hello-tool` 换成 `$env:TEMP\hello-tool`。生成目录包含：

```text
hello-tool/
├── plugin.json
├── handlers.py
├── examples/request.json
├── tests/test_plugin.py
├── .github/workflows/plugin-ci.yml
├── .gitignore
└── README.md
```

脚手架默认不覆盖同名生成文件。确认要刷新模板文件时用 `--force`；它只覆盖生成文件，不删除你的额外文件。

也可以直接研究仓库内已经生成的同构示例：`examples/plugins/hello-tool/`。

### 3.2 静态校验（约 2 分钟）

```bash
python -m backend.cli.plugin validate /tmp/hello-tool --strict
```

校验只读取 `plugin.json` 并对 Python 文件做 AST 解析，**不会 import 或执行插件代码**。它会检查 manifest schema、tool 入口文件、权限 `scope:action` 形态、Python 语法、README 与当前宿主是否支持该 capability。

### 3.3 进程外冒烟（约 5 分钟）

```bash
python -m backend.cli.plugin dev /tmp/hello-tool \
  --arguments-file /tmp/hello-tool/examples/request.json
```

这条命令会执行插件代码。它使用临时生命周期数据库完成“安装记录 → 启用 → 启动子进程 → invoke → 停止”，预期结果包含：

```json
{"message": "Hello, Ada!", "plugin": "hello-tool", "template": "tool"}
```

`examples/request.json` 避免了 Windows shell 的 JSON 引号差异。也可以用 `--arguments '<JSON object>'`；生命周期配置用 `--config` 或 `--config-file`。

### 3.4 改成你的工具（约 10 分钟）

编辑 `handlers.py`，保留 manifest 指定的 `handlers:run`：

```python
from typing import Any, Dict, Optional

_CONFIG: Dict[str, Any] = {}


def configure(config: Dict[str, Any]) -> None:
    _CONFIG.clear()
    _CONFIG.update(config or {})


def run(arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = arguments if isinstance(arguments, dict) else {}
    return {"echo": payload, "config_keys": sorted(_CONFIG)}
```

每次改完重跑：

```bash
python -m pytest /tmp/hello-tool/tests
python -m backend.cli.plugin validate /tmp/hello-tool --strict
python -m backend.cli.plugin dev /tmp/hello-tool \
  --arguments-file /tmp/hello-tool/examples/request.json
```

R86 的 `dev` 是一次性 smoke，不是 watch/hot-reload。代码变更后重跑命令；设置页中已启动的 worker 需要显式 restart 才会加载新代码。

### 3.5 登记到静态索引（约 5 分钟）

```bash
python -m backend.cli.plugin index build /tmp/hello-tool \
  --base-dir /tmp \
  --output /tmp/index.json
python -m backend.cli.plugin index validate /tmp/index.json --check-local
python -m backend.cli.plugin index search /tmp/index.json hello \
  --capability-type tool
```

到这里，第一个插件已经完成生成、运行与可搜索登记。若要放进 Sage 仓库的种子索引，使用 git source：

```bash
python -m backend.cli.plugin index build examples/plugins/hello-tool \
  --source-kind git \
  --source-url https://github.com/oneMuggle/sage.git \
  --source-ref main \
  --base-dir . \
  --output plugins/index.json
```

## 4. Tool 入口契约

`plugin.json` 中的 tool 必须有 `entry_point`。R83 宿主支持：

| 形式 | 示例 | 说明 |
| --- | --- | --- |
| `module:attr` | `handlers:run` | 推荐，最明确 |
| 点路径 | `handlers.run` | 兼容形式 |
| 模块约定 | `handlers` | 模块需定义 `run` / `execute` / `handler` / `main` 之一 |
| 类 | `tools:Greeter` | 无参构造后调用 `execute()`，或实例本身可调用 |

入口可以是同步或 async callable。参数映射规则：

- 单参数名为 `arguments` / `payload` 等载荷名时，收到完整参数字典；
- 多个具名参数时，宿主以 `**arguments` 调用；
- 无参入口以无参调用；
- 可选 `configure(config)` 会在模块或实例开始服务前收到生命周期配置。

返回值必须 JSON serializable。普通异常会变成结构化工具错误且 worker 继续运行；超时、崩溃和协议损坏会让 runtime 进入 failed 并注销代理。不要向 `sys.stdout` 写协议外文本；诊断请写 stderr/logging，设置页会展示有界的 stderr tail。

### 4.1 让聊天 Agent 调用

给 tool capability 声明调用参数的 JSON Schema：

```json
{
  "type": "tool",
  "name": "hello_tool",
  "entry_point": "handlers:run",
  "input_schema": {
    "type": "object",
    "properties": {
      "name": {"type": "string", "default": "World"}
    },
    "required": [],
    "additionalProperties": false
  }
}
```

这个示例在 hello-tool runtime 启动后会成为 `plugin__hello-tool__hello_tool`。已有聊天和随后新建的聊天都能看到它；stop、restart 失败、worker 崩溃、保存配置、禁用或卸载导致停机时，它会从聊天工具面注销。没有 object 形 `input_schema` 的 tool 仍可在设置页手动 invoke，但不会猜参数后交给 LLM。旧插件若按 R86 模板把参数 schema 写在 `config_schema`，桥接仍兼容读取；新插件请用 `input_schema`，`user_config` 只描述生命周期配置。

插件调用按第三方代码执行面处理：风险下限为 EXEC，默认 `workspace_write` 模式会逐次请求批准，`read_only` 会拒绝。用户可在权限规则中对可信的完整名或 `plugin__<plugin>__*` 显式 allow/deny/ask。带工具白名单的 agent profile 可列出完整工具名，也可用 `plugin__<plugin>__*` 放行某个插件的全部工具或 `plugin__*` 放行全部插件工具（仅这两种插件通配会被展开，其它 `*` 写法不通配）；在「智能体」页编辑目标 Agent 的工具白名单即可添加。通配会让该插件将来新增的能力自动对该 Agent 可见，调用仍逐次审批；最小权限场景请列完整工具名。

插件已启动且 tool 已发布后，「智能体」页的工具白名单下方会列出「运行中插件工具」。勾选会把完整名写入白名单草稿，仍需点保存；点「刷新」可重新读取当前已发布快照。若工具未单独列名、但被 `plugin__*` 或 `plugin__<plugin>__*` 覆盖，复选框会显示已选中且禁用，取消时需要编辑对应通配条目。未运行的工具不会出现在动态列表中，但已保存在白名单里的完整名不会因此被自动删除；读取该列表不会启动任何插件。

工具真正调用时，审批弹窗勾选「记住我的选择」后还可选择记住范围：默认「仅此工具」只保存当前完整名；「整个插件」会保存 `plugin__<plugin>__*` 的允许或拒绝规则，并覆盖该插件未来新增的工具。只有 Sage 能从当前已发布工具确认插件名时才会显示整插件选项；最小权限场景请保持「仅此工具」。这里的权限规则决定以后是否还要逐次审批，不会替你把工具加入某个 Agent 的白名单。后续执行时，整插件权限规则会按当时已发布工具的插件身份核对，不只看名字开头；若插件名与 capability 名拼出了相同前缀，另一个插件不会继承这条整插件允许或拒绝。若当前无法确认发布身份，整插件规则不会生效，Sage 会继续按其它权限规则或默认审批处理。已保存的规则可在「设置 → 通用 → 工具权限 → 已记住的规则」查看并逐条删除；删除后对应工具恢复逐次审批，需要时重新记住即可（设置页不提供直接新增或编辑规则，避免手写通配误放行）。

## 5. Manifest 最小契约

脚手架生成的 `plugin.json` 是完整样例。关键字段：

| 字段 | 说明 |
| --- | --- |
| `schema_version` | 当前为 `"1.0"` |
| `name` / `version` | 小写插件 ID 与 `X.Y.Z` 版本；同一索引内二者组合唯一 |
| `type` | `builtin` / `cdn` / `personal`；第三方本地插件用 `personal` |
| `metadata.display_name` | UI 与索引展示名 |
| `capabilities[].type` | `tool` / `skill` / `hook` / `mcp_server` / `command` |
| `capabilities[].entry_point` | tool 必填；其他模板也应明确声明 |
| `capabilities[].permissions` | `scope:action` 列表，只声明真实需要的权限 |
| `capabilities[].input_schema` | tool 调用参数的 object JSON Schema；提供后才向聊天 Agent 暴露 |
| `min_sage_version` / `python_version` | 兼容下限；索引 compatibility 会据此派生 |
| `user_config` | 生命周期配置的 JSON Schema |

不要按旧博客或旧版 `97-plugin-manifest.md` 的字典形 `capabilities` 写；当前 schema 中 `capabilities` 是数组，权威定义在 `backend/plugins/manifest.py`。

## 6. 模板矩阵

| 模板 | 生成物 | 当前成熟度 | 怎么验证 |
| --- | --- | --- | --- |
| `tool` | `handlers:run` | supported | `validate` + `dev` 进程外 invoke |
| `hook` | `handlers:on_event` | preview | 静态校验与自带测试；R83 不托管 hook |
| `mcp` | 无依赖 stdio `server.py` | preview | JSON-RPC handler 测试；在 MCP 客户端手动登记命令 |
| `skill` | `skills/<name>/SKILL.md` | preview | frontmatter 静态检查；把 skill 目录放进 Sage 技能根 |

preview 的确切含义是“manifest 与文件契约可生成、可校验、可进入索引”，不是“启用记录后会自动运行”。校验器会给出 `RUNTIME_PREVIEW_ONLY` warning；`--strict` 会把它升级为失败，所以 preview 包通常不要用 strict 作为发布门，除非你就是要阻止未托管能力进入某个索引。

## 7. 在设置页手动运行

1. 打开设置中的插件页；
2. 在“安装插件记录”中填插件目录的本地绝对路径，并粘贴 `plugin.json` 全文；
3. 若 manifest 声明权限，逐项审阅后勾选确认，再点“确认权限并安装”；
4. 对新记录点“启用”。此时仍没有代码执行；
5. 点“启动运行”，确认 runtime 状态变为 active；
6. 选择 tool capability，填写 JSON 参数并点“调用工具”；若该 tool 声明了 `input_schema`，也可回到聊天让 Agent 调用并逐次批准。若要限定给某个 Agent，请打开其编辑表单，在「运行中插件工具」中勾选完整工具名后保存；
7. 修改配置后点“保存配置”——正在运行的 worker 会先停止；改代码后点“重启运行”。

禁用、卸载、保存配置都会联动停止 worker，并同步从聊天工具面注销插件工具。后端重启后 runtime 不自动恢复，必须再次显式启动。

## 8. 静态索引格式

仓库种子位于 `plugins/index.json`。它只是格式与示例目录，不是已审核市场，也不代表签名信任。

每条 entry 嵌入完整已校验 manifest，并带：

- `source.kind = git`：HTTPS 仓库 URL、`ref` 与仓库内 `subdir`；
- `source.kind = archive`：HTTPS 下载 URL 与必填的 64 位小写 SHA-256；
- `source.kind = local`：相对 index 文件的本地路径，适合离线目录；
- `compatibility`：Sage/Python 要求、平台与 `win7 = supported|unsupported|unknown`；
- 可选 `signature`：algorithm 与 value/HTTPS URL。R86 只验结构，**不下载、不验签、不建立信任**。

向索引提交条目前至少做到：

1. 版本号已递增，entry 与嵌入 manifest 的 name/version 一致；
2. `python -m backend.cli.plugin validate <plugin>` 无 error；
3. `python -m backend.cli.plugin index validate <index> --check-local` 在对应 checkout 根通过；
4. 权限、兼容范围和下载来源与实际插件一致；没有 Win7 实测时 `win7` 保持 `unknown`；
5. README 写清安装路径、运行方式、权限用途与已知限制。

索引搜索完全离线，不会下载或安装搜索结果。

## 9. 权限与安全清单

- 默认权限为空；需要时逐项加 `file:read`、`network:write` 等最小声明；
- `input_schema` 只声明 handler 真正接收的参数，能用 `additionalProperties: false` 时不要放开任意字段；
- 权限声明不会把插件工具降成纯读：桥接按代码执行面处理，网络权限还会升为外部风险；
- 未知 scope 会 warning 并在安装确认中原文展示，不要发明看似更弱的别名；
- 不把 API key、用户文件正文或配置值写进日志、索引或测试快照；
- 入口参数来自调用方，先验类型和边界再使用；
- 文件路径必须限制在插件明确允许的根内，不能因为子进程隔离就假设安全；
- 网络、子进程和大文件处理要设超时与大小上限；
- 生成的 CI 只跑插件自带测试；在 Sage checkout 中再跑 `validate`/`dev`，它不会自动下载 Sage。

## 10. 故障排查

| 现象 | 先查什么 |
| --- | --- |
| `ENTRY_POINT_MODULE_NOT_FOUND` | entry 的模块是否位于插件根，拼写是否为 `module:attr` |
| `ENTRY_POINT_ATTR_NOT_STATICALLY_FOUND` | 属性是否动态生成；静态警告不等于运行时必然失败，用 `dev` 实测 |
| `PLUGIN_NOT_ENABLED` | 设置页是否先启用记录；`dev` 临时记录不会有此问题 |
| `NO_SUPPORTED_CAPABILITIES` | 是否只有 skill/hook/mcp，或 tool 缺 entry_point |
| `INVALID_PERMISSION` | 权限必须是全小写 `scope:action` |
| tool 返回不可序列化 | 返回 dict/list/str/number/bool/null 组合，不要返回 Path、set 或自定义对象 |
| 改代码后仍是旧结果 | 重跑 `dev`，或在设置页 restart runtime |
| 聊天里看不到插件工具 | runtime 是否 active、tool 是否有 object 形 `input_schema`、当前 profile 白名单是否列出完整 `plugin__...` 名 |
| `INDEX_LOCAL_MANIFEST_DRIFT` | plugin.json 改过但索引未重建；重新 `index build` |

## 11. 下一步贡献

- 只写内容：走 skill/prompt/harness 的 L1 路径；
- 写可运行扩展：走本指南的 L2 插件路径；
- 想增加新的 capability 类型、UI 插件槽位或宿主语义：这是 L3 内核变更，先在 `docs/plans/` 写 spec 并评审。

三层入口、分支与 PR 规则见根目录 `CONTRIBUTING.md` 的“按层贡献”一节。
