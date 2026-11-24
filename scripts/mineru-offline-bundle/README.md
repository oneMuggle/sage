# MinerU 内网离线部署包

面向内网（无外网）环境部署 [MinerU](https://github.com/opendatalab/MinerU) 文档解析服务的
离线包构建与安装工具。配套 Sage 客户端的 MinerU 适配章节见
[`docs/technical/154-mineru-deployment.md`](../../docs/technical/154-mineru-deployment.md)。

本目录是**离线包的唯一源**：包里的一切（部署脚本、systemd 模板、配置模板）都从
这里打进 tar；`/home/fz/mineru-offline-bundle-out` 里的旧包不保留下一次构建的改动。

## 1. 包内容

| 组件 | 说明 |
| --- | --- |
| `python/` | python-build-standalone 便携 CPython（默认 3.12），不依赖目标机 Python |
| `wheels/` | 目标平台全部 wheel（含 `mineru[full]` 及其依赖；A6000 老驱动可附 `vllm==0.19.1`） |
| `models/` | MinerU 模型（离线 `source: local`，运行期零外网） |
| `install.sh` | 目标机安装：便携 Python → venv → `--no-index` 装 wheel → 模型/config → systemd |
| `verify.sh` | 安装后只读验收（含鉴权实测） |
| `systemd/` | `mineru.service`、`mineru-start.sh`（bearer 包装）、`mineru-start-anonymous.sh`、`mineru.env` 模板 |
| `config/config.yaml.template` | `source: local` + 模型路径/后端的配置模板 |
| `MANIFEST.env` | 版本事实（供 install/verify source） |
| `MANIFEST.txt` | 人机可读清单（组件体积等） |

## 2. 构建（联网 Linux x86_64 构建机）

```bash
bash scripts/mineru-offline-bundle/build-bundle.sh
```

默认产出 `$HOME/mineru-offline-bundle-out/mineru-offline-bundle-<ver>-<YYYYMMDD>-linux-x86_64.tar`
与同名 `.sha256`。包体不 gzip（wheel/模型本身已压缩），约 8 GB。

常用覆盖项：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `MINERU_SPEC` | `mineru[full]>=4.1,<4.2` | 版本下限 4.1（V1 异步 API），上限 <4.2 |
| `EXTRA_SPEC` | 空 | 如 `vllm==0.19.1`，用于锁 torch 2.10 / CUDA 12.8 / 驱动 ≥535 |
| `PY_VERSION` | `3.12` | 便携 Python 主版本 |
| `PBS_VERSION` | latest | 指定 python-build-standalone 发布日期 tag，绕过 GitHub API 不可达 |
| `PIP_PLATFORM` | 空 | 交叉下载目标平台 wheel（如 `manylinux_2_28_x86_64`） |
| `MODEL_SOURCE` | `huggingface` | 失败自动回退 `modelscope`（HF 先禁 Xet 重试一次） |
| `TIER` / `SMALL_BACKEND` / `VLM_ENGINE` | `standard` / `torch` / `vllm` | 写入装包配置 |
| `OUT_DIR` / `WORK_DIR` | `~/mineru-offline-bundle-out` / `~/mineru-bundle-build` | 产物与缓存目录 |
| `KEEP_STAGING=1` / `CLEAN_WORK_DIR=1` / `SKIP_DISK_CHECK=1` | — | 排障保留 staging / 构建后清缓存 / 跳过 25 GB 磁盘检查 |

构建流程：便携 Python（npmmirror → github → ghproxy.net 三镜像回退）→ venv `--copies`
→ `pip download` 全量 wheel、sdist 再 `pip wheel` 化 → `mineru-kit models download`
+ `models verify` → staging 打包 + `MANIFEST.env`/`MANIFEST.txt` → 未压缩 tar + sha256。

> 构建机需要约 25 GB 空闲磁盘；`models verify` 依赖 vllm 运行时可导入，
> 否则会报模型校验失败。

## 3. 目标机安装

```bash
tar -xf mineru-offline-bundle-<ver>-<date>-linux-x86_64.tar
cd mineru-offline-bundle
sha256sum -c ../mineru-offline-bundle-<ver>-<date>-linux-x86_64.tar.sha256  # 可选
sudo ./install.sh                       # 默认 bearer 鉴权
sudo ./verify.sh                        # 安装后验收
```

`install.sh` 参数：

```text
--prefix /opt/mineru        安装根（便携 Python + venv）
--home   /var/lib/mineru    服务用户主目录（模型在 ~/.mineru/models）
--user   mineru             系统服务用户
--port   8000               api-server 监听端口
--tier   standard           basic | standard
--auth-mode bearer|anonymous  默认 bearer
--no-systemd                不写 unit（手动启动，镜像/容器场景）
SKIP_GPU_CHECK=1            跳过 nvidia-smi 检查
```

### 3.1 鉴权模式（重要）

`mineru-kit api-server` 的 `--api-key` **只能在命令行传入，没有环境变量回退**。
因此只在 unit 里配 `EnvironmentFile` 不会开启鉴权——服务端会静默保持匿名。本包的
做法是：

- `/etc/mineru/mineru.env`（0600 root）保存 `MINERU_API_KEY`，由 systemd 以 root 身份
  读取并注入服务环境；
- `mineru.service` 的 `ExecStart` **必须**是 `/etc/mineru/mineru-start.sh`——一个
  0755、**不含密钥**的包装脚本，由它把注入的 `$MINERU_API_KEY` 展开成
  `--api-key "$MINERU_API_KEY"`；
- `bearer` 模式：无凭据访问受保护端点得 401/403；
  `anonymous` 模式：包装脚本不传 `--api-key`，**必须靠内网防火墙限制来源**。

`install.sh --auth-mode anonymous` 会保留 env 文件里的旧 key 值（便于日后切回
bearer），但服务端不会收到它；同时写入 `/etc/mineru/auth-mode` 记录期望模式，
供 `verify.sh` 对比实测结果。

### 3.2 验收（`verify.sh`）

八项检查：包完整性 / `systemd` 状态与 `ExecStart` 形态 / GPU / 鉴权配置 / `/v1/health` /
**`/v1/usage` 鉴权实测** / `/v1/tiers` / 模型目录与 `source: local`。

`/v1/health`、`/v1/models`、`/v1/tiers` 是公开端点，**不能**证明鉴权生效；
`verify.sh` 探测非公开的 `/v1/usage`：无凭据 200 ⇒ `anonymous`，401/403 ⇒ `bearer`，
并打印：

```text
serverAuthMode=bearer（期望 bearer）
```

期望与实测不一致时（如期望 bearer 实测 anonymous）⇒ FAIL，提示检查包装脚本与 unit。
脚本只输出判定与 `access_level`，**从不回显 API key**。

## 4. Sage 客户端配置

设置页「MinerU 服务」（`preferences.mineru_service`）：

| 字段 | 取值 |
| --- | --- |
| `baseUrl` | `http://<服务器内网IP>:8000` |
| `apiKey` | `bearer`：服务器上 `sudo sed -n 's/^MINERU_API_KEY=//p' /etc/mineru/mineru.env` 读出后填入；`anonymous`：留空 |
| `defaultTier` | `standard`（或 `basic`） |
| `timeoutSeconds` | `300` |

`GET /api/v1/mineru/status` 只返回 `hasApiKey` 布尔与 `serverAuthMode`，不返回密钥。
**不要把 key 粘贴到日志、聊天或工单里**；Sage 侧也可通过 gitignored 的 `.env.local`
或环境变量注入（见技术文档 §6）。

## 5. 从旧部署升级

旧包（`/home/fz/mineru-offline-bundle-out` 生成的版本）的 unit 里既没有包装脚本
也没有 `--api-key` ⇒ 线上实际是**匿名**服务。重跑新版 `install.sh`：

- 默认 `bearer`：本次起开启鉴权，既有客户端需要补填 `apiKey`；
- 若要维持旧行为：`sudo ./install.sh --auth-mode anonymous`。

`install.sh` 会检测旧 unit 并打印 upgrade 提示；`verify.sh` 对无 `auth-mode` 记录的
旧装机会给出 WARN（建议重跑 install 或显式选择模式）。

## 6. 排障

| 现象 | 检查 |
| --- | --- |
| 服务起不来 | `journalctl -u mineru -n 200 --no-pager`；`/etc/mineru/mineru-start.sh` 首行报 `MINERU_API_KEY 未注入` ⇒ env 文件/`EnvironmentFile` 问题 |
| 期望 bearer 实测 anonymous | wrapper 是否含 `--api-key`；`systemctl cat mineru` 是否被旧 drop-in 覆盖；`systemctl daemon-reload` 是否执行 |
| 启动慢/超时 | vLLM 冷启动可超过 60 s，`TimeoutStartSec=300`；看 journal 是否在加载模型 |
| 模型加载失败 | `verify.sh` 第 8 项；确认 `~/.mineru/models` 与 `config.yaml` 的 `source: local` |
| 显存不足 | 降 `--tier basic`，或换更大显存/更多卡；`nvidia-smi` 看占用 |
| 客户端 401 | `serverAuthMode` 与设置页 `apiKey` 是否匹配（bearer 需填 key，anonymous 需留空） |

## 7. 运行时版本矩阵

| vllm | torch | CUDA | NVIDIA 驱动 |
| --- | --- | --- | --- |
| 0.19.x（本包默认推荐用于 A6000） | 2.10 | 12.8 | ≥525（建议 ≥535） |
| 0.20–0.26 | 2.11 | 13.0 | ≥580 |
| 0.27–0.30 | 2.11 | 13.0 | ≥580 |

镜像中若装了旧驱动，请用 `EXTRA_SPEC="vllm==0.19.1"` 重新构建，而不是在目标机上更换
驱动。

## 8. 相关文档

- 技术手册：[`docs/technical/154-mineru-deployment.md`](../../docs/technical/154-mineru-deployment.md)
  （服务端部署、客户端 `parse_document` 集成、安全与运维）
- 章节总览：[`docs/technical/README.md`](../../docs/technical/README.md)
