# 100 Win7 服务检测 + 修复文档打包

> 发布分支：`release/win7`
> PR：#1333 (feat/win7-service-fix) + #1337 (ci smoke 修复)
> 生效版本：v0.4.9-alpha.50-win7 起

## 背景与动机

内网 Win7 机器常被企业组策略 / 管控软件 (360 天擎 / 联软 / IP-guard) 禁用
`TrustedInstaller` 或 `wuauserv` 服务。症状：

- Sage 启动后 splash 显示、然后主窗口白屏 / 不出现 (之前归类为"浏览器内核版本低")
- 用户反馈"自检界面消失"

PR #1333 之前的 runtime-check 已覆盖 6 项检查 (VC++ Redist / KB3033929 / KB4474419 /
KB4490628 / KB2670838)，但只打补丁解决不了服务禁用问题——真正的根因在服务配置。
本次新增 2 个 service check + 修复文档打包进安装包 + 弹窗动态按钮引导。

## 变更清单 (PR #1333)

| 文件 | 改动 |
|---|---|
| `electron/runtime-check.ts` | +256 / -32: 重构为可组合的 check 集合, 新增 `checkTrustedInstallerService()` + `checkWuauservService()` |
| `electron/__tests__/runtime-check.test.ts` | +379: 13 个 unit test 覆盖两条 service 路径 |
| `electron-builder.yml` | +10: `extraResources` 新增 `resources/win7-fix → win7-fix` 打包条目 |
| `resources/win7-fix/sage-win7-fix.md` | 新增 122 行: 用户面修复流程文档 |
| `resources/win7-fix/fix.bat` | 新增 97 行: 一键服务启用 + 重启脚本 |

## 实现要点

### 1. Service check 设计

两条 service check 共享同一实现骨架——`sc query <service>` + 状态解析:

```ts
async function checkService(serviceName: string): Promise<RuntimeCheckResult> {
  // 1. execFileP('sc', ['query', serviceName], { timeout: 2000 })
  // 2. 解析 stdout: 找 "STATE" 行, 匹配 /RUNNING/ 即 ok
  // 3. 异常分支:
  //    - sc 命令抛错 / 超时 → warn (不能判 critical, 因为 sc 本身可能被禁用)
  //    - 状态非 RUNNING → critical (明确被禁用)
  // 4. 非 Win32 平台直接返回 ok 占位
}
```

`runRuntimeChecks()` 现在并行跑 8 个 check (Promise.all 总耗时 ≤ 5s 最慢项):

```ts
const results = await Promise.all([
  checkVCppRedistX64(),
  checkVCppRedistX86(),
  checkKB3033929(),
  checkKB4474419(),
  checkKB4490628(),
  checkKB2670838(),
  checkTrustedInstallerService(),  // PR #1333 新增
  checkWuauservService(),          // PR #1333 新增
]);
```

### 2. 弹窗动态按钮

之前 `showRuntimeMissingDialog()` 按钮固定 4 个。PR #1333 起根据 critical 项动态
插入"打开修复文档"按钮——仅当 service check 失败时才出现, 指向
`<resourcesPath>/win7-fix/`:

```ts
const hasServiceIssue = missing.some(
  (m) => m.name === 'trusted_installer' || m.name === 'wuauserv',
);
const buttons = [
  '打开下载页',
  ...(hasServiceIssue ? ['打开修复文档'] : []),
  '查看日志目录',
  '仍要启动',
  '退出',
];
```

`dialog.showMessageBox()` 的 `result.response` 是按钮索引, 动态插入后
switch 分支要按新索引解析。

### 3. electron-builder 打包

`electron-builder.yml` 新增条目:

```yaml
extraResources:
  - from: "resources/win7-fix"
    to: "win7-fix"
    filter: ["**/*"]
```

安装后路径: `<install-dir>/resources/win7-fix/sage-win7-fix.md` + `fix.bat`。
`fix.bat` 封装步骤 1-3 + `shutdown /r /t 0` 一键重启, 用户右键"以管理员身份运行"即可。

### 4. 用户面文档

`resources/win7-fix/sage-win7-fix.md` 结构:

1. **症状说明** — 为什么"补丁通常不是问题"
2. **前提** — 管理员权限 cmd
3. **步骤 1-3** — 检查 → 启用 TrustedInstaller / wuauserv (注册表直写 Start=3) → 重启验证
4. **步骤 4** — 启动 Sage
5. **步骤 5 (可选)** — wuauserv 改回自动启动 (Start=2)
6. **补丁安装顺序** — 仅当 service 都 running 但 Sage 还白屏才走 (KB4490628 → KB3033929 → KB4474419 → KB2670838)
7. **失败对照表** — 6 个常见错误码 + 处理
8. **一键脚本** — 指向 `fix.bat`

## CI smoke 失败与修复 (PR #1337)

PR #1333 合入后, release/win7 CI smoke 系统性失败 (run 35510214994)。

**根因**: GitHub `windows-latest` runner 的 `TrustedInstaller` / `wuauserv` 状态
不可预测。service check 返回 critical → `showRuntimeMissingDialog()` 调用
`dialog.showMessageBox()` 阻塞 Electron 主进程 → `createMainWindow()` 永远调不到 →
Playwright `firstWindow()` 30s 超时。

**修复** (commit 936587c4, PR #1337):

```yaml
# .github/workflows/ci.yml smoke step
env:
  SAGE_SKIP_BACKEND: '1'
  CI: 'true'
  SAGE_RUNTIME_CHECK_ON_START: 'false'  # ← 新增
```

`electron/main.ts:2187` 已有 env gate:

```ts
if (process.env.SAGE_RUNTIME_CHECK_ON_START !== 'false') {
  await runRuntimeChecks();
}
```

smoke test 只关心 IPC bridge + frontend 渲染, 不需要真跑 runtime check, 关闭即可。

**main 分支同步**: PR #1340 (ci/main-smoke-skip-runtime-check) 把同一个 env var
加到 main 的 ci.yml smoke step。main 的 runtime-check 目前只跑 6 项 (不带 service
check), CI 实际能过; 这是防御性同步, 防止未来 main 加类似 service check 时踩同一个坑。

## 与其他文档的关系

| 文档 | 关系 |
|---|---|
| [`20-electron.md`](./20-electron.md) | Electron 21 桌面壳, 含 7 个 Win7 启动开关;本文是其中 runtime-check 子系统的展开 |
| [`26-packaging-matrix.md`](./26-packaging-matrix.md) | 跨平台打包矩阵;本文补 `resources/win7-fix` 这一 extraResources 条目的语义 |
| [`31-win7-lts.md`](./31-win7-lts.md) | Win7 LTS 维护总览;本文是其"启动失败排查"章节的实现细节 |
| `resources/win7-fix/sage-win7-fix.md` | 本文是面向开发者的设计/集成文档;该文件是面向终端用户的修复操作手册 |

## 教训

1. **CI 环境状态不可预测**: 服务状态、注册表项、环境变量都可能随 runner 镜像更新漂移。
   任何"检查系统状态 → 弹对话框"的流程, 在 CI 都要能一键关闭。
2. **`dialog.showMessageBox` 阻塞语义**: 在 Electron 主进程里, 这是同步阻塞。
   在 `createMainWindow()` 之前调用会导致首窗口永远不出来, 触发 Playwright 超时。
3. **防御性同步值得做**: main 当前不需要这个 env var, 但加 5 行 YAML 能避免未来
   加 service check 时重蹈覆辙 (PR #1340)。
