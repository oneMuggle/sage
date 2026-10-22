# R86 插件生态：脚手架、静态索引与贡献指南

> 日期：2026-10-21
> 轮次：plugin-evo R86
> 状态：已实现，待 PR CI
> 验收门：外部开发者在已准备好 Sage 开发环境的前提下，30 分钟内生成、校验并通过进程外宿主跑通第一个 Python tool 插件。

## 1. 背景与盘点结论

R78–R85 已补齐插件内核、tool bundle 装配、harness 配置、插件生命周期 REST/UI、进程外宿主、harness 文件化与提案引擎，但开发者面仍有四个断点：

1. `backend/plugins/` 只有 manifest、lifecycle、registry 与 R83 host，没有脚手架、包校验器或索引模型；
2. 仓库没有可运行的插件示例、`plugins/index.json` 或 `create-sage-plugin` 包；
3. `docs/technical/97-plugin-manifest.md` 仍混有旧版 manifest/API 示例，与当前 Pydantic schema、R82 记录面和 R83 仅托管 tool 的边界不一致；
4. `CONTRIBUTING.md` 没有按 L1 内容、L2 插件、L3 内核分层的入口，贡献者必须先通读核心源码才能知道该改哪里、能跑什么。

当前真实契约是：

- `PluginManifest` 接受 `tool`、`skill`、`hook`、`mcp_server`、`command` 五类 capability；
- R82 只保存生命周期记录，安装/启用不会读目录、导入或执行代码；
- R83 只显式托管带 `entry_point` 的 Python `tool` capability，支持 `module:attr`、点路径、模块约定入口、普通函数、类 `execute()` 与可选 `configure(config)`；
- 插件子进程是崩溃隔离边界，不是 OS 安全沙箱；manifest 权限仍是安装确认与审计语义，不宣称文件/网络内核级强制；
- 主仓库没有 UI capability 类型或前端插件加载器，因此本轮不能把 TS widget/panel 模板冒充成可运行插件。

## 2. 目标

R86 交付一条不依赖服务端市场的本地优先闭环：

```text
plugin init -> plugin validate -> plugin dev (R83 one-shot smoke)
            -> index build -> index validate/search -> 按贡献指南提交
```

具体目标：

1. 新增 `sage plugin` 语义对应的 `python -m backend.cli.plugin`，提供脚手架、包校验、模板列表、一次性 dev smoke 与静态索引命令；
2. 提供 `tool`、`hook`、`mcp`、`skill` 四个模板，其中只有 `tool` 标记为当前运行时支持，其余明确标记为 contract preview；
3. 新增仓库内可运行示例 `examples/plugins/hello-tool/` 与静态目录种子 `plugins/index.json`；
4. 索引可静态托管、离线校验与搜索，不做下载执行、自动安装、签名验证或服务端市场；
5. 用一份 30 分钟快速开始文档和 CONTRIBUTING 分层入口，把 L1/L2/L3 贡献路径、权限、安全边界、CI 门与索引登记讲清；
6. 在现有 backend CI 中显式校验示例与索引，后端测试同时覆盖脚手架、校验器、索引和 CLI。

## 3. 非目标与诚实边界

- 不新增服务端市场、远程下载、自动安装、依赖解析、升级/回滚分发机制；
- 不新增签名信任根。索引允许登记签名元数据和 archive SHA-256，但本轮只验结构与哈希格式，不下载、不验签、不把静态索引称为可信源；
- 不扩展 R83 宿主去执行 `skill`、`hook`、`mcp_server`、`command`；三类 preview 模板只保证 manifest/文件契约可校验，文档会明确当前运行方式或未托管状态；
- 不新增 UI capability、前端插件加载器或 `npm create sage-plugin`。触发条件是先有 UI manifest 契约、沙箱/消息边界与至少一个宿主渲染槽位；在此之前生成 TS 模板只会产生不可运行的假生态；
- 不实现 watch/hot-reload。`dev` 是显式的一次性安装→启用→子进程启动→invoke→停止冒烟；代码改动后重跑命令或在设置页 restart runtime；
- 不改变默认启动、安装、启用或 LLM ToolRegistry 暴露行为；R86 新代码只在 CLI/测试/文档中被显式调用。

## 4. 模块设计

### 4.1 `backend/plugins/scaffold.py`

职责：模板目录、文件渲染、安全落盘、插件包静态校验与 dev smoke。

公共面：

