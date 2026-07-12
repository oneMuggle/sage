import { ErrorBoundary } from './app/providers/ErrorBoundary';
import { Layout } from './widgets/layout';

/**
 * App component — diagnostic build reintroduces Layout inside an inner
 * ErrorBoundary so the specific throw inside Layout (or any of its
 * children) is captured and shown to the user.
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
      {/* MINIMAL TEST: position below red banner with bright contrast so visible */}
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
        下方是 Layout 测试 (被 ErrorBoundary 包裹,抛出错误会显示 '出错了')
      </div>
      {/* Layout test — if it throws, ErrorBoundary will catch and show '出错了' */}
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
        <h3>Layout 测试 (下面这个):</h3>
        <ErrorBoundary>
          <Layout />
        </ErrorBoundary>
      </div>
    </>
  );
}

export default App;
