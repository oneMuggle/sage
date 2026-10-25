# LocalBridge files.cjs 与 Sage P0 实现逐项对照

> 日期：2026-09-26
> 参考：`reference/LocalBridge-Share/LocalBridge/src/files.cjs`（4354 字节，已完整读取）
> 对照：分支 `feat/localbridge-p0-safety` 提交 `0f2bc5b97`（`backend/tools/file_guard.py` 等）

## 1. files.cjs 实际做了什么

| 函数 | 行为 |
|---|---|
| `parts()` 路径校验 | 只接受相对路径。拒绝绝对路径、以 `/` 或 `\` 开头的路径、长度超过 1000 的路径、控制字符以及 `:`（这会同时挡住 NTFS 备用数据流 `a.txt:stream`）。拒绝空段和 `..` 段、以 `.` 或空格结尾的段、Windows 保留名（`con`、`prn`、`aux`、`nul`、`com0-9`、`lpt0-9`） |
| `parts()` 受保护路径 | 路径中**任意一段**命中以下规则即拒绝：`.git`、`.ssh`、`.aws`、`.azure`、`.local-state`、`node_modules`；`.env` 以及所有 `.env.*`（**含 `.env.example`**）；`credentials`、`id_rsa`、`id_ed25519` |
| `resolve()` | 对 root 做 realpath；对请求路径的**每一段**做 `lstat`，只要有一段是 symlink 或 junction 就拒绝，即使指向工作区内部也拒绝；最后再用 realpath 确认结果在工作区内 |
| `list()` | 自动隐藏命中受保护规则或非法名称的条目，以及 symlink；最多返回 500 条 |
| `read()` | 只读普通文件，上限 512 KiB；含 NUL 字节的拒绝；用严格 UTF-8 解码，非法字节直接报错；返回 `version`，即原始字节的 sha256（**不带 `sha256:` 前缀**） |
| `write()` | 上限 512 KiB。**版本号必填**：文件不存在时必须传 `'new'`，已存在时必须传 sha。在进程内给每个文件加锁，并发写同一文件返回 `FILE_BUSY`。先写入临时文件 `.lb-<uuid>.tmp`（`wx`），**替换前再读一次比对版本**，然后用原子 `rename` 覆盖；失败时清理临时文件。返回新版本 |
| 注释中声明的边界 | "This guards cooperating clients, not hostile OS processes." |

## 2. 与 Sage 当前实现的差异

### 2.1 版本号 / 乐观锁

| 项 | LocalBridge | Sage（0f2bc5b97） | 判断 |
|---|---|---|---|
| 版本格式 | 64 位十六进制 | `sha256:` 加 64 位十六进制 | Sage 自定格式，二者不互通，但各自内部一致 |
| 是否必填 | **必填** | 可选，不传就不校验 | **偏离**：出于兼容性考虑 |
| `'new'` 语义 | 一致 | 一致 | 相同 |
| 写入方式 | 临时文件加原子 rename | 原地覆盖（`open('w')` 或 `write_bytes`） | **缺失**：中途失败可能留下半截文件 |
| 替换前复核 | 有，第二次比对 | 无，只在写前校验一次 | **缺失**：TOCTOU 窗口更大 |
| 进程内文件锁 | 有（`FILE_BUSY`） | 无 | **缺失**：Sage 的子代理并发时更需要它 |
| 覆盖的工具 | 只有 `write` | `write_file`、`edit_file`、`apply_patch` | Sage 覆盖面更广 |

### 2.2 凭据路径 / 受保护路径

| 规则 | LocalBridge | Sage | 判断 |
|---|---|---|---|
| `.env`、`.env.*` | 全部拒绝，含 `.env.example` | 拒绝，但**放行模板文件**（example、sample、template 等） | **偏离**：Sage 更宽松 |
| `.ssh` | 任意一段命中就拒绝，包括 `*.pub` | 拒绝 `.ssh/` 下的私密文件，放行 `*.pub`、`known_hosts`、`config`、`authorized_keys` | **偏离**：Sage 更宽松 |
| `.aws` | 整个目录拒绝 | 只拒绝 `.aws/credentials` | **偏离**：Sage 更窄（例如 `.aws/config` 放行） |
| `.azure` | 拒绝 | 未覆盖 | **缺失** |
| `.git` | 拒绝（防止改写 hooks 或 config） | 未覆盖 | **缺失**：写 `.git/hooks/*` 等于执行任意代码 |
| `node_modules` | 拒绝 | 未覆盖 | 需要取舍：Sage 读依赖源码是合理需求 |
| `.local-state` | 拒绝 | 未覆盖 | LocalBridge 特有，可以忽略 |
| `credentials`（任意位置） | 拒绝 | 只拒绝 `.aws/credentials` | **偏离**：Sage 更窄 |
| `id_rsa`、`id_ed25519` | 拒绝 | 拒绝（还包括 dsa、ecdsa、`_sk` 变体） | Sage 更广 |
| `.pem`、`.key`、`.pfx`、`.p12`、`.kdbx`、`.git-credentials`、`.netrc`、`.docker/config.json`、`.kube/config` 等 | **无** | 拒绝 | **Sage 自行扩充**，不来自参考项目 |
| 逃生开关 | 无 | `SAGE_ALLOW_SENSITIVE_PATHS=1` | Sage 自行添加 |
| `list` 隐藏受保护条目 | 有 | `list_dir` 不隐藏 | **缺失** |

### 2.3 路径合法性

| 规则 | LocalBridge | Sage | 判断 |
|---|---|---|---|
| 只允许相对路径 | 是 | 否：允许绝对路径；读取默认不限制在工作区内（沿用 claw-code 的"读写非对称"） | 设计理念不同，Sage 有意为之 |
| 拒绝 `:`（NTFS 备用数据流） | 是 | 否 | **缺失**：`a.txt:hidden` 可以写入隐藏流 |
| 拒绝 Windows 保留名（`con`、`nul` 等） | 是 | 否 | **缺失**：写入 `nul` 会静默丢失，`con` 可能挂起 |
| 拒绝以 `.` 或空格结尾的段 | 是 | 否 | **缺失**：Windows 会自动去掉结尾的点和空格，可以用来绕过黑名单（例如 `.env.`） |
| 逐段检查 symlink / junction | 任何一段是链接都拒绝 | 只用 realpath 判断最终是否落在工作区内，工作区内部的链接放行 | 部分缺失 |

### 2.4 大小与编码

| 项 | LocalBridge | Sage |
|---|---|---|
| 读取上限 | 512 KiB | 5 MiB（大文件分页） |
| 写入上限 | 512 KiB | 10 MiB |
| 解码 | 严格 UTF-8，遇到非法字节报错 | 识别 BOM 后用 `errors="replace"` 解码 |

Sage 服务于本地写作，需要处理大文件，保持现状即可，不对齐。

## 3. 需要特别指出的问题

**`.env.` 结尾点绕过**：Sage 的 `sensitive_path_reason(".env.")` 得到的文件名是 `.env.`。它以 `.env.` 开头，后缀为空，不在模板白名单里，所以会被拒绝。但 `".env "`（结尾带空格）和 `"id_rsa."` 都不会命中，而 Windows 会把它们解析为 `.env` 和 `id_rsa`。已实测：`.env `、`id_rsa.`、`id_rsa `、`x.pem.`、`a/.ssh./x` 都返回 `None`（放行），`.git/hooks/pre-commit`、`a.txt:s` 也都放行。**这是一个真实的绕过漏洞**，应当修复：判定前先去掉每段结尾的点和空格，或者像 LocalBridge 一样直接拒绝这类路径段。

## 4. 建议的对齐方案（待确认）

| 编号 | 项 | 建议 |
|---|---|---|
| A1 | 结尾点、空格规范化或拒绝，保留名，`:` 备用数据流 | **必须修**，属于安全缺陷 |
| A2 | 写入改为"临时文件 → 复核版本 → 原子 rename"，并加进程内文件锁 | **建议做**，与 LocalBridge 一致，对子代理并发有直接价值 |
| A3 | 受保护路径补上 `.git/`（至少禁止写入）、`.azure/`、整个 `.aws/`、任意位置的 `credentials` | **建议做** |
| A4 | `list_dir` 隐藏受保护条目 | 可选 |
| A5 | `.env.example` 等模板文件 | 取舍：保持 Sage 放行，或者对齐 LocalBridge 全部拒绝 |
| A6 | `.ssh/*.pub` | 取舍：保持放行，或者对齐拒绝 |
| A7 | `node_modules` | 不建议拒绝读取；可以考虑拒绝写入 |
| A8 | 版本号改为必填 | 不建议，维持可选；可以在 system prompt 里引导模型传入 |
| A9 | 只允许相对路径，限制读取范围 | 不对齐，这属于 Sage 的既有设计（由 `allowed_paths` 控制） |

## 5. uia.cjs 补充（已完整读取）

`reference/LocalBridge-Share/LocalBridge/src/uia.cjs` 中的设计要点，供后续做桌面控制时参考：

- 每次操作都启动一个 `powershell.exe -File native/uia.ps1` 子进程，参数以 JSON 通过 stdin 传入。超时 200 秒，响应上限 4 MiB。超时的报错信息要求"不要重放，先检查状态"。
- 控件引用 `uia-<uuid>` 只在**当前会话**和**当前窗口租约**内有效，120 秒过期，最多保留 4000 个。执行 `invoke`、`toggle`、`set_value`、`click_element` 这类会改变界面的操作后，**全部引用清空**，必须重新查询控件树。
- 引用只保存 `runtimeId`、`name`、`autoId`、`controlType`，其中 `runtimeId` 不返回给模型。
- 工具共 7 个：`uia_list_windows`、`uia_dump_tree`（maxDepth ≤ 12，maxNodes ≤ 1500）、`uia_find_elements`（按名称、AutomationId、ControlType 做 AND 精确匹配，至少提供一个条件）、`uia_invoke`（不会自动退回 toggle）、`uia_toggle`、`uia_set_value`（拒绝只读和密码框，最多 4000 字符）、`uia_click_element`。
- 不返回密码框的值；排除 LocalBridge 自身的控制台和安全桌面。
- 注意：上一版分析报告的工具列表来自 `使用说明.txt`，漏掉了 `uia_toggle`。
