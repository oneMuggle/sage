# 依赖安全现代化实施计划

> **状态：进行中计划。** 批次 1 已执行低风险依赖更新，但因 React Router 6.x 仍落在当前 advisory 影响范围内，批次 1 尚未完全验收；不提交代码。
>
> **For agentic workers:** 实施时按批次逐项执行，并在每个批次完成后进行独立验证、代码审查和回滚点确认。所有步骤使用复选框跟踪；仅对已实际执行且结果明确的步骤标记 `[x]`。

**目标：** 在不破坏 Sage Electron 桌面运行、打包产物和 Win7 LTS 支持的前提下，分批降低 npm 依赖漏洞暴露面，并建立可重复的审计、构建和升级门禁。

**架构：** 先冻结当前依赖树与构建行为作为可回滚基线，再按风险和耦合度分批升级 Web 工具链、打包工具和测试工具。Electron runtime 与 Win7 支持不混入普通依赖升级，单独经过兼容性决策门；`main` 与 `release/win7` 保持独立演进，必要的安全修复采用经过验证的 cherry-pick，而不是分支合并。

**技术栈：** npm lockfile v3、React 18、React Router、Vite、Vitest、Electron、electron-builder、PostCSS、GitHub Actions、Electron Playwright smoke/deep tests。

**依据与范围：** 本计划依据仓库当前 `package.json`、`package-lock.json`、`vite.config.ts`、`electron-builder.yml`、CI workflow 以及 2026-08-30 在当前工作区执行的 `npm audit --json`。后续执行者必须在实际升级前重新生成审计结果，不能把本文件中的版本或数量当作永久不变的事实。

## 本次安全清理执行记录（2026-08-30）

- [x] 逐项核实调用方：`rg` 检查 `src/`、`electron/`、`tests/`、`scripts/` 及动态导入；生产源码没有 `react-syntax-highlighter` 的 import/require/dynamic import，`Message.tsx` 仅有历史注释，实际代码使用 `ShikiCodeBlock`。同时移除 `vite.config.ts` 中仅为该包保留的 `manualChunks` 引用。
- [x] 从 `package.json` 移除未使用的 `react-syntax-highlighter` 与 `@types/react-syntax-highlighter`，使用 npm 11.12.1 正常生成 `package-lock.json`；未使用 `npm audit fix --force`、overrides 或不兼容 major。
- [x] 目标传递依赖来源已确认：`js-yaml` 来自 `electron-builder`/`app-builder-lib`/`builder-util` 及 ESLint，`undici` 来自 `jsdom` 与 `node-gyp`，`brace-expansion` 来自各版本 `minimatch`。通过父依赖当前兼容范围的正常解析更新，未直接添加顶层依赖或强制 override。
- [x] 更新后锁树版本：`js-yaml@4.3.2`（原 4.2.0，越过 `<4.3.1` advisory）、顶层 `undici@7.29.0`（原 7.28.0，越过 `<7.29.0` advisory）、`brace-expansion@1.1.18`（旧 1.x vulnerable 子树改为修复版本），同时保留 `undici@6.28.0`（node-gyp 的兼容 6.x 路径）及安全的 brace-expansion 2.x/5.x 子树。`npm ls` 无 errors；干净 `npm ci` 成功。
- [x] 审计结果由本轮基线 `moderate 7 / high 5 / critical 0 / total 12` 降至 `moderate 4 / high 2 / critical 0 / total 6`；`npm audit --omit=dev` 为 `moderate 2 / high 0 / critical 0 / total 2`。剩余项仅为 Electron 21 runtime/get/extract-zip、React Router 6.x 及其工具链路径；本次未触碰 Electron runtime。
- [x] `npm run typecheck` 与 `npm run build` 成功。
- [ ] `npm run test:run` 退出 1：`204` suites 中 `203` 通过，`1451` tests 中 `1450` 通过；唯一失败为既有 `tests/packaging/verify-artifacts.spec.ts` 缺少 `release/0.4.9-alpha.29/sage_0.4.9-alpha.29_amd64.deb`。该失败属于缺失 deb 产物，不能归因于本次依赖清理；测试另报告 2 个既有 `window is not defined` unhandled errors，未修改测试或伪造产物。
- [x] 未修改 `release/win7`，未提交 commit。

## 全局约束

- 当前工作区已有其他未提交改动；执行本计划前必须单独建立依赖升级分支或 worktree，并且不得覆盖、回退或混入这些改动。
- 本计划当前只允许写入本文件；实施阶段才允许按批次修改依赖及必要的配置、测试和文档。
- 禁止直接修改或删除 `release/win7`；该分支长期维护至 **2027-12-13**，不可与 `main` 合并。
- `main` 使用 Electron 21.4.4、Python 3.11、Chromium 106；`release/win7` 使用 Electron 21.4.4、Python 3.8、Chromium 106，并分别使用自己的 Python 依赖文件。
- 不得因为 `main` 的 npm 依赖升级而自动同步 `release/win7`；跨分支仅在安全修复确有价值、完成 py38/Win7 验证后按需 cherry-pick。
- Node/npm 版本必须先记录并固定在 CI 与本地验证矩阵中；不得通过未经审查的全局安装解决升级问题。
- 每个批次必须先记录升级前 lockfile SHA、`npm audit` 输出、构建/测试结果和产物校验信息，再修改依赖。
- 每个批次只解决明确范围的问题；不得使用无边界的 `npm audit fix --force`，不得为了清零数字而绕过真实漏洞或引入未评估的 major migration。
- 任何安全豁免必须包含漏洞编号、受影响路径、实际可达性、补偿控制、责任人和复查日期，并且不能把 critical/high 漏洞静默标记为已接受。

