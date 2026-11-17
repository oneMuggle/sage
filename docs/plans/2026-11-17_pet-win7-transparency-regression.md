# Win7 桌宠透明回归修复（alpha.81+）实施计划

> 状态：实施完成，待 PR（2026-11-17）
> 分支：`fix/win7-pet-transparency-regression`（基于 `release/win7`）

## 1. 背景与目标

用户反馈：最新 win7 安装包（alpha.82-win7）桌宠始终显示为不透明黑底窗口，设置页「兼容模式」选择 `自动 / 开启 / 关闭` 均无差异；而在 alpha.80-win7 及更早版本中，选择「关闭」时桌宠背景是透明的。

**根因（已定位）**：`db016b86b`（PR #3031 → win7 #3034，进入 alpha.81-win7）把 `compatibilityEnabled()` 改为"旧版 Windows 一律返回 true"：

```ts
// alpha.80-win7 及更早
function compatibilityEnabled(config) {
  if (config.compatibilityMode === 'on') return true;
  if (config.compatibilityMode === 'off') return false; // off = 真透明
  return isLegacyWindows(); // auto 在 Win7 才不透明
}

// alpha.81-win7 起
if (legacyWindows && !experiment) return true; // 三档全部强制不透明
```

该修复本意是保护"Win7 关闭 Aero / 远程桌面下透明窗口黑屏或不可见"的机器，但一刀切误伤了 DWM 桌面合成正常、透明可用的机器（用户环境即属此类——alpha.80 在相同 GPU 开关下透明工作正常）。alpha.82 之后 PR #3040 追加的 `SAGE_PET_TRANSPARENCY_EXPERIMENT=1` 环境变量逃生门，普通安装包用户无法使用。

**目标**：

1. 恢复 `compatibilityMode=off` → 透明窗口的语义，让 DWM 正常的 Win7 用户重新获得透明桌宠。
2. 对 DWM 桌面合成不可用（无 Aero / Basic 主题 / 远程桌面）的机器，仍精准强制不透明，并在设置页如实解释原因，避免"桌宠消失"。
3. `auto` 语义保持 alpha.80 行为不变（Win7 上不透明），不引入新的平台差异。
4. 单测覆盖新判定；更新技术/用户文档。

## 2. 涉及文件与模块

| 文件                                                | 改动                                                                                                                                    |
| --------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `electron/pet/windows.ts`                           | `compatibilityEnabled()` 恢复 off 透明 + 新增 DWM 合成上下文（`systemPreferences.isAeroGlassEnabled()`）；导出 `resolveCompatContext()` |
| `electron/pet/types.ts`                             | 新增 `PetCompatStatus` 类型                                                                                                             |
| `electron/pet/controller.ts`                        | 新增 `getCompatStatus()` 方法                                                                                                           |
| `electron/pet/ipc.ts`                               | 新增 `pet:get-compat-status` invoke 通道（仅主窗口可用）                                                                                |
| `electron/preload.ts`                               | `pet.getCompatStatus()` 桥接                                                                                                            |
| `src/shared/types/electron-api.d.ts`                | 新增 `PetCompatStatusBridge` 类型与桥方法签名                                                                                           |
| `src/pages/settings/PetTab.tsx`                     | 读取兼容状态；DWM 不可用时禁用「关闭」档并展示原因；本地 `Select` 支持 `disabled`                                                       |
| `src/shared/lib/i18n/locales/{zh,en}/*.ts`          | 更新兼容模式提示文案，新增「无桌面合成」提示                                                                                            |
| `electron/__tests__/petCompatibility.test.ts`       | 覆盖 legacy/off/DWM 组合                                                                                                                |
| `src/pages/settings/__tests__/PetTab.pack.test.tsx` | 桥 mock 补 `getCompatStatus`                                                                                                            |
| `docs/technical/{114,117}-desktop-pet.md`           | Win7 兼容模式章节与已知限制更新                                                                                                         |
| `docs/user-manual/{26,27}-desktop-pet.md`           | 兼容模式说明与 FAQ 更新                                                                                                                 |

## 3. 技术方案

### 3.1 判定函数（`electron/pet/windows.ts`）

```ts
export interface CompatContext {
  legacyWindows: boolean;
  /** Win7 透明窗口依赖 DWM 桌面合成；无 Aero / Basic / 远程桌面时为 false。 */
  dwmComposition: boolean;
}

export function resolveCompatContext(): CompatContext {
  return { legacyWindows: isLegacyWindows(), dwmComposition: hasDwmComposition() };
}

function hasDwmComposition(): boolean {
  if (process.platform !== 'win32') return true;
  try {
    return systemPreferences.isAeroGlassEnabled();
  } catch {
    return true; // fail-open：检测失败时不强制不透明
  }
}

export function compatibilityEnabled(
  config: PetConfig,
  context: CompatContext = resolveCompatContext(),
): boolean {
  if (config.compatibilityMode === 'on') return true;
  if (config.compatibilityMode === 'off') {
    return context.legacyWindows && !context.dwmComposition; // 仅 DWM 不可用时强制不透明
  }
  return context.legacyWindows; // auto：保持 alpha.80 语义
}
```