- `TEMPLATE_NAMES`、`list_templates()`：返回模板名、capability 类型、成熟度（`supported`/`preview`）和说明；
- `ScaffoldOptions`、`ScaffoldResult`、`scaffold_plugin()`：生成插件目录；
- `PluginValidationIssue`、`PluginPackageValidation`、`validate_plugin_package()`：只读静态校验，不导入插件代码；
- `PluginDevResult`、`run_plugin_dev()`：用临时 SQLite 生命周期库和独立 `CapabilityRegistry` 复用 R82/R83，执行一次 tool 调用后必停 worker；
- `PluginEcosystemError`：面向 CLI 的稳定错误类型，带 `code` 与 `status_code`。

脚手架安全规则：

1. 先用 `PluginManifest` 校验并规范化名称，再渲染全部文件；
2. 所有相对路径必须是 POSIX 相对路径，禁止绝对路径与 `..`；
3. 目标不存在时在同级 staging 目录完整渲染后改名；目标已存在且任一生成文件重叠时默认拒绝，`--force` 只覆盖生成文件、永不删除额外文件；
4. 生成代码只依赖 Python 标准库，兼容 Python 3.8，不 import `backend.*`，因此插件仓库可独立跑自带测试；
5. 生成物固定包含 `plugin.json`、`README.md`、`tests/test_plugin.py`、`.github/workflows/plugin-ci.yml`、`.gitignore`，tool 模板额外含 `examples/request.json`。

模板矩阵：

| 模板 | capability | 入口 | 成熟度 | 当前验证方式 |
| --- | --- | --- | --- | --- |
| `tool` | `tool` | `handlers:run` | supported | `plugin dev` 经 R83 子进程 invoke |
| `hook` | `hook` | `handlers:on_event` | preview | 静态校验 + 自带单测；R83 不托管 |
| `mcp` | `mcp_server` | `server.py` | preview | 静态校验 + JSON-RPC handler 单测；需手动登记 MCP 命令 |
| `skill` | `skill` | `skills/<name>/SKILL.md` | preview | 静态校验 + frontmatter 检查；需放入技能根 |

包校验规则：

- `plugin.json` 必须存在、可解析并通过 `PluginManifest`；
- 未知顶层字段、缺失 README、目录名与插件名不一致是 warning；`--strict` 时 warning 升级为失败；
- 至少声明一个 capability；tool 必须有合法入口；
- Python 入口只做文件存在与 AST 静态解析，不导入、不执行；动态属性找不到时 warning；
- skill 入口必须留在插件根内且文件存在，并有基本 frontmatter；
- 权限统一为 `scope:action` 形式，未知 scope 与重复声明 warning；
- 非 tool capability 给出 `RUNTIME_PREVIEW_ONLY` warning，防止把 manifest 可登记误读为宿主可执行；
- Python 文件做 `ast.parse` 语法检查，跳过缓存/虚拟环境目录。

### 4.2 `backend/plugins/index_catalog.py`

职责：静态索引模型、构建、校验与搜索。

索引文件形态：

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-10-21T00:00:00Z",
  "plugins": [
    {
      "name": "hello-tool",
      "version": "0.1.0",
      "manifest": { "...": "完整的已校验 PluginManifest" },
      "source": {
        "kind": "git",
        "url": "https://github.com/oneMuggle/sage.git",
        "ref": "main",
        "subdir": "examples/plugins/hello-tool"
      },
      "compatibility": {
        "sage": ">=0.4.0",
        "python": ">=3.8",
        "platforms": ["any"],
        "win7": "unknown"
      },
      "signature": null,
      "published_at": null
    }
  ]
}
```

约束：

- `source.kind` 仅 `git`、`archive`、`local`；git/archive URL 必须 HTTPS，archive 必须带小写 64 位 SHA-256，local 只接受相对路径；
- entry 的 `name/version` 必须与嵌入 manifest 一致，同一索引内 `(name, version)` 唯一；
- compatibility 默认由 manifest 的 `min_sage_version` 与 `python_version` 派生；`win7` 只能是 `supported`、`unsupported`、`unknown`，没有实测时固定 `unknown`；
- signature 若登记，必须有 algorithm 与 value 或 HTTPS URL；仅做结构校验；
- build 接受单个插件根或一层插件根集合，逐个复用包校验器；有 error 时拒绝产出入口，warning 会保留在 CLI 输出；
- 本地检查模式可验证 git `subdir`/local `path` 指向的 manifest 与索引一致；
- search 只做名称、显示名、描述、作者、分类、标签和 capability 的离线文本/类型/权限过滤，不访问网络。

### 4.3 `backend/cli/plugin.py`

命令面：

```text
python -m backend.cli.plugin templates [--json]
python -m backend.cli.plugin init NAME [--template tool] [--output DIR]
    [--display-name TEXT] [--author TEXT] [--description TEXT]
    [--version X.Y.Z] [--force] [--json]