## 当前 npm audit 基线（2026-08-30）

在当前工作区执行 `npm audit --json` 得到：

| 指标 | 基线 |
| --- | ---: |
| info / low / moderate / high / critical | 0 / 0 / 9 / 15 / 4 |
| 漏洞总数 | **28** |
| 依赖总数（prod / dev / optional / peer） | 268 / 824 / 93 / 40 |
| lockfile | v3 |

当前顶层解析版本（以 `npm ls --depth=0` 为准）：

| 依赖 | `package.json` 约束 | 当前解析版本 | 主要问题或关注点 |
| --- | --- | --- | --- |
| `electron` | `^21.4.4` | 21.4.4 | 高危/中危漏洞较多；升级到已修复现代版本会触发 Chromium、Node、原生 ABI、Win7 兼容性决策 |
| `electron-builder` | `^24.13.3` | 24.13.3 | 通过 `app-builder-lib`、`builder-util`、`dmg-builder` 和 `tar` 形成高危/critical 传递链 |
| `tar` | 传递依赖 | 解析版本需在执行时重新记录 | critical：node-tar 路径穿越、硬链接/符号链接、解析 DoS 等；当前审计修复路径指向升级 electron-builder |
| `postcss` | `^8.4.32` | 8.5.26 | 审计范围 `<=8.5.22`；需记录为何当前解析版本仍出现在审计结果及 lockfile 子树中，并确认重新安装后的结果 |
| `react-router-dom` | `^6.20.0` | 6.30.6 | moderate：open redirect/XSS 相关修复范围覆盖旧版本；同时受 `react-router` 7.18.0 以下问题影响 |
| `react-router` | 传递依赖 | 6.30.6 | moderate：反斜杠绕过 open redirect、SSR hydration 构造器注入；本项目需审查是否使用 SSR（当前 Electron file:// renderer 不是 SSR 假设） |
| `vite` | `^5.0.8` | 5.4.21 | high：优化依赖 source map 路径穿越、Windows UNC/NTLM 泄露、`server.fs.deny` 绕过；升级可能影响 Vite 配置和构建产物 |
| `vitest` | `^1.6.0` | 1.6.1 | critical：UI server 任意文件读取/执行路径，并受 Vite/vite-node 传递漏洞影响 |
| `@vitest/ui` | `^1.6.0` | 1.6.1 | critical：与 Vitest UI server 漏洞链直接相关；若非必要应评估移除运行入口，不能只依赖网络隔离 |
| `@vitest/coverage-v8` | `^1.6.0` | 1.6.1 | critical 审计链；需与 Vitest 主版本配套升级 |

审计结果显示的可用修复方向包括：`postcss` 需要高于 8.5.22，React Router 需要至少越过当前 advisory 的 7.18.0 范围（或采用官方 backport/明确补丁版本），Vite 需要高于 6.4.2，Vitest 相关包需要至少越过 3.2.5；npm 当前给出的自动修复候选包括 `electron-builder` 26.15.3、`electron` 44.0.0、`vite` 8.2.2、Vitest 系列 4.1.11。上述候选只是调查输入，不是未经兼容性验证的批准版本。

## 依赖关系与文件地图

实施者先确认以下文件职责，再按批次修改最小范围：

- `package.json`：直接 npm 依赖、脚本和版本约束；只有对应批次批准后才能修改。
- `package-lock.json`：唯一可复现解析树；必须由与 CI 相同的 npm 版本重新生成并审查 diff。
- `vite.config.ts`：React dedupe、file:// 相对路径、manual chunks、Vitest jsdom/exclude 配置；Vite/Vitest 升级时重点回归。
- `electron-builder.yml`：asar、extraResources、Python bundle、Win7 NSIS、Linux 产物和输出目录；builder 升级时重点回归。
- `electron/main.ts`、`electron/backendLauncher.ts`、`electron/preload.ts`、`electron/invoke.ts` 及 `electron/**/__tests__`：Electron runtime、IPC、后端启动和安全边界；runtime 决策门必须覆盖。
- `src/**` 与 `src/**/__tests__`：React Router 导航、HashRouter/file:// 路径、前端构建和测试行为；Router/Vite 升级时按实际使用点修复。
- `tests/electron/**`、`e2e/**`、`playwright.config.*`：桌面 smoke/deep 和 packaged 行为；不能用纯单元测试替代。
- `.github/workflows/ci.yml`、`.github/workflows/e2e-*.yml`、`.github/workflows/release*.yml`：main、PR、Linux/Windows、Win7 LTS 构建和测试矩阵；每个批次需确认 Node/npm 缓存键包含 lockfile。
- `scripts/fix-chrome-sandbox.sh`、`scripts/bundle-python-main.ps1`、`scripts/bundle-python.ps1` 以及 release 脚本：安装后脚本、Python bundle 和打包前置；升级后必须验证脚本不依赖旧 node_modules 布局。

## 实施步骤

### 批次 0：冻结基线与可回滚证据

**目标：** 在任何依赖变更前证明当前代码、依赖树、构建、测试和产物状态，并把安全问题按直接/传递、开发期/发布期、main/Win7 影响分类。

- [ ] 记录 `git rev-parse HEAD`、当前分支、`node --version`、`npm --version`、操作系统、npm 配置中影响 registry/engine 的字段，以及 `npm ls --all --json`。
- [ ] 重新执行并保存 `npm audit --json`、`npm audit --omit=dev --json` 和 `npm audit signatures`（若 registry 支持），记录漏洞总数、severity、advisory URL、受影响路径和修复候选。

