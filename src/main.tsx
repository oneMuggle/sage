import ReactDOM from 'react-dom/client';

import App from './App';
import { AppProviders } from './app/providers';
import './index.css';

// Window-level error handlers — forward to console.error so the Electron
// main process logger (electron/main.ts console-message handler) picks them up.
window.addEventListener('error', (event) => {
  console.error('[sage] window error:', event.message, event.error?.stack);
});
window.addEventListener('unhandledrejection', (event) => {
  console.error('[sage] unhandledrejection:', event.reason);
});

// 注意: 关闭 React.StrictMode — 在 chat 流程里它会导致 useChat 双挂载,
// 渲染层 sendMessage 被双调用, 后端两次 LLM 调用 + 两次 IPC listen + 流事件混乱。
// StrictMode 的副作用检测价值在 Electron 桌面端不值得这种代价。
// (PR #34 cancel-prev 在 StrictMode 双实例下不解决问题,因为每个实例的 cancelRef 独立)
// 如要恢复 StrictMode, 需先把 chatStream 改成模块级去重 (相同 args 合并)。
ReactDOM.createRoot(document.getElementById('root')!).render(
  <AppProviders>
    <App />
  </AppProviders>,
);
