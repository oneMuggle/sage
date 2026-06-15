# 26. 跨平台打包矩阵

> 本章节描述 Sage 桌面端在各平台的分发产物与用户侧安装路径。
> 更新自 2026-06-15(feat/cross-platform-packaging)。

## 1. 平台覆盖矩阵

| 平台 | 最低版本 | 架构 | 产物 | CI 构建 runner |
|---|---|---|---|---|
| Windows | 7 SP1 | x64 | `Sage-Setup-${version}.exe`(NSIS,含 VCRedist bundling) | `windows-latest` |
| Windows | 10 | x64 | 同上 | 同上 |
| Windows | 11 | x64 | 同上 | 同上 |
| Ubuntu | 20.04+ | amd64 | `sage_${version}_amd64.deb`(原生 deb) | `ubuntu-latest` |
| Linux 通用 | glibc 2.28+ | x64 | `Sage-${version}.AppImage` | `ubuntu-latest` |
| macOS | — | — | **暂不支持**(`mac.target: null`) | — |

**架构限制(本期不支持):** 32-bit Windows · ARM Windows · ARM Linux · 任何 macOS。

## 2. 用户侧安装

### Windows 7 SP1 / 10 / 11

1. 下载 `Sage-Setup-${version}.exe`
2. 双击运行,按向导安装(默认 HKCU,无需管理员权限)
3. 安装阶段会**静默装** VC++ 2015-2022 Redistributable(已装会跳过)
4. Win7 SP1 用户需提前装 **KB3033929**(SHA-2 代码签名,Phase 3 启用签名后强依赖)

### Ubuntu 20.04+ / Debian / Mint

```bash
sudo apt install ./sage_${version}_amd64.deb
# 或
sudo dpkg -i sage_${version}_amd64.deb && sudo apt-get install -f
```

安装后 `sage` 出现在应用菜单 → Office 类别。卸载:`sudo apt remove sage`。

### 其它 Linux(Fedora / Arch / openSUSE / NixOS)

```bash
chmod +x Sage-${version}.AppImage
./Sage-${version}.AppImage
```

可选:用 [AppImageLauncher](https://github.com/TheAssassin/AppImageLauncher) 集成到桌面菜单。

## 3. 真机烟测策略

| 平台 | 自动化 | 频率 | 工具 |
|---|---|---|---|
| Win Server 2022 | ✅ CI `electron-smoke`(每次 PR) | Per-PR | Playwright `_electron` |
| Win10 / Win11 | ⚠️ 等价于 Server 2022(同 Chromium 内核),无独立真机 | — | — |
| Win7 SP1 | ❌ 人工([`21-win7-lts.md`](./21-win7-lts.md)§3) | 每 release | `scripts/win7-smoke/*.ps1` |
| Ubuntu | ❌ 暂无 | — | (TODO:可加 `electron-smoke` 的 Linux 镜像) |

## 4. 已知限制

- **macOS 缺席** — `electron-builder.yml` 的 `mac.target: null` 是 Phase 1 战略决策(Win7 优先)。Phase 3 可补 `dmg` + 签名。
- **deb 无 GPG 签名** — 用户首次 `apt install` 会警告 "未签名"。Phase 3 加 GPG key + APT repo。
- **VCRedist bundling 让安装包 +~14MB** — 文档已明示;可接受(节省 Win7 用户找 VC++ 的麻烦)。
- **AppImage 不进 apt 列表** — 这是 AppImage 设计本身的特性,不是 bug。

## 5. 故障排查

| 现象 | 平台 | 原因 / 处理 |
|---|---|---|
| `sage.exe` 双击无响应 | Win7 SP1 | KB3033929 未装(若用了签名版) → 装补丁;或 VCRedist 未装成功 → 手动跑 `vc_redist.x64.exe /install` |
| `error while loading shared libraries: libnss3.so` | Linux | `sudo apt install libnss3`(deb 应自动解,AppImage 需手动) |
| Ubuntu 24.04 apt install 报 `libasound2` not found | Ubuntu | 24.04 改名为 `libasound2t64`;升级到本计划的 deb 已用 electron-builder 默认列表(自动迁移) |

## 6. 相关文档

- [`20-electron.md`](./20-electron.md) — Electron 主进程架构
- [`21-win7-lts.md`](./21-win7-lts.md) — Win7 LTS 分支策略
- `../plans/2026-06-15_cross-platform-packaging.md` — 本计划文档(实施后归并并删除)