**批次 0 当前状态记录（2026-08-30）：** 本次短期缓解已确认 Vite 配置原先未显式绑定地址；已在 `vite.config.ts` 将 Vite dev/preview server 及独立的 Vitest API/UI server 固定到 `127.0.0.1`，并新增配置回归测试。该限制只降低共享网络暴露面，不替代 `@vitest/ui` 漏洞修复；完整批次 0 的依赖审计、基线命令和产物证据仍按上列清单待执行，不因本项完成而标记批次 0 完成。
- [ ] 用 `npm explain tar`、`npm explain esbuild`、`npm explain postcss`、`npm explain react-router`、`npm explain vite-node` 逐条确认传递来源，特别确认 `tar` 是否全部来自 electron-builder 工具链。
- [ ] 执行 `npm ci` 仅作为基线重现步骤（不得修改 manifest；若 npm ci 因当前未提交状态或环境失败，记录完整错误并停止该子步骤），随后执行 `npm run typecheck`、`npm run typecheck:electron`、`npm run test:run`、`npm run format:check`、`npm run lint`。
- [ ] 执行 `npm run build`、`npm run electron:build`，在可用环境执行 `npm run test:smoke`；记录 `dist/`、`dist-electron/`、`release/` 的文件清单、大小和 manifest 内容。
- [ ] 在 Linux CI 等价环境运行 Electron packaged smoke；在 Windows runner 或现有发布流水线记录 NSIS 构建是否成功、`resources/build-manifest.json` 是否存在、`artifactName` 和 `release/${version}` 输出结构是否符合当前断言。
- [ ] 建立基线报告（建议作为批次分支上的审计 artifact，而非提交敏感日志），包含命令、时间、commit、Node/npm、依赖计数、测试结果和产物 SHA256；将该报告作为所有后续回滚比较对象。
- [ ] 设定验收门：基线重现成功、关键命令有明确结果、没有未解释的 flaky failure；任何基线失败先修复或登记，不把基线失败误归因于升级。
- [ ] 设定回滚动作：不改动基线分支；批次失败时恢复该批次 `package.json` / `package-lock.json` 和配置 diff，删除批次产物，重新执行基线命令确认回滚完整。

**批次 0 风险：** 当前工作区改动会污染 diff；npm registry、Node 版本和缓存会使 audit/lockfile 不可重现；Electron 下载和 Python bundle 会使构建耗时或网络失败。

**批次 0 验收标准：** 有可重跑的基线命令和证据；审计数量与路径已解释；构建、单测、类型检查、lint、Linux/Windows 关键打包行为均有结果；回滚到基线后结果不劣化。

### 批次 1：PostCSS 与 React Router 安全修复

**目标：** 先处理低耦合的 CSS 工具链和导航安全问题，避免与 Electron runtime、builder major 同批引入。

- [x] 在独立批次分支创建升级前测试清单，覆盖 `vite.config.ts` 的 CSS 处理、生产构建、HashRouter/file:// 入口、内部导航、外部链接、反斜杠和协议相对路径输入。
- [x] 根据重新生成的 advisory 选择达到修复范围的 PostCSS 版本，更新 `package.json` 约束并用同版本 npm 生成 `package-lock.json`；不得用 resolutions/overrides 隐藏未经确认的冲突。
- [ ] 选择官方支持且越过当前 React Router advisory 范围的升级路径：若迁移到 React Router 7，先核对 React 18、`react-router-dom` 导出、future flags、TypeScript 类型和 HashRouter 行为；若采用可用的 6.x 安全 backport，记录版本、advisory 范围和为何无需 major migration。
- [x] 审查所有 `Link`、`NavLink`、`useNavigate`、redirect/location 拼接点；对用户或远端可控 URL 只允许预期的站内路径/协议，并用测试证明 `\\`, `//`, `javascript:`, `data:` 和带编码变体不会变成外部 open redirect。
- [x] 运行 `npm ls postcss react-router react-router-dom`、`npm audit --json` 和 `npm audit --omit=dev --json`，确认新 lockfile 没有重复旧版本或新的 critical/high 路径。
- [x] 运行前端单元测试、导航安全测试、`npm run typecheck`、`npm run lint`、`npm run build` 和 Electron stub smoke；验证 `base: './'`、manual chunks、HashRouter 刷新和 packaged `file://` 加载。
- [x] 若此批次失败，恢复两个 manifest 文件和涉及的导航/config 改动，重新执行批次 0 的最小基线命令；禁止为修复 Router 类型错误顺手升级 Vite 或 Electron。
- [ ] 只有在漏洞数量、导航安全用例、前端构建和 Electron smoke 全部满足门槛后，才允许将此批次标记完成。

**批次 1 风险：** React Router 7 可能改变类型、route data API 和 future flag 行为；路径规范化差异可能重新引入白屏或外链跳转；PostCSS 版本变化可能影响 Tailwind/autoprefixer source map。

**批次 1 验收标准：** PostCSS advisory 修复且无旧版本可达路径；Router advisory 修复或有可审计的官方 backport；危险 URL 测试通过；前端构建、HashRouter、Electron smoke 和现有导航测试全部通过，产物与基线无非预期结构变化。

### 批次 2：electron-builder 26

**目标：** 通过升级打包工具链修复 `tar`、builder-util/app-builder-lib 等传递漏洞，同时保持 Linux、Windows NSIS、extraResources、asar 和 manifest 产物契约。

