# 更新安装与回滚语义重做 Round 1 实施计划

> 日期: 2026-09-18 · 分支: `docs/update-rollback-cmid-r1-plan` · 基于 main
> 系列: 更新子系统专项第六批 (#996) 的后续设计
> Win7 对齐: **设计同样适用 release/win7**（其 updateManager 已含 #996 同款
> 静默安装/完整性落账）；文档随下一轮 cherry-pick 同步。
> 依赖: 零新增。

## 背景

#996 落地后，provider 更新链路已具备：内置公钥验签、真实 sha512 落账、
安装包收进 `userData/update-cache`、Windows 静默安装（`/S /D=` spawn）。
仍存四处结构性缺口：

1. **回滚数据语义冲突**：`cachedRollbackPackage` 存的是**新版本**安装包，
   而 `rollback()`/`reinstallFromPackage` 校验
   `cached.version === state.lastKnownGoodVersion`（旧版本）——两者永不相等，
   回滚必然拒绝。即：坏版本更新后**没有**可用的自动回滚数据。
2. **`.prepare-rollback.bat` 无人执行**：Windows 的 `prepareForUpgrade`
   把回滚准备写入 bat 后注释"deferred to a post-exit batch script"，
   但没有任何机制运行它（NSIS 不会调用）。
3. **非 Windows provider 安装无契约**：#996 显式报错指引手动安装，
   macOS（zip→.app）与 Linux（AppImage）暂无静默路径。
4. **双轨安装路径**：legacy 路径走 electron-updater `quitAndInstall`，
   provider 路径走自管 spawn——健康检查/回滚对两条路径的行为需统一验收。

## 批次任务

### A. 回滚数据流（语义对齐）

- `prepareForUpgrade()`（替换前）把**当前版本**安装包留底：
  - 来源优先级：`userData/update-cache` 里 version === currentVersion 的
    包 → 无则跳过留底（老用户首轮回滚数据为空，如实记录）；
  - `cachedRollbackPackage = { version: currentVersion, path: 留底绝对路径,
    sha512: 当前包真实 hash, size, signature, fileUrl }`；
  - `lastKnownGoodVersion` 校验从此自然成立（不放宽校验本身）。
- 下载新版本时**不再**覆盖 `cachedRollbackPackage`（新包只进
  `pendingUpdate` + `providerInstallerPath`）。

### B. 执行机制（Windows）

- `prepareForUpgrade` 写 bat 的同时注册
  `HKCU\Software\Microsoft\Windows\CurrentVersion\RunOnce`：
  `sage-rollback` = `cmd /c <userData>\.prepare-rollback.bat`；
- bat 内容（既有）：交换 installDir 与 `.prev` 目录 → 重启 app；
- app 退出（quitAndInstall / provider spawn 前的 app.exit）后由 RunOnce
  接管下一次登录前的交换；
- `onAppStartup` 检测到 `.prev` 交换完成后清理 RunOnce 项与 `.prev`。

### C. 非 Windows provider 安装

- v1 维持 #996 的显式报错 + 手动安装指引（本期不改）；
- AppImage 路线预研记入候选：下载替换 AppImage 文件 +
  `--appimage-extract-and-run` 过渡；macOS 需签名/公证前提声明。

### D. 统一验收

- 集成测试（windows runner）：下载 → 静默安装 → relaunch → 健康检查
  失败 ×3 → rollback → 旧版本 relaunch 全链；
- 断言：RunOnce 注册/清理、`.prev` 交换、`lastKnownGoodVersion` 迁移。

## 验证

- Phase A/B 单测：留底数据合法性、RunOnce 注册/清理；
- Phase D 全链集成测试作为合入门槛；
- 手工冒烟：真实 NSIS 包升级 + 人为破坏健康检查的回滚演练。

## 风险

- RunOnce 需要用户会话（HKCU），服务化场景不适用（本产品为桌面 app，成立）；
- NSIS `/S` 在目标文件被占用时的行为依赖安装器脚本（electron-builder
  默认会尝试关闭应用）——Phase D 集成测试覆盖。
