/**
 * App component — diagnostic-only stub.
 *
 * The real implementation (BrowserRouter, Layout, NavHistoryProvider, all
 * the page components) has been temporarily removed to isolate a white-
 * screen bug. Two visible markers are rendered so we can confirm App
 * function body executes and React can mount its output:
 *
 *   - red banner at the top
 *   - green diagnostic block below the banner
 *
 * If the user sees both markers, App itself is fine and the white-screen
 * is downstream (Layout, providers, etc.). If the user sees only the red
 * banner, the green block failed to render (an error is being thrown
 * somewhere between the two).
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
        ✅ MINIMAL TEST 渲染成功 — App 组件 + 第二个 div 都工作
        <br />
        如果你看到这条绿条,说明 App function body 完整执行,问题在原 Layout 树。
      </div>
    </>
  );
}

export default App;