- [ ] 在批次 1 已稳定的基础上，先用 `npm explain tar` 保存升级前路径，并查阅 electron-builder 26 的 Node/npm engine、配置 schema、artifact 输出和 Windows/Win7 相关发布说明。
- [ ] 选择已修复且项目 Node 版本可用的 electron-builder 26 版本；优先验证审计当前给出的 26.15.3 候选，但不得把候选版本直接视为批准版本。
- [ ] 只更新 `electron-builder` 及其必要的 lockfile 子树；若 npm 解析同时改变 `tar`、`app-builder-lib`、`builder-util*`、`electron-publish` 或 `js-yaml`，逐项记录原因、版本和 advisory 关闭情况。
- [ ] 对 `electron-builder.yml` 做 schema/行为核对：`directories.output`、`files` 排除、`extraResources` 三组 Python/backend/sage-core、asar、NSIS include、artifactName、Linux AppImage/deb 和 `mac.target: null` 均须保持意图一致。
- [ ] 运行配置校验和 dry-run packaging；确认 `npm run electron:build`、Linux `npx electron-builder --linux AppImage deb --publish never`、Windows `npx electron-builder --win nsis --publish never` 的输出路径与 CI 脚本断言一致。
- [ ] 解包或挂载 Linux/Windows 产物，验证 `resources/build-manifest.json`、Python runtime、backend、sage-core、`dist/` 和 `dist-electron/` 存在且没有测试文件、map 或 `.git` 泄露；验证 ASAR 内容和 `asarUnpack` 仍符合配置。
- [ ] 运行 Electron stub smoke、stub deep、live boot（可用时）和至少一次 packaged startup；验证后端 resolver、单实例锁、IPC bridge、日志和退出清理行为。
- [ ] 在 builder 26 引入新 warning 或 schema 失败时优先回滚 builder 单项，不修改 Electron runtime；回滚后重新生成 lockfile 并执行 `npm ci` 与批次 0 的打包证据比较。
- [ ] 批次完成前确认 `tar` critical advisory 已关闭或有明确阻断记录；若仍由无法替换的工具链引入，停止发布而不是设置 `npm audit` 忽略。

**批次 2 风险：** electron-builder 26 可能要求更新 Node、改变 artifact 目录或 NSIS 行为；Windows 签名、VC runtime、Python bundle 和缓存下载会导致平台差异；builder 修复不等于 Electron runtime 漏洞已修复。

**批次 2 验收标准：** `tar` 及 builder 传递漏洞达到批准版本范围；Linux/Windows 构建和 manifest 校验通过；安装器能安装、启动、启动 Python 后端并正常退出；产物命名、资源布局和 CI 检查保持兼容；失败可一键恢复到批次 1 lockfile。

#### 批次 2 执行记录（2026-08-30）