要点：

- `systemPreferences.isAeroGlassEnabled()` 是 Electron 21 自带同步 API（`node_modules/electron/electron.d.ts:8649`），零启动开销，无需 PowerShell/原生模块。
- `SAGE_PET_TRANSPARENCY_EXPERIMENT` 仍保留在 `electron/main.ts`，仅影响 GPU 开关组合，不再参与 `off` 判定。
- `PetWindow` 构造/`needsRecreate`/`applyConfig` 继续调用 `compatibilityEnabled()`，每次解析上下文（DWM 状态为同步轻量调用）；切换 off/on 会正确触发窗口重建。

### 3.2 设置页状态透出

新增 IPC `pet:get-compat-status`（仅 `isMainSender` 可用），返回：

```ts
interface PetCompatStatus {
  legacyWindows: boolean;
  dwmComposition: boolean;
  /** true = 即使选择 off 也只能不透明（legacy 且 DWM 关闭） */
  transparencyUnavailable: boolean;
}
```

`PetTab` 据此：

- `transparencyUnavailable` 为 true 时禁用「关闭」选项并显示原因文案；
- 其余情况保持三档可选；
- 提示文案改为"若看不到桌宠或背景变黑，请改用自动/开启"。

### 3.3 文案调整

- `settings.pet.compatibility_desc`：说明 off = 透明、Win7 需 Aero。
- `settings.pet.compatibility_win7_hint`：黑底/不可见时改用自动或开启。
- 新增 `settings.pet.compatibility_no_dwm`：当前系统未开启桌面合成（Aero），透明不可用。

## 4. 实施步骤

- [x] 步骤 1：更新 `electron/__tests__/petCompatibility.test.ts`，先写失败用例（legacy+off+DWM开 → false；legacy+off+DWM关 → true；auto/on 不变），运行确认失败
- [x] 步骤 2：修改 `electron/pet/windows.ts` 判定函数与 DWM 上下文，测试转绿
- [x] 步骤 3：`electron/pet/types.ts` 增加 `PetCompatStatus`；`controller.ts` 增加 `getCompatStatus()`
- [x] 步骤 4：`electron/pet/ipc.ts` 注册 `pet:get-compat-status`；`preload.ts` / `electron-api.d.ts` 桥接
- [x] 步骤 5：`PetTab.tsx` 展示与禁用逻辑；更新 zh/en 文案；补 PetTab 测试 mock
- [x] 步骤 6：更新技术/用户手册中 Win7 兼容模式说明
- [x] 步骤 7：运行单测（electron pet 相关 + PetTab）、`tsc`/lint
- [ ] 步骤 8：提交并开 PR 到 `release/win7`

## 5. 测试与验收

**自动化**：

```bash
cd .worktrees/fix-win7-pet-transparency-regression
../../node_modules/.bin/vitest run electron/__tests__/petCompatibility.test.ts
../../node_modules/.bin/vitest run src/pages/settings/__tests__/PetTab.pack.test.tsx
../../node_modules/.bin/tsc --noEmit
```

**真机验收（Win7）**：

1. 设置「关闭」→ 桌宠透明背景恢复，角色可见，透明区域点击穿透正常；
2. 设置「开启 / 自动」→ 不透明窗口（深色底），整窗可交互；
3. 关闭系统 Aero（Basic 主题 / 远程桌面）→ 设置页禁用「关闭」并显示原因，桌宠仍可见；
4. 切换设置即时生效（窗口重建），位置记忆不丢失。

## 6. 风险与依赖

| 风险                                                  | 缓解                                                                                                       |
| ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| 个别 Win7 机器 DWM 报告开启但透明仍失败（#3031 场景） | 用户可改选「自动/开启」回退；提示文案明确指引；保留 `SAGE_PET_TRANSPARENCY_EXPERIMENT` 供 GPU 开关矩阵排查 |
| `isAeroGlassEnabled()` 在非 Windows 调用异常          | `process.platform` 门控 + try/catch fail-open                                                              |
| main 分支行为受影响                                   | 仅 `isLegacyWindows()` 为 true 时路径变化，Win10+ 行为不变；同一补丁 cherry-pick 到 main 保持对齐          |
| 架构棘轮行数                                          | 本方案不改 `electron/main.ts`，不涉及 baseline                                                             |
