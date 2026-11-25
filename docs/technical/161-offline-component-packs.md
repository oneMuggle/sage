# 161 内网离线组件包（.sagepkg）

> 面向 release/win7 内网维护：全量安装包保持不变，组件包作为独立签名资产，用于补装、修复与按需安装。

## 1. 背景与边界

win7 全量 NSIS 安装包仍然内置 Electron、Python 运行时、模型与桌宠素材，适合完全离线的一次性部署。但当出现以下场景时，重新分发 379MB 安装包并不划算：

- 只缺 embedding / OCR 模型；
- 模型需要单独升级；
- 终端已经装好，但某个可选能力缺失；
- 管理员需要按组件粒度做修复。

`.sagepkg` 提供一条独立通道：**签名组件包 + 本地导入**。它不替代全量安装包，也不要求终端联网。

## 2. 包格式

`.sagepkg` 是一个 zip：

```
component.json      # 清单（签名覆盖其原始字节）
signature.bin       # RSA-PKCS1v15-SHA256 签名
payload/...         # 已构建好的文件
```

`component.json`：

```json
{
  "schemaVersion": 1,
  "id": "embedding-bge-small-zh",
  "name": "Embedding model (bge-small-zh-v1.5)",
  "version": "1.0.0",
  "branch": "win7",
  "python": "3.8",
  "arch": "x64",
  "target": "user_data",
  "payloadDir": "payload",
  "files": [
    {"path": "models/bge-small-zh-v1.5/model.onnx", "size": 91000000, "sha256": "…"}
  ],
  "description": "本地语义嵌入模型（ONNX）",
  "createdAt": "2026-11-17T00:00:00Z"
}
```

- `target: user_data`：只允许写入 `models/` 前缀，安装到 `<userData>/models/...`，与现有模型查找链（userData > bundled）直接兼容。
- `target: component_dir`：安装到 `<userData>/components/<id>/<version>/`，给非模型类组件使用。
- `python` / `arch` / `branch`：导入时校验 Python 版本与架构；设置 `SAGE_COMPONENT_BRANCH` 时同时校验分支。

### 2.1 清单约束

清单在解析期即校验，不合法直接拒绝：

- `schemaVersion` 必须为 `1`；
- `id` 匹配 `^[a-z0-9][a-z0-9._-]{0,63}$`，`version` 匹配 `^[0-9A-Za-z][0-9A-Za-z._+-]{0,63}$`；
- `files` 非空且路径不得重复；`path` 必须是相对路径，拒绝绝对路径、盘符、`.`、`..`、空段与 NUL；
- `target: user_data` 时每个 `path` 还必须以 `models/` 开头；
- 每个文件 `size` 为非负整数，`sha256` 为 64 位小写十六进制；
- `component.json` 不超过 1 MiB，`signature.bin` 不超过 64 KiB。

`arch` 比较前归一化：`amd64` / `x86_64` / `x64` → `x64`，`aarch64` / `arm64` → `arm64`。

## 3. 校验与安全

导入流程固定为：

1. 读取 `component.json` 与 `signature.bin`；
2. 用内置/管理员配置的公钥做 RSA-SHA256 验签；
3. 校验清单路径：拒绝绝对路径、`..`、盘符、空段、NUL；
4. 逐文件流式解包，边写边算 SHA-256，校验声明大小/hash；
5. 拒绝未登记文件、重复条目、符号链接；
6. 原子复制到目标路径，写入 `<userData>/components/installed.json`；
7. 升级时删除旧版本中不再存在的文件；失败时回滚已覆盖的文件。

安全约束：

- 未配置公钥、签名无效、hash 不匹配一律拒绝；
- `user_data` 目标只允许 `models/`，不能覆盖 `sage.db`、设置、诊断日志；
- 生产终端不执行 `pip` / `npm` / `conda`；
- 导入操作有文件锁，避免并发写坏目标目录。

公钥解析顺序：

1. `SAGE_COMPONENT_PUBLIC_KEY_PATH`（管理员显式路径）；
2. `SAGE_COMPONENT_PUBLIC_KEY`（内联 PEM，管理员/测试）；
3. `%ProgramData%\Sage\component-public-key.pem`（机器级管理员覆盖）；
4. `<resources>/component-public-key.pem`（安装包内置，生产默认信任锚）。

`<userData>` 目录**不作为**信任锚：它是普通用户可写目录，接受其中的公钥会让任何本地用户绕过管理员签名。管理员如需自定义密钥，应使用 `ProgramData` 或安装目录下的公钥文件，或通过显式环境变量下发。