- [x] 记录环境：当前分支 `feat/skills-system-remediation`，HEAD `6a2f04692f5a99829dc245226f0b89fd1649bee5`，Node `v25.9.0`，npm `11.12.1`，npm registry 为 `https://registry.npmjs.org/`，`engine-strict=false`；未修改 `release/win7`。
- [x] 升级前 `npm explain tar`：`electron-builder@24.13.3` → `app-builder-lib@24.13.3`，解析 `tar@6.2.1`；升级前完整审计为 `moderate 9 / high 13 / critical 4 / total 26`，生产依赖审计为 `moderate 5 / high 0 / critical 0 / total 5`，`npm audit signatures` 成功。
- [x] 查验 npm 元数据：`electron-builder@26.15.7` 为当前 26.x 稳定版本，Node engine 为 `>=14.0.0`，因此与本地 Node 25 及 CI Node 22 兼容；其 `app-builder-lib`/`dmg-builder` 为 26.15.7，`builder-util` 为 26.15.3。Electron 仍解析为 `21.4.4`，未升级 runtime。
- [x] 仅更新 `package.json` 的 `electron-builder` 约束至 `^26.15.7`，并由 npm 11 重生成 `package-lock.json`；锁树解析 `tar@7.5.22`，来源为 `app-builder-lib@26.15.7`（同时存在 `node-gyp` 工具链路径）。未使用 `--force`、`audit fix` 或 overrides。
- [x] `npm ci` 成功；postinstall 仅报告当前 Linux 无法设置 Electron `chrome-sandbox` SUID 的环境提示。
- [x] 配置核对：builder 26 成功加载 `/home/fz/project/sage/electron-builder.yml`；保留 `directories.output=release/${version}`、asar/files 排除、三组 `extraResources`、NSIS include/installer 选项、artifactName、Linux AppImage/deb 和 `mac.target: null`。构建日志确认 Electron `21.4.4` 正常打包。
- [x] `npm run typecheck`、`npm run typecheck:electron`、`npm run build`、`npm run electron:build` 均成功；`npm run test:smoke` 为 3 passed、16 skipped（既有 TODO/条件跳过）。
- [ ] Linux AppImage/deb 完整打包未通过（2026-08-30 复核）：`npm run test:packaging` 可稳定复现 `2 tests | 1 failed`，唯一失败是缺少 `release/0.4.9-alpha.29/sage_0.4.9-alpha.29_amd64.deb`；AppImage 测试通过，现有 AppImage 为 105,258,931 bytes。单独执行 `timeout 240s env DEBUG=electron-builder,electron-builder:* npx electron-builder --linux deb --publish never` 的完整日志已保存到 `/tmp/sage-builder26-deb-20260830.log`，退出码 1；日志显示 builder 26.15.7 在 `building target=deb` 后尝试下载 `fpm-1.17.0-ruby-3.4.3-linux-amd64.7z`，随后在 `app-builder-lib/.../got` 中抛出 `RequestError`，底层为 Node `AggregateError`/`internalConnectMultiple`（远端 `20.205.243.166:443` ETIMEDOUT）。
- [x] 缓存/本地工具排查完成：`~/.cache/electron` 有 Electron 21.4.4 zip，`~/.cache/electron-builder` 有 AppImage 12.0.1、7zip 和旧 fpm 1.9.3；builder 26 所需的 `fpm@2.1.4/fpm-1.17.0-ruby-3.4.3-linux-amd64-1nk0v` 目录存在但为空，没有可执行 fpm 或归档可供离线恢复。系统 `dpkg-deb` 存在，但 electron-builder 26 的 Linux deb 路径明确使用 fpm；改用手工 `dpkg-deb` 会绕过 builder 产物路径/元数据契约，不能作为本次验收。因此当前没有不改变配置/产品行为且不伪造产物的本地离线修复，未修改 `electron-builder.yml`、测试或 release/win7。
- [x] Linux staging 对照验证：`npx electron-builder --linux dir --publish never` 成功，说明 Electron 21.4.4 unpacked staging 可生成；但它不能替代 deb/AppImage 完整验收，也不能证明缺失的 fpm 资源可用。
- [ ] Windows NSIS 在当前 Linux 环境未完成：builder 26 成功进入 `win-unpacked` 打包阶段，但等待远端请求 600 秒后超时；这是网络/跨平台环境阻断，不是兼容性通过证据。应在 Windows CI/runner 重新执行 NSIS、manifest、安装启动和 Win7 LTS 矩阵。
- [x] Node 矩阵复核完成：electron-builder 26.15.7 自身声明 `engines.node >=14.0.0`，当前本地 Node `v25.9.0` 与 packaging/release CI 的 Node 22 可用；但升级后的 lockfile 还引入 `@electron/rebuild@4.2.0` 与 `node-abi@4.35.0`，二者声明 `>=22.12.0`。因此 `.github/workflows/e2e-pr-gate.yml` 和 `e2e-nightly.yml` 的 Node 20 job 与“安装完整升级后依赖树”存在 engine 约束冲突（当前 `engine-strict=false` 可能只给 warning，不能视为兼容性验证）。建议后续计划统一这些 job 至 Node `22.12+`，或将 E2E 依赖/安装边界明确拆分并单独证明 Node 20 不解析 builder 26 的受限子树；不得用 `--force` 或忽略 engine warning 作为解决方案。
- [x] 将受完整 builder 依赖树影响的 main E2E workflow 统一到明确的 Node `22.12`：`.github/workflows/e2e-pr-gate.yml` 的 stub-smoke、stub-deep、live-boot 及 `.github/workflows/e2e-nightly.yml` 的 live-deep-nightly 均已从 Node 20 提升；`.github/workflows/ci.yml`、`.github/workflows/release.yml` 和 `.github/workflows/release-win7.yml` 的既有 Node 22 设置未改动。验证范围限定为 workflow 静态/YAML 解析、Node 矩阵扫描与 `git diff --check`；尚未在 GitHub runner 上执行这些 workflow，仍需 CI 实际验证 Node 22.12 下的 `npm ci`、构建和 E2E。

**批次 2 结论：** 依赖升级本身与当前 Electron 21/Node 22+目标及配置兼容，且类型检查、前端/Electron 构建和 stub smoke 通过；但 Linux deb 因缺失的远端 fpm 下载、Windows NSIS 因网络/runner 环境、资源 manifest/Python bundle 未准备而阻断，批次 2 **仅完成候选升级验证，不能标记为完整验收或发布批准**。当前无可利用的本地缓存/工具生成可信 deb，保持代码不变。应在网络可用的 Linux CI 重跑 `npx electron-builder --linux AppImage deb --publish never` 并检查 deb/AppImage 内容；在 Windows runner 重跑 `npx electron-builder --win nsis --publish never`、manifest/Python bundle 与 packaged startup；Node20 E2E 矩阵已修正为 Node 22.12，仍需在 CI 实际验证该版本下的 `npm ci`、构建和 E2E，再将批次 2步骤标为完成。

### 批次 3：Vitest / Vite 工具链

**目标：** 修复 Vitest UI critical、Vite high、esbuild/vite-node 传递风险，同时保持 jsdom 测试、coverage、Electron 单测和生产构建稳定。

