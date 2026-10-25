# R81：三层配置 + 四预设 + `--dump-config`

> 账本：`docs/plans/plugin-evo-index.md` R81。设计依据：总纲 §4 **D4**（三层叠加）/
> **D5**（四预设）与 §7 路线图 R81（`harness.yaml` 解析、四预设、CLI；
> 验收 = 同一安装包跑出四形态、解析后配置可导出；回滚 = 删除 `harness.yaml` 即回默认）。

## 1. 现状盘点（带证据）

| 事项 | 现状 | 证据 |
| --- | --- | --- |
| YAML 解析 | PyYAML 6.0.1 已在全部 requirements（含 py38） | `requirements*.txt`；`main.py`、`application/services/tool_config.py` 等 8+ 处 `import yaml` |
| CLI 入口 | 无 `sage` console entry；既有形态是 `python -m backend.cli.doctor` | `backend/cli/doctor.py`（550 行，argparse + `main(argv) -> int`） |
| `.sage/` 路径约定 | `~/.sage/`（personas/skills）与 `<cwd>/.sage/`（agents、hooks.json）已在用 | `adapters/out/skill/persona_loader.py`、`agents/agents_files.py` |
| `register_all_tools` | 无 workspace 入参；调用方 4 个生产点 + 多个测试 | `tools/__init__.py` 签名；调用方见 `inproc_adapter.py`、`runtime_routes.py`、`core/legacy/agent.py` |
| preset/profile 契约 | R78 未预定义（`domain/plugin.py` 无相关类型） | grep 命中仅 `ProviderKind` / `TrustLevel` / `FiberState` |
| 坏配置惯例 | **fail-open**：非法 → warning + 忽略，永不阻断启动 | `hooks/config.py` 校验策略 |

结论：三层配置的全部原料已齐；R81 = 把「bundle 选择」从写死改为数据驱动，
并兑现 R80 的承诺删除 `_register_all_tools_legacy`。

## 2. 设计

### 2.1 机制与声明的分工（延续 R79/R80）

- **机制** → `backend/application/kernel/harness_config.py`：解析 / 分层合并 /
  预设目录 / bundle 选择 / 解析后视图。只认识 **bundle 名字符串**，不 import tools。
- **声明与接线** 在 tools 侧：`tool_bundles.install_default_bundles(..., harness=None)`
  按解析结果过滤 `BUNDLES` 后再走 R80 的 `install_bundles`。
- **CLI** → `backend/cli/harness.py`：组合层，允许同时 import kernel 与 tools
  （与 `doctor.py` 的定位一致）。

### 2.2 `harness.yaml` v1 模式（刻意最小）

```yaml
preset: focus            # standard | focus | headless | dev
bundles:
  office_core: true      # 在预设基线之上按名开关
  browser: false
flags:
  context: compact       # 先记录、先可导出，语义接入随 R82+
```

- 未知 preset / 未知 bundle 名 / 未知顶层键 → **warning 并忽略**（fail-open）；
  `strict=True`（CLI `check`）时才抛 `HarnessConfigError`。
- 「插入自定义 bundle 行」需要代码引用，属于插件装载（R82/R83），本轮明确不做。

### 2.3 分层合并（低 → 高）

`builtin` < `~/.sage/harness.yaml` < `<workspace>/.sage/harness.yaml`
< 环境变量 `SAGE_HARNESS_PRESET` < `--patch`（dict）

- `preset`：最后一个非空值赢。
- `bundles`：按名合并，高层覆盖低层同名项。
- `flags`：以所选预设的 flags 为底，按键被各层 `flags:` 覆盖。
- 解析结果带 **provenance**（`sources`：实际命中的文件路径 / `env` / `patch`）
  与 `warnings`，`--dump-config` 可直接导出排障。
- 路径解析：`user_home` 默认 `Path.home()`，可用 `SAGE_HARNESS_HOME` 覆盖（测试隔离）；
  `workspace` 由调用方传入，接线层缺省取 `SAGE_WORKSPACE` 或 cwd。
- 文件读取带 mtime 缓存：同一进程多次 `register_all_tools` 不重复解析未变的 YAML。

### 2.4 四预设（bundle 排除表）

| 预设 | 排除 bundle | ONLINE 工具数 | flags |
| --- | --- | --- | --- |
| standard | — | 94 | — |
| focus | `office_core/pdf/template/analysis/journal/quality`、`browser`、`multimodal`、`design`（9 个） | 53 | `context: compact` |
| headless | `ask_user`（唯一会阻塞等人的工具面） | 93 | `interactive: false` |
| dev | — | 94 | `dev: true` |