### 3.1 分支校验归一化

`component.json` 的 `branch` 是**发布通道 id**（固定值 `win7` / `main`），而打包版 `resources/build-manifest.json` 的 `branch` 是 git ref（tag 名 `v0.4.9-alpha.84-win7`、分支名 `release/win7`、dev 缺省 `unknown`）。两者不做裸字符串比较 —— `ComponentService._check_compatibility` 通过 `_normalise_branch()` 把两边都映射成通道 id 再比较：

| 输入 | 归一化结果 |
| --- | --- |
| `win7` / `release/win7` / `feat/x-win7` / `v0.4.9-alpha.84-win7` | `win7` |
| `v0.4.9-alpha.55-lts` / `lts` / `release/lts`（旧版 LTS 标签约定） | `win7` |
| `main` / `master` / `v0.4.9-alpha.84` | `main` |
| `""` / `unknown` / `dev-build` | 期望值侧跳过校验；清单 `branch` 为空时不校验该维度，`unknown` / `dev-build` 归一到自身后与通道 id 不符而被拒绝 |

错误消息里仍保留原始 ref 便于诊断；比较只用归一化后的通道 id。历史版本（2026-11-22 之前）是严格字符串比较，导致所有正式发行版导入必然报 `branch_mismatch`；2026-11-22 起已修复。

分支校验只在调用方设置了 `SAGE_COMPONENT_BRANCH` 时生效：桌面端由 `build-manifest.json` 的 `branch` 注入，SageDoctor/CLI 独立运行且未设置该变量时跳过此维度（Python 与架构校验仍然生效）。

### 3.2 解包限额与路径防护

- 单包最多 100,000 个文件，解压后总计不超过 8 GiB；
- 只接受 `component.json`、`signature.bin` 与 `payloadDir/...` 三类条目，payload 之外的条目一律拒绝；
- 逐文件流式写入暂存目录（`<userData>/components/.staging/`），边写边算 SHA-256；声明大小或 hash 不符立即失败；
- zip 条目中的符号链接位（`0o120000`）直接拒绝；重复条目、清单未登记文件或缺失文件同样拒绝。

### 3.3 安装事务与并发

- 安装先整体解包到 `<userData>/components/.staging/install-<id>-*`，成功后再落盘，结束时清理暂存目录。
- 落盘前获取 `<userData>/components/.install.lock`（`O_CREAT|O_EXCL`）；锁存在且未超过 600 秒判定为并发安装（`install_locked`），超过 600 秒视为陈旧锁并回收一次。
- 每个目标文件先写 `*.sagepkg-tmp` 再 `replace`，实现单文件原子替换；已存在文件先备份到暂存目录的 `.backup/`，任一步失败按备份回滚并删除本次新建文件。
- 重复导入同一 `id` + `version` + `target` 且目标文件大小/hash 全部一致时，直接返回已安装记录，不重复写盘。
- 升级成功后按旧清单删除不再被新版本引用的文件；`component_dir` 还会删除旧的 `<id>/<version>/` 目录。
- `remove` 只删除 `installed.json` 记录且位于允许前缀内的文件；`user_data` 目标会自下而上清理空目录（止于 `<userData>/models`）。
- 元数据写在 `<userData>/components/installed.json`，结构为 `{"schemaVersion": 1, "components": {<id>: InstalledComponent}}`。

## 4. 入口

### 4.1 设置页「组件管理」

设置 → 使用与维护 → 组件管理：

- 查看已安装组件（名称、id、版本、target、大小、签名状态）；
- 「导入 .sagepkg」打开文件选择器，「刷新」重新拉取列表；
- 「扫描组件包」扫描默认目录；
- 列表内可直接导入发现的包；
- 卸载组件（二次确认）；
- 导入/卸载进度经 `api.listen('components:progress')` 订阅（主进程实际发送 `sage:event:components:progress`，preload 的 `listen` 以 `sage:event:` 前缀拼出真实通道）；成功后提示「导入完成。请重启 Sage 后生效」；
- Web 模式没有 `window.electronAPI.components`，页面显示「组件管理仅在 Sage 桌面端可用」。

### 4.2 SageDoctor（兜底/批量）

```bash
python -m backend.cli.rescue components list --json
python -m backend.cli.rescue components scan --dir D:\SageComponents --json
python -m backend.cli.rescue components verify D:\SageComponents\model.sagepkg --json
python -m backend.cli.rescue components import D:\SageComponents\model.sagepkg --json --yes
python -m backend.cli.rescue components remove embedding-bge-small-zh --json --yes
```