- [x] 盘点工具链耦合（升级前）：`vitest`/`@vitest/coverage-v8`/`vite-node` 均为 `1.6.1`，`vite` 为 `5.4.21`，`esbuild` 为 `0.21.5`；`@vitest/coverage-v8` 的 peer `vitest=1.6.1` 满足。随后基于 peer/engine 评估实施了 Vitest 3/Vite 7 成组 major 升级，详见执行记录。
- [x] 检查源码、脚本和 CI：没有 `@vitest/ui` 或 `vitest/ui` 的导入/require，也没有 `vitest --ui`；现有 `--ui` 仅属于 Playwright 的 `test:dev` 和测试文档。因此确认该包未被使用，采用仅移除 manifest 条目的最小变更；移除后 `npm ls` 无 peer/config 错误。
- [x] 选择越过 Vitest 3.2.5、vite-node 和 Vite 6.4.2 advisory 范围的兼容版本；本次选择 Vitest `3.2.7`、`vite-node` `3.2.4`、`@vitest/coverage-v8` `3.2.7`、Vite `7.3.6` 和 `@vitejs/plugin-react` `5.2.0`。它们满足当前 Node 22.12+ CI（本地 Node `v25.9.0`）与 React 18；没有选择 npm 自动修复提出的 Vitest 4/Vite 8，因为 plugin-react 6.x 只接受 Vite 8，而 Vitest 4 也要求 Vite 6+，会扩大迁移面。`npm view` 核对了 Node engines 和 peer constraints。
- [x] 更新 `vite.config.ts` 时保持 `base: './'`、React dedupe、manual chunks、`optimizeDeps.exclude`、`esbuild.format: 'esm'`、jsdom、setupFiles 和 `.claude/worktrees`/Playwright 排除规则；本次升级不需要配置变更，已有 loopback server/API binding 回归测试继续保留。
- [x] 升级未要求测试 API/类型迁移；保留全部测试语义、排除规则和 coverage 配置，未扩大 exclude、降低 coverage threshold、关闭错误或删除失败测试。
- [ ] 运行 `npm run test:run`、`npm run test:coverage`（保持项目 coverage 门槛）、Electron 相关 Vitest suites、`npm run typecheck`、`npm run typecheck:electron`、`npm run lint` 和 `npm run build`；类型检查、lint、build 已通过，完整 test/coverage 的唯一失败仍为既有缺失 deb 产物（详见执行记录）。
- [x] 运行 `npm audit --json`、`npm audit --omit=dev --json`、`npm ls vite vitest vite-node esbuild @vitest/ui @vitest/coverage-v8`，确认没有旧的 vulnerable duplicate subtree；记录剩余漏洞是否仅存在于不生产的 dev tool，并进行人工复核。

#### 批次 3 执行记录（2026-08-30）

- [x] 重新核对环境与元数据：本地 Node `v25.9.0`、npm `11.12.1`、registry `https://registry.npmjs.org/`；`npm view` 显示 Vitest `4.1.11` 要求 Vite `^6/^7/^8` 且 `@vitest/coverage-v8` 同版本，Vite `8.2.2` 要求 Node `^20.19.0 || >=22.12.0`，plugin-react `6.1.1` 仅接受 Vite `^8`；因此先评估了 Vitest 4/Vite 8 候选，再选择耦合较小的 Vitest 3/Vite 7 成组迁移。
- [x] 升级前当前审计（移除 `@vitest/ui` 后）为 moderate 9 / high 6 / critical 2 / total 17；生产审计 moderate 5 / high 0 / critical 0 / total 5。剩余关键工具链路径为 Vitest critical（`GHSA-5xrq-8626-4rwp`，影响 `vitest <=3.2.5`，经 `vite`/`vite-node`）和 Vite high（`GHSA-fx2h-pf6j-xcff`，影响 `vite <=6.4.2`），另有 esbuild `GHSA-67mh-4wv8-2f99`。
- [x] 仅移除 `package.json` 中未使用的 `@vitest/ui`，并用 npm 11.12.1 执行 `npm install --package-lock-only` 正常更新 `package-lock.json`；这是最初的低风险步骤，随后同一批次又完成了下述工具链成组升级；未使用 `--force`、`npm audit fix` 或 overrides。
- [x] 在完成 peer/engine 评估后，按最小成组范围更新 `package.json` 与 lockfile：`vitest` `1.6.1 → 3.2.7`、`vite-node`（显式加入）`3.2.4`、`@vitest/coverage-v8` `1.6.1 → 3.2.7`、Vite `5.4.21 → 7.3.6`、`@vitejs/plugin-react` `4.7.0 → 5.2.0`。没有修改 Electron 版本，也没有使用 `npm audit fix --force`、overrides 或 legacy peer resolution。
- [x] `npm ci` 成功（仅有 Linux 无法设置 Electron `chrome-sandbox` SUID 的既有环境提示）。安装后依赖树为 Vitest 3.2.7、coverage-v8 3.2.7、vite-node 3.2.4、Vite 7.3.6、plugin-react 5.2.0、esbuild 0.28.2；`npm ls` 无 peer/config 错误，`@vitest/ui` 不再解析。
- [x] `npm run typecheck`、`npm run typecheck:electron` 和 `npm run build` 成功；Vite 7 生产构建转换 2678 modules，保留 `base: './'` 和既有 chunk 结构意图。
- [ ] `npm run test:run` 与 `npm run test:coverage` 各执行 557 suites / 1451 tests，555 suites、1450 tests 通过；唯一失败 suite/test 是 `tests/packaging/verify-artifacts.spec.ts` 中既有缺失 `release/0.4.9-alpha.29/sage_0.4.9-alpha.29_amd64.deb` 断言，未发现由 Vitest 迁移引起的测试 API 或行为失败。未修改测试或伪造产物。
- [x] `npm run test:smoke` 通过（3 passed、16 skipped；跳过项为既有 TODO/条件跳过）。
- [ ] `npm run lint` 通过无 error（6 个既有 React hook/fast-refresh warnings）；`npm run format:check` 仍被仓库既有 470 个格式问题阻断，未对全仓格式化。
- [x] 升级后完整审计降为 moderate 7 / high 5 / critical 0 / total 12；生产审计仍为 moderate 5 / high 0 / critical 0 / total 5。Vitest critical 与 Vite/esbuild 工具链 high/moderate 已关闭。剩余 high 为 Electron runtime/extract-zip、brace-expansion、js-yaml、undici；这些不属于本批次且不能通过升级开发工具链宣称解决。审计 JSON 保存在 `/tmp/sage-batch3-audit-after-upgrade.json` 和 `/tmp/sage-batch3-audit-prod-after-upgrade.json`。
- [x] Electron runtime 仍为 `21.4.4`，未修改 `release/win7`；本地 `npm ci`/stub smoke 未改变 runtime 或 Win7 分支。

