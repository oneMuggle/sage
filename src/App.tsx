import { ErrorBoundary } from './app/providers/ErrorBoundary';
import { ResizeDivider } from './widgets/layout/ResizeDivider';
import { Sidebar } from './widgets/layout/Sidebar';
import { Titlebar } from './widgets/layout/Titlebar';

/**
 * App component — diagnostic build isolates which Layout subcomponent
 * throws by wrapping each in its own ErrorBoundary. Previous attempts
 * showed App and Layout are healthy; the error is somewhere inside.
 * The full original Layout tree couldn't surface the message because
 * it threw a bare `new Error()` with empty message at minified code
 * boundary, so we need granular per-child boundaries to localize.
 */

function App() {
  return (
    <>
      {/* DIAGNOSTIC BANNER — red bar so we can confirm App mounted */}
      <div
        data-testid="sage-app-mounted"
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          zIndex: 999999,
          background: 'red',
          color: 'white',
          padding: '8px 12px',
          fontFamily: 'sans-serif',
          fontSize: 14,
          fontWeight: 'bold',
        }}
      >
        APP MOUNTED — 如果你看到这条红条,App 组件正常挂载
      </div>
      <div
        data-testid="sage-minimal-router"
        style={{
          position: 'fixed',
          top: 60,
          left: 0,
          right: 0,
          zIndex: 999998,
          background: '#0a0a0a',
          color: '#00ff00',
          padding: '20px',
          fontFamily: 'monospace',
          fontSize: 18,
          fontWeight: 'bold',
        }}
      >
        ✅ MINIMAL TEST 渲染成功 — App 组件健康
        <br />
        下方是按组件拆分的 ErrorBoundary 测试,会显示哪个组件抛错
      </div>
      <div
        data-testid="sage-layout-test"
        style={{
          position: 'fixed',
          top: 180,
          left: 0,
          right: 0,
          zIndex: 999997,
          background: '#1a1a1a',
          color: 'white',
          padding: '20px',
          fontFamily: 'monospace',
          fontSize: 16,
        }}
      >
        <h3>Layout 子组件拆分测试:</h3>
        <div style={{ border: '2px solid #00ff00', padding: '8px', margin: '8px 0' }}>
          <strong>1. Titlebar 测试:</strong>
          <ErrorBoundary>
            <Titlebar />
          </ErrorBoundary>
        </div>
        <div style={{ border: '2px solid #00ff00', padding: '8px', margin: '8px 0' }}>
          <strong>2. Sidebar 测试 (no width prop):</strong>
          <ErrorBoundary>
            <Sidebar />
          </ErrorBoundary>
        </div>
        <div style={{ border: '2px solid #00ff00', padding: '8px', margin: '8px 0' }}>
          <strong>3. ResizeDivider 测试 (no handlers):</strong>
          <ErrorBoundary>
            <ResizeDivider onMouseDown={() => {}} />
          </ErrorBoundary>
        </div>
      </div>
    </>
  );
}

export default App;