python -m backend.cli.plugin validate PATH [--strict] [--json]
python -m backend.cli.plugin dev PATH [--capability NAME]
    [--arguments JSON | --arguments-file FILE]
    [--config JSON | --config-file FILE] [--json]
python -m backend.cli.plugin index build ROOT... [--output FILE]
    [--source-kind local|git] [--source-url URL] [--source-ref REF]
    [--base-dir DIR] [--json]
python -m backend.cli.plugin index validate FILE [--check-local]
    [--base-dir DIR] [--json]
python -m backend.cli.plugin index search FILE [QUERY]
    [--capability-type TYPE] [--permission PERM] [--json]
```

退出码沿用 Sage CLI 家族：成功 0、业务/校验失败 1、参数或输入文件错误 2。`--json` 输出稳定字段，供 CI 与脚本消费；文本模式给下一步命令。

## 5. 示例、索引种子与文档

1. `examples/plugins/hello-tool/` 由 tool 模板同构生成，`configure(config)` 保存问候语，`run(arguments)` 返回 JSON serializable 结果；仓库测试直接对其做严格校验和 R83 smoke；
2. `plugins/index.json` 只登记该示例，git source 指向主仓库 `main` 的示例子目录。它是格式种子，不是已审核市场清单，指南会明确这一点；
3. 新增 `docs/user-manual/21-plugin-development.md`：前置条件、30 分钟路径、manifest 字段、模板矩阵、入口契约、权限与安全边界、设置页安装/启停/runtime 操作、索引登记、故障排查；
4. `CONTRIBUTING.md` 增加三级贡献面：
   - L1 内容：skill/prompt/harness 预设，给出校验命令；
   - L2 插件：init→validate→dev→index 的最短路径；
   - L3 内核：新 provider/capability/宿主语义必须 spec 先行并走评审；
5. `docs/technical/97-plugin-manifest.md` 顶部补当前契约与到开发指南的指针，避免旧示例继续被当成现行 API。

## 6. CI 与测试

新增测试：

- `test_plugin_scaffold.py`：四模板清单、tool 生成/严格校验/dev invoke、拒覆盖、preview warning、坏入口/权限/skill 路径、生成 Python 可编译；
- `test_plugin_index.py`：build、重复条目、manifest 不一致、archive hash、签名结构、checked-in index 与本地检查、search 过滤；
- `test_plugin_cli.py`：templates/init/validate/index/dev 的退出码与 JSON 形态。

现有 backend CI 自动收集上述测试；另在 backend job 增加显式步骤：

```bash
python -m backend.cli.plugin validate examples/plugins/hello-tool --strict
python -m backend.cli.plugin index validate plugins/index.json --check-local
```

本地验收还包括插件相关回归、Ruff、py38 hazard scan（若环境可用）、architecture-check、diagnostics。import-linter 在远端环境缺失时不宣称本地通过，以 PR CI 为准。

## 7. 30 分钟验收脚本

在 Sage 仓库根、后端依赖已安装的环境中：

```bash
python -m backend.cli.plugin init hello-tool --template tool --output /tmp/hello-tool
python -m backend.cli.plugin validate /tmp/hello-tool --strict
python -m backend.cli.plugin dev /tmp/hello-tool \
  --arguments-file /tmp/hello-tool/examples/request.json
python -m backend.cli.plugin index build /tmp/hello-tool --output /tmp/index.json
python -m backend.cli.plugin index validate /tmp/index.json
python -m backend.cli.plugin index search /tmp/index.json hello
```

成功标准：五条命令均退出 0，`dev` 在独立子进程返回问候结果，索引可被重新加载与搜索。随后贡献者可按指南在设置页用同一 manifest 与本地路径登记记录；启用记录不会自动执行代码，runtime 仍需显式 start。

## 8. 回滚

R86 以新增模块、CLI、示例、索引和文档为主；回滚时删除这些文件并撤销 CI 显式步骤、CONTRIBUTING/技术文档指针与总账条目即可。没有数据库 schema、默认配置、启动路径或既有 API 语义变更，R78–R85 行为不受影响。