**批次 3 结论（2026-08-30）：** `@vitest/ui` 已确认无源码、脚本、CI 实际使用并安全移除；随后实际完成 Vitest 3.2.7 / vite-node 3.2.4 / coverage-v8 3.2.7 / Vite 7.3.6 / plugin-react 5.2.0 成组升级，Vitest critical 与 Vite/esbuild 工具链 advisory 已关闭。lockfile、干净安装、类型检查、生产构建和 stub smoke 通过；全量测试与 coverage 的唯一失败均为既有缺失 deb 产物，format:check 仍受既有全仓格式问题阻断。因此批次 3 的工具链迁移已完成候选验证，但尚未满足完整验收，不能标记为发布批准。剩余 high/moderate 漏洞及 Electron-builder packaged 验证按后续批次处理。
- [ ] 在 Linux CI 等价环境运行前端构建和 Electron smoke/deep；确认 Vite dev server 仍固定 1420、strictPort 行为不变，Electron `file://` packaged renderer 没有白屏、资源 404 或 React duplicate instance。
- [ ] 若测试工具升级失败，先回滚 Vitest/Vite 全部成组版本（不能只回滚其中一个 `@vitest/*` 包），恢复原 `vite.config.ts`，重新执行批次 2 的构建和 smoke；保留失败日志用于重新评估。
- [ ] 将审计结果分为“发布期依赖”和“仅开发期工具”；critical/high 不能以“dev-only”自动豁免，只有确认不暴露服务且已移除危险 UI 入口时才可进入人工批准流程。

**批次 3 风险：** 已实际选择 Vite 7/Vitest 3；未来升级到 Vite 8/Vitest 4 仍可能要求更新 Node 或改变插件、coverage、fake timers、pool、集成 API。当前 Vite 配置细节仍可能影响 Electron file:// 资源；Vitest UI server 已移除入口，但不可信项目目录仍不得运行测试 UI。

**批次 3 验收标准：** Vitest/Vite/esbuild/vite-node advisory 达到批准修复范围；全量测试和 coverage 门槛通过；Vite dev、生产 build、Electron unit/smoke/deep 均通过；测试发现数与基线可解释；不以删测试或放宽门槛换取绿灯。

### 批次 4：Electron runtime 与 Win7 决策门

**目标：** 在充分证据基础上决定 main 是否升级 Electron runtime，以及 release/win7 是否继续固定 21.4.4；明确安全收益、平台支持和维护边界，而不是将 runtime major 混入普通 npm 批次。

- [ ] 汇总批次 0–3 后仍存在的 Electron、`@electron/get`、`extract-zip` 等漏洞，按 main 发布版本、Win7 LTS 安装器、开发下载链和运行时可达性分类；记录每个 advisory 的修复最低版本和 Electron 官方支持矩阵。
- [ ] 对 `main` 制定独立 runtime 试验分支：候选版本必须同时评估 Chromium/Node 行为、native module ABI、sandbox/contextIsolation、protocol/navigation、clipboard/shell、single-instance、Python child process、preload API 和 renderer CSP/资源加载。
- [ ] 对 `release/win7` 明确决策：在 Electron 21.4.4 仍是 Win7 支持基线时，不升级到放弃 Win7 的现代 Electron；如存在安全 backport、补丁或可接受的补偿控制，记录其生命周期、验证范围和 EOL；没有可接受的安全方案时，提交维护者决定是否停止 Win7 新发布，而不是暗中改变平台承诺。
- [ ] 严禁把 `main` runtime 试验直接合并或同步到 `release/win7`；若某个不涉及 runtime 的安全修复确需同步，使用单独 cherry-pick，分别在 Python 3.11/main 与 Python 3.8/Win7 环境验证，并记录两个 commit 的差异。
- [ ] 更新 Electron 安全回归用例：拒绝不可信导航和外部协议、校验 `shell.openPath`/路径输入、验证 contextIsolation/preload 最小 API、阻止任意窗口打开、验证 ASAR/资源完整性和后端 spawn 参数不受 cwd/用户输入注入。
- [ ] 在 main 候选 runtime 上运行 Linux AppImage/deb、Windows NSIS、Electron stub/deep/live smoke、backend startup/restart、IPC、日志、升级后数据目录兼容性和至少一次冷启动/升级安装测试。
- [ ] 在 release/win7 的 py38 依赖环境和 Windows 7 SP1 目标矩阵（或受控等价验证环境）运行 NSIS 安装、启动、后端健康检查、IPC、卸载/重装和现有 LTS smoke；验证 `KB3033929`、VC runtime、x64 限制和 TLS 说明仍正确。
- [ ] 设定决策门输出三选一：`main 升级并保留 win7 21.4.4`、`两个分支暂不升级并采取补偿控制`、或`暂停相关发布并进入产品/维护者审议`。每个选项必须列安全收益、已知剩余风险、用户影响、支持期限和回滚方案。
- [ ] runtime 候选不能通过时，回滚整个 Electron 版本、lockfile 和配置变更；保留基线 builder 26（若其独立已验收）与已通过的 PostCSS/Router/Vite/Vitest 批次，不做跨批次全量回退。
- [ ] 只有维护者书面确认决策、main 与 Win7 的发布/安全说明同步更新、平台矩阵通过且没有 critical/high 未处理发布阻断时，才关闭本批次。

