/**
 * 启动屏 (splash window)。
 *
 * 背景：后端健康检查在慢机器上要 50–90s (BACKEND_HEALTH_TIMEOUT_MS，conda +
 * uvicorn 冷启动实测 50–65s)，而主窗口此前排在 waitForBackend() 之后创建 ——
 * 用户双击图标后近一分钟没有任何视觉反馈。启动屏在 app.whenReady() 一开始
 * 就显示，把「准备环境 → 自检 → 启动后端服务」各阶段实时反馈给用户。
 *
 * 实现约束：
 *  - 页面用自包含 data: URL：不进 electron-builder 打包清单，dev / 打包 /
 *    Win7 路径完全一致，也避免与 main 分支 / release/win7 分支的打包配置
 *    产生 cherry-pick 冲突。
 *  - 已耗时由页面内联脚本自计时（setInterval），主进程只在阶段切换时推一次
 *    文案（executeJavaScript + textContent，无 HTML 注入面）。
 *  - 幂等 + 不阻塞：所有函数在启动屏不存在（CI / 演示模式 / 已关闭）时
 *    静默 no-op；创建失败只记日志，绝不阻断启动主链路（对齐
 *    setupTrayAndGlobalShortcut 的降级原则）。
 *  - 主窗口 ready-to-show 后由 createMainWindow() 调 closeSplashWindow()，
 *    窗口显示与启动屏消失同帧发生，无白屏间隙。
 */
import { BrowserWindow } from 'electron';
import { logger } from './logger';

let splashWin: BrowserWindow | null = null;

/** 配色对齐应用暗色主题 (src/index.css: --color-primary-rgb 暗色 129 140 248)。 */
const SPLASH_HTML = `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body { margin: 0; height: 100%; }
  body {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 18px; background: #141519; color: #e8e9ed; overflow: hidden;
    font-family: 'Segoe UI', 'Microsoft YaHei UI', 'PingFang SC', sans-serif;
    user-select: none; cursor: default;
  }
  .logo { font-size: 34px; font-weight: 700; letter-spacing: 0.5px; }
  .bar { width: 200px; height: 3px; border-radius: 2px; background: rgba(255,255,255,.12); overflow: hidden; }
  .bar i { display: block; width: 40%; height: 100%; border-radius: 2px; background: #818cf8; animation: sweep 1.4s ease-in-out infinite; }
  @keyframes sweep { 0% { transform: translateX(-100%); } 100% { transform: translateX(350%); } }
  .stage { font-size: 13px; color: #9aa0ab; min-height: 18px; }
  .elapsed { font-size: 11px; color: #5c626d; min-height: 14px; }
</style>
</head>
<body>
  <div class="logo">Sage</div>
  <div class="bar"><i></i></div>
  <div class="stage" id="stage">正在准备环境…</div>
  <div class="elapsed" id="elapsed"></div>
<script>
  var t0 = Date.now();
  setInterval(function () {
    var s = Math.floor((Date.now() - t0) / 1000);
    document.getElementById('elapsed').textContent = s >= 3 ? '已 ' + s + ' 秒' : '';
  }, 500);
</script>
</body>
</html>`;

const SPLASH_URL = `data:text/html;charset=utf-8,${encodeURIComponent(SPLASH_HTML)}`;

export function createSplashWindow(): void {
  if (splashWin) return;
  try {
    const win = new BrowserWindow({
      width: 420,
      height: 260,
      resizable: false,
      minimizable: false,
      maximizable: false,
      fullscreenable: false,
      frame: false,
      center: true,
      show: false,
      title: 'Sage',
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
        sandbox: true,
      },
    });
    win.once('ready-to-show', () => win.show());
    void win.loadURL(SPLASH_URL).catch((e: Error) => {
      logger.warn('splash: loadURL failed', { error: e.message });
    });
    splashWin = win;
    win.on('closed', () => {
      splashWin = null;
    });
  } catch (err) {
    logger.warn('splash: create failed — continuing without splash', { error: String(err) });
    splashWin = null;
  }
}

/** 阶段文案更新；stage 为纯文本，经 JSON.stringify 注入 textContent。 */
export function updateSplashStage(stage: string): void {
  const win = splashWin;
  if (!win || win.isDestroyed()) return;
  void win.webContents
    .executeJavaScript(
      `(function(){var s=document.getElementById('stage');if(s)s.textContent=${JSON.stringify(stage)};})()`,
    )
    .catch(() => undefined);
}

export function closeSplashWindow(): void {
  const win = splashWin;
  splashWin = null;
  if (win && !win.isDestroyed()) {
    win.destroy();
  }
}
