import { useEffect } from 'react';
import { BrowserRouter } from 'react-router-dom';

// import { NavHistoryProvider } from './app/providers/NavHistoryProvider'; // REMOVED for diagnostic
import { loadCurrentSessionId } from './entities/session/storage';
import { useStore } from './shared/lib/store';

function App() {
  useEffect(() => {
    loadCurrentSessionId().then((id) => {
      if (id) {
        useStore.getState().setCurrentSessionId(id);
      }
    });
  }, []);

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
      <BrowserRouter>
        <div
          data-testid="sage-no-navhistory"
          style={{ color: 'magenta', padding: 20, fontSize: 24 }}
        >
          NavHistoryProvider REMOVED for diagnostic
          <div data-testid="sage-no-routes" style={{ color: 'cyan', padding: 20, fontSize: 24 }}>
            ROUTES REMOVED for diagnostic — if this cyan div appears, throw is inside Routes
          </div>
          {/* CommandPalette REMOVED for diagnostic — if more content appears, throw is in CommandPalette */}
        </div>
      </BrowserRouter>
    </>
  );
}

export default App;