**批次 4 风险：** Electron 21 已严重落后且无法获得全部上游修复；现代 Electron 通常不再支持 Win7；runtime 升级可能破坏 Chromium 行为、Python spawn、原生模块、安装器和用户数据；双分支误同步会破坏 LTS 承诺。

**批次 4 验收标准：** 有可审计的 runtime/Win7 决策记录；main 的候选版本或“不升级”方案通过安全和功能回归；release/win7 未被未经批准的 runtime 变更污染；两个分支的发布工件、启动、后端健康和关键 IPC 流程均有证据；所有未修复漏洞均有明确 owner、补偿控制和复查日期。

## 短期构建与脚本缓解（不替代依赖升级）

这些措施可在正式批次完成前单独实施，但必须保持最小范围、可审计，并不得声称已经修复上游漏洞：

- [x] 在 CI 增加只读审计 job，固定 Node/npm，运行 `npm ci`、`npm audit --json` 和 `npm audit --omit=dev --json`，上传 JSON artifact；对 critical/high 设置失败门槛或显式人工批准，不使用 `|| true` 吞掉失败。
- [ ] 将 `npm ci`、`npm run build`、`npm run build:electron`、Electron smoke 和发布打包分开记录；脚本失败必须保留退出码和日志，避免后续步骤覆盖根因。
- [x] 检查所有 Vite dev/preview/UI server 仅绑定受控本机地址，CI 不暴露到 `0.0.0.0`；禁止在共享或生产环境运行 `vitest --ui`，并在贡献说明中明确不打开不可信项目目录。
- [ ] 继续使用 lockfile 完整性校验、npm registry HTTPS、缓存 key 包含 `package-lock.json` hash；缓存命中不能绕过 `npm ci` 或审计。
- [ ] 对 Electron 21 运行时实施补偿控制：保持 `contextIsolation`、sandbox/最小 preload API、严格 IPC 输入校验、拒绝不可信导航/外部协议、避免把用户可控 cwd/路径传给 shell 或 child process，并为这些控制保留回归测试。
- [ ] 对 PostCSS source map 相关风险，在所有内部构建入口显式设置可信 `from`/source root，生产构建不接受不可信 source map URL；该措施只降低可达性，不能替代升级。
- [ ] 对 `tar` 使用链，在没有升级 builder 前禁止对不可信归档执行解压或文件覆盖；审查 CI/脚本中是否存在直接调用传递 `tar` 的路径，若存在则改用受控临时目录、路径归一化和目标目录边界检查，并记录待 builder 升级关闭的 advisory。
- [ ] 让发布脚本在打包前输出 Electron、builder、Node、commit、branch 和 Python bundle 版本，并在打包后验证 manifest、资源路径和产物 hash；失败时立即停止发布。

## 跨批次统一验证与回滚协议

- [ ] 每批都执行依赖树审查：`npm ls --all`、`npm explain <package>`、manifest/lockfile diff、`npm audit --json`；确认没有因 peer dependency warning 被静默安装多个不兼容主版本。
- [ ] 每批都执行最小质量门：`npm run typecheck`、`npm run typecheck:electron`、`npm run lint`、对应单元测试、`npm run build` 和 Electron stub smoke；涉及发布工具时追加 Linux/Windows packaging。
- [ ] 涉及导航、IPC、路径、归档或构建输入的批次，必须运行对应安全回归测试并检查错误信息没有泄露路径、token 或内部环境变量。
- [ ] 每批独立提交时使用清晰的 conventional commit（例如 `chore(deps): ...` 或 `fix(security): ...`），但本文件当前阶段不提交；执行者须在用户批准后再进行 git 操作。
- [ ] 发现 critical/high 新增、构建产物契约变化、Win7 启动失败、白屏、后端 spawn 失败或测试门槛下降时立即停止当前批次，保留日志，恢复到最近一个已验收批次，不跨过失败继续升级。
- [ ] 回滚后重新运行 `npm ci`、`npm audit`、关键测试和至少一个构建，比较 lockfile、产物结构、manifest 和启动日志，确认回滚本身没有留下半升级状态。

## 总体完成验收标准

- [ ] `npm audit` 基线中的 critical/high 已全部升级至批准修复范围，或每个剩余项都有经过维护者批准的可达性分析、补偿控制、owner 和复查日期。
- [ ] `tar`、`postcss`、`react-router`、Vite/Vitest 及其相关传递路径均有最新审计证据；不存在用 audit ignore、无边界 force fix 或删除测试掩盖问题的情况。
- [ ] main 的前端 build、Electron build、Linux/Windows 产物、stub/deep/live smoke（按矩阵可用项）全部通过；资源 manifest、asar、Python bundle、artifactName 和输出目录契约保持正确。
- [ ] release/win7 仍保持 Electron 21.4.4、Python 3.8、Win7 LTS 独立约束；没有未经决策门的 runtime 升级、分支合并或依赖自动同步。
- [ ] CI 对 lockfile、审计、类型、lint、coverage、前端构建、Electron smoke 和发布产物有可重复门禁；失败不会被静默吞掉。
- [ ] 所有批次均有升级前后版本表、advisory 路径、测试结果、风险、回滚点和验收记录；完成后才将本文件内容拆入对应技术/用户文档，并从 `docs/plans/` 删除本进行中计划。