交互式 `python -m backend.cli.rescue` 菜单 `[8] 管理离线组件包` 提供相同能力。应用起不来时优先使用该入口。

### 4.3 自动发现目录

应用/CLI 扫描以下位置：

- `<install>/resources/components`
- `<userData>/components/inbox`
- `SAGE_COMPONENT_SCAN_DIRS`（`os.pathsep` 分隔）
- Windows `%ProgramData%\Sage\components`

扫描只匹配各目录**顶层** `*.sagepkg`，不递归子目录；同一真实路径只返回一次。

### 4.4 Electron IPC 与超时

| 通道 | 作用 | 超时 |
| --- | --- | --- |
| `components:list` | 已安装 + 可发现包 | 60 s |
| `components:scan` | 扫描默认目录 | 60 s |
| `components:pick-and-import` | 文件选择器后导入 | 15 min |
| `components:import-path` | 按绝对路径导入 | 15 min |
| `components:remove` | 卸载组件 | 15 min |

- `import-path` 只接受以 `.sagepkg` 结尾的绝对路径（含 Windows 盘符形式）且文件存在；`remove` 的组件 id 必须匹配 `^[a-z0-9][a-z0-9._-]{0,63}$`。
- 子进程继承主进程环境，并在缺省时补 `PYTHONIOENCODING=utf-8`、`PYTHONUTF8=1`；打包态再注入 `SAGE_IS_PACKAGED=1` 与 `SAGE_RESOURCES_DIR`。
- 桌面端把 `build-manifest.json` 的 `branch` 作为 `SAGE_COMPONENT_BRANCH` 传给 CLI，因此 win7 包会拒绝 `main` 通道包。
- 执行时通过 `resolveModuleLaunchCommand(..., 'backend.cli.components', argv)` 复用后端解释器/命令解析；IPC 层另有 `invalid_package`、`invalid_component_id`、`broken_installer`、`spawn_failed`、`cli_failed`、`timeout`、`cancelled` 等错误码。

### 4.5 与本地模型导入的路径一致性

组件包的 `user_data` 目标与「从本地导入」模型都落到 `<userData>/models/`，后端按 `SAGE_USER_DATA_DIR/models` 查找。桌面端统一由 `electron/userDataPaths.ts::resolveSageModelsDir()` 推导：`SAGE_USER_DATA_DIR` 显式覆盖 → 打包态 `app.getPath('userData')` → 开发态 `<cwd>/data`，再拼 `models`。

2026-11-22 之前，模型下载/导入 IPC 用 `process.env.SAGE_USER_DATA_DIR || process.cwd()`，但主进程并不设置该变量：打包版写安装目录、开发态写仓库根，而后端读另一处，导入显示成功却不生效。现在 `models:embedder:*` / `models:ocr:*` IPC 与 spawn 时的 OCR 目录候选都改用 `resolveSageModelsDir()`，与组件包落盘位置一致。

## 5. 构建与签名

### 5.1 生成密钥

```bash
python scripts/gen-component-keypair.py --out-dir .secrets
# .secrets/component-private-key.pem  （gitignored，保存到 CI secret）
# resources/component-public-key.pem   （可入库）
```

CI secret：`SAGE_COMPONENT_SIGNING_KEY`（私钥 PEM 内容）。

密钥为 RSA 3072，私钥 PKCS#8 PEM、权限 `0600`，公钥 SubjectPublicKeyInfo PEM。`--public-out` 可改公钥输出路径；私钥已存在时必须显式加 `--overwrite` 才会替换。私钥目录 `.secrets/` 与 `component-private-key.pem` 已加入 `.gitignore`；`electron-builder.yml` 的 `extraResources` 把 `resources/component-public-key.pem` 拷到安装目录 `resources/` 根下，作为生产终端的内置信任锚。

### 5.2 构建组件包

```bash
python scripts/build-component-packs.py \
  --all \
  --models-dir resources/models \
  --key .secrets/component-private-key.pem \
  --output release/components
```

产物：

- `Sage-Setup-<version>-win7-core.exe`（轻量安装包，不含内置 AI 模型；与全量包同签发布，配合 `.sagepkg` 启用语义检索/OCR）
- `embedding-bge-small-zh-<version>-win7.sagepkg`（payload 前缀 `models/bge-small-zh-v1.5`）
- `ocr-models-ppocr-<version>-win7.sagepkg`（payload 前缀 `models/rapidocr`）
- `components-index.json`：`{"schemaVersion":1,"generatedAt":...,"packages":[{id,name,version,branch,python,arch,file,size,sha256}]}`