预设只表达「排除集」，安装顺序仍为 `BUNDLES` 声明顺序减去被排除者（顺序保真不破）。
flags 本轮只做**声明与导出**，审批模式 / 热重载 / 上下文压缩的行为接入随 R82+，
账本交付边界里如实标注，不冒充已实现。

### 2.5 接线与删除 legacy

- `register_all_tools` 固定走 bundle 路径：加载 harness（任何错误 → standard，
  即与今天逐字节等价）→ `install_default_bundles(..., harness=cfg)`。
- 删除 `_register_all_tools_legacy` 与环境开关 `SAGE_KERNEL_TOOL_BUNDLES`
  （`tool_bundles_enabled` / `TOOL_BUNDLES_ENV` 同步删除；引用方仅 `__init__` 与 2 个测试文件）。
- **回退路径**：无任何 `harness.yaml` 时 ≡ 今天行为（94 个工具，顺序 / risks / schema 不变），
  由黄金快照测试钉死 —— 这既是兼容承诺，也是 D4「删除即回默认」的回滚方式。

### 2.6 CLI（`python -m backend.cli.harness`）

```
presets [--json]                                  # 列四预设与排除集
dump-config [--workspace P] [--user-home P]       # 导出解析后配置
            [--preset NAME] [--patch FILE.yaml]   # 含选中/跳过的 bundle 与来源
            [--json]
check [--workspace P] [--user-home P]             # strict 校验，非法退出码 1
      [--preset NAME] [--patch FILE.yaml] [--json]
```

## 3. 验收矩阵

| 主张 | 证据形式 |
| --- | --- |
| 无配置文件 ⇒ 行为零变更 | 黄金快照：ONLINE 94 名逐项顺序 + `declared_risks` 键序 + `get_schemas_for_llm` 的 78 个可见 schema 名序；两次独立装配的完整 schema 相等；INTRANET 93 / OFFLINE 89 与 R80 实测一致 |
| 四预设可从同一安装包跑出 | `select_bundles` 纯函数断言 + 真实安装断言（focus 无 `office_*`/`browser_*`、headless 无 `ask_user_question`） |
| 三层合并优先级正确 | tmp 目录双层文件 + env + patch 四档叠加用例，含同名覆盖与 provenance |
| 坏配置不阻断启动 | 非法 YAML / 未知 preset / 未知 bundle → warnings + 回默认；`strict` 下抛错 |
| 解析后配置可导出 | CLI 三子命令冒烟（`main(argv)` 直调，文本 + JSON） |
| legacy 已删且无残引用 | grep 零命中；CI `Backend legacy smoke` 12700+ 全量过 |

## 4. 风险与边界

| 风险 | 处置 |
| --- | --- |
| 默认装配路径切换（legacy → bundle）影响全部调用方 | R80 已在 3 档网络策略下证明双路径等价；本轮黄金快照继续钉顺序 / risks / schema；CI 全量首次实跑 bundle 路径 |
| 开发者机器上存在 `~/.sage/harness.yaml` 影响既有测试 | CI 机器无此文件；测试用 `SAGE_HARNESS_HOME` / 参数隔离；文件缺失即默认 —— 这是承诺而非巧合 |
| flags 被误读为「已生效」 | spec 与账本明示：R81 只声明 + 导出，行为接入在 R82+ |
| py38 语法 | 不用 `match` / PEP604 运行时并集 / `str.removeprefix`；`Backend collect (py38)` 把守 |

## 5. 交付清单（实测）

| 文件 | 行数 | 内容 |
| --- | ---: | --- |
| `backend/application/kernel/harness_config.py` | 546 | 三层解析/合并、四预设、选择、provenance、mtime 缓存 |
| `backend/cli/harness.py` | 215 | `presets` / `dump-config` / `check`，文本与 JSON 双输出 |
| `backend/tools/tool_bundles.py` | 485 | 新增 `bundle_names` / `select_bundle_objects` 与 `harness=` 接入 |
| `backend/tools/__init__.py` | 301 | 删除约 220 行 legacy 平铺实现，门面固定 bundle 路径并 fail-open 加载配置 |
| `backend/application/kernel/tool_install.py` | 113 | 删除已退役的 `SAGE_KERNEL_TOOL_BUNDLES` 开关 |

本地证据：

- 新增/改写测试 55 例通过：机制 11 + harness 19 + 黄金/预设 15 + CLI 10；
- 既有相关测试 32 例通过：无循环导入 4 + 注册门控 9 + 注册表 19；
- `ruff check backend` 全绿；`node scripts/architecture-check.mjs` 全绿；
- `_register_all_tools_legacy` / `tool_bundles_enabled` / `SAGE_KERNEL_TOOL_BUNDLES`
  在 `backend/**/*.py` 中 grep 零命中。
