// src/widgets/pet/PetDock.tsx
//
// 应用内宠物 dock（P1）——挂在 Layout 角落（TaskCenterWidget 上方），
// 状态来自 usePetSnapshot。点击 → 跳到当前优先关联会话（Sidebar
// handleOpenSession 同款路子：setCurrentSessionId + SPA navigate）。
// 多会话并行时徽标显示在流式会话数。

import { useLocation, useNavigate } from 'react-router-dom';

import { getPetPack } from '../../features/pet/builtinPacks';
import { useImportedPacksBootstrap } from '../../features/pet/importedPacks';
import { usePetStore } from '../../features/pet/petStore';
import { usePetSnapshot } from '../../features/pet/usePetSnapshot';
import { useChatStreamStore } from '../../features/send-message/chatStreamStore';
import { useI18n } from '../../shared/lib/i18n';
import { useStore } from '../../shared/lib/store';

import { PetVisual } from './PetVisual';

import './pet.css';

export function PetDock() {
  const enabled = usePetStore((s) => s.enabled);
  const petId = usePetStore((s) => s.petId);
  const snapshot = usePetSnapshot();
  const streamSessions = useChatStreamStore((s) => s.sessions);
  const setCurrentSessionId = useStore((s) => s.setCurrentSessionId);
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useI18n();
  useImportedPacksBootstrap();

  if (!enabled) return null;

  const pack = getPetPack(petId);
  const busyCount = Object.keys(streamSessions).filter(
    (id) => id !== '__btw__' && streamSessions[id]?.streaming != null,
  ).length;
  const label = t(`pet.state.${snapshot.state}`);

  const handleClick = () => {
    if (!snapshot.sessionId) return;
    setCurrentSessionId(snapshot.sessionId);
    if (location.pathname !== '/chat') {
      // SPA navigation（对齐 Sidebar.handleOpenSession）：整页刷新会闪白屏
      navigate('/chat');
    }
  };

  return (
    <div data-testid="pet-dock" data-state={snapshot.state} className="fixed bottom-28 right-4 z-40">
      <button
        type="button"
        onClick={handleClick}
        aria-label={label}
        title={snapshot.sessionId ? `${label} · ${t('pet.click.jump')}` : label}
        className="relative block cursor-pointer bg-transparent border-0 p-0"
      >
        <PetVisual pack={pack} state={snapshot.state} />
        {busyCount > 1 && (
          <span
            data-testid="pet-badge"
            className="absolute -top-1 -right-1 min-w-4 h-4 px-1 rounded-full bg-primary text-white text-[10px] leading-4 text-center"
          >
            {busyCount}
          </span>
        )}
      </button>
    </div>
  );
}