参数缺省值：`--models-dir resources/models`、`--output release/components`、`--version 1.0.0`、`--branch win7`、`--python 3.8`、`--arch x64`；私钥也可用 `SAGE_COMPONENT_SIGNING_KEY_PATH` 指定。`component.json` 用 `sort_keys` + 紧凑 JSON 序列化，签名覆盖其原始字节；zip 条目使用固定时间戳（1980-01-01）。

`release-win7.yml` 的 Source job 会自动构建组件包并上传 artifact；未配置 `SAGE_COMPONENT_SIGNING_KEY` 时打印 warning 并跳过。Source job 同时通过临时移走 `resources/models` 构建 core 变体；Cython job 仅注入公钥，保证两个安装包都能验证同一批组件包。

### 5.3 密钥轮换

替换 `resources/component-public-key.pem` 后，旧私钥签名的组件包全部失效，必须重新构建并分发。

## 6. 内网分发建议

- **WebDAV 云盘**：作为上传/交换舱，Ubuntu 用 rclone 同步到 `/srv/sage/components/win7/`。
- **Ubuntu + nginx**：以 HTTPS 只读提供 `.sagepkg` 与 `components-index.json`，支持 Range。
- **GitLab（后期）**：用 Release/Package Registry 留存与审计，CI 负责校验签名后再发布。
- **完全隔离**：把 `.sagepkg` 拷到 U 盘或共享盘，SageDoctor 直接导入。

## 7. 错误码

| code | 含义 |
| --- | --- |
| `public_key_missing` / `public_key_invalid` | 未配置或无法解析公钥 |
| `signature_invalid` / `invalid_signature` / `unsigned_package` | 签名不匹配、签名文件异常或缺失 `signature.bin` |
| `unsafe_path` / `unexpected_file` / `symlink_rejected` / `duplicate_entry` | 路径穿越、未登记文件、符号链接或重复条目 |
| `hash_mismatch` / `size_mismatch` / `missing_file` | 文件内容、大小与清单不符，或清单文件缺失 |
| `python_mismatch` / `arch_mismatch` / `branch_mismatch` | 包与当前运行时/架构/分支不匹配 |
| `install_locked` | 另一个导入正在进行 |
| `write_failed` / `remove_failed` / `invalid_metadata` | 文件被占用、权限不足或已安装元数据非法 |
| `package_missing` / `invalid_zip` / `invalid_manifest` / `package_too_large` | 包不存在、非 zip、清单无效或超出解包限额 |
| `not_installed` | 卸载的组件不在 `installed.json` 中 |

IPC/CLI 外层还可能返回 `cancelled`、`invalid_package`、`invalid_component_id`、`broken_installer`、`spawn_failed`、`cli_failed`、`timeout`、`unexpected_error`；CLI 出错统一退出码为 2。

## 8. 已知限制

- 组件包只支持离线导入；在线瘦包通道、远程组件目录浏览与自动更新尚未实现。
- 扫描只覆盖各扫描目录顶层 `*.sagepkg`，不递归子目录，也没有包内容浏览 UI。
- 升级不保留旧版本供回滚：成功后即删除旧版本不再引用的文件/目录。
- 分支校验依赖调用方提供 `SAGE_COMPONENT_BRANCH`；独立 CLI/脚本未设置时该维度不校验（Python/架构仍校验）。
- `target: user_data` 仅允许 `models/` 前缀，不能用于其他可写目录。

## 9. 验证

```bash
PYTHONPATH=. /home/fz/anaconda3/envs/sage-backend-py38/bin/python -m pytest \
  backend/tests/unit/services/test_components_service.py \
  backend/tests/unit/cli/test_components_cli.py \
  backend/tests/unit/test_build_component_packs.py -q
```

前端：

```bash
npx vitest run \
  src/pages/settings/__tests__/ComponentsTab.test.tsx \
  src/pages/settings/__tests__/settingsTabs.guards.test.ts \
  electron/__tests__/componentsIpc.test.ts
```

## 10. 相关文档

- [101 Win7 内网离线维护](./101-win7-offline-maintenance.md)
- [156 本地 AI 模型内置与离线导入](./156-local-ai-models.md)
- [26 打包矩阵](./26-packaging-matrix.md)
