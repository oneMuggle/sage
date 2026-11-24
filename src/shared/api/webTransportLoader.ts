/**
 * 懒加载网页回退模式的传输层（`webTransport.ts`）。
 *
 * 桌面端产物（`vite build`，mode=production）里这段代码永远走不到 ——
 * Electron 渲染层始终有 `window.electronAPI`，走 IPC 桥，根本不会进同源
 * HTTP 回退。但 `webTransport.ts` 静态引入 `electron/commands.ts` →
 * `electron/commandRoutes/**`（约 130KB 源码的 IPC 路由表）；一旦被渲染层
 * 静态引入，桌面端安装包会白白变大，并直接撞上渲染产物体积门禁
 * （`scripts/check-bundle-size.mjs`：主 chunk 预算 2.25MB、总量 12MB）。
 *
 * 这里用 Vite 的 `import.meta.env.MODE` 做编译期开关：Vite 在 `vite build`
 * （mode=production）时把它替换成字面量 `'production'`，Rollup 随即把
 * `production` 分支连同下面的动态 import 一起消除 —— 桌面端产物里就不含
 * 那张路由表；网页模式（mode=web）、开发模式与测试模式保留真实实现。
 *
 * 注：electron tsc（`tsconfig.electron.json`，module=commonjs）因渲染侧
 * 的共享模块间接引用而顺带 type-check 此文件。commonjs 模式下 `import.meta`
 * 不被允许，故用 `@ts-ignore` 抑制（`@ts-expect-error` 会在渲染侧 tsc 触发
 * "未使用"TS2578）—— 该文件不会被 Electron 主进程调用，Vite 构建仍正常
 * 替换该字面量。
 */
import type * as WebTransport from './webTransport';

// 见文件头注释：electron tsc (commonjs) 不接受 import.meta，用 `@ts-ignore`
// 抑制（`@ts-expect-error` 在渲染侧 tsc 会报"未使用"TS2578）。Vite 构建阶段
// 会把它静态替换为字面量 mode，tree-shaking 正常工作。
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore
const _MODE: string = import.meta.env.MODE;

export async function loadWebTransport(): Promise<typeof WebTransport> {
  if (_MODE === 'production') {
    // 桌面端产物已剔除网页传输层（见文件头注释）——走到这里说明调用方
    // 在 Electron 里误走了网页回退分支。
    throw new Error('网页模式传输层在桌面端产物中不可用');
  }
  return import('./webTransport');
}
