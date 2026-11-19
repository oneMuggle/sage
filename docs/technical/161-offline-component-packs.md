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

## 4. 入口

### 4.1 设置页「组件管理」

设置 → 使用与维护 → 组件管理：

- 查看已安装组件（名称、id、版本、大小、签名状态）；
- 「导入 .sagepkg」打开文件选择器；
- 「扫描组件包」扫描默认目录；
- 列表内可直接导入发现的包；
- 卸载组件（二次确认）；
- 导入进度经 `components:progress` 事件展示。

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

## 5. 构建与签名

### 5.1 生成密钥

```bash
python scripts/gen-component-keypair.py --out-dir .secrets
# .secrets/component-private-key.pem  （gitignored，保存到 CI secret）
# resources/component-public-key.pem   （可入库）
```

CI secret：`SAGE_COMPONENT_SIGNING_KEY`（私钥 PEM 内容）。

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
- `embedding-bge-small-zh-<version>-win7.sagepkg`
- `ocr-models-ppocr-<version>-win7.sagepkg`
- `components-index.json`（包名、大小、sha256）

`release-win7.yml` 的 Source job 会自动构建并上传；Cython job 仅注入公钥，保证两个安装包都能验证同一批组件包。

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
| `signature_invalid` | 签名不匹配 |
| `unsigned_package` | 缺少 `signature.bin` |
| `unsafe_path` / `unexpected_file` | 路径穿越或未登记文件 |
| `hash_mismatch` / `size_mismatch` | 文件内容与清单不符 |
| `python_mismatch` / `arch_mismatch` / `branch_mismatch` | 包与当前运行时/分支不匹配 |
| `install_locked` | 另一个导入正在进行 |
| `write_failed` / `remove_failed` | 文件被占用或权限不足 |
| `package_missing` / `invalid_zip` / `invalid_manifest` | 包本身无效 |

## 8. 验证

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

## 9. 相关文档

- [101 Win7 内网离线维护](./101-win7-offline-maintenance.md)
- [156 本地 AI 模型内置与离线导入](./156-local-ai-models.md)
- [26 打包矩阵](./26-packaging-matrix.md)
