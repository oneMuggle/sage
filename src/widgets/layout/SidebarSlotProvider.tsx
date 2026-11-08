import { createContext, useContext, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

export interface SidebarSlotContextValue {
  /** 侧栏内容列中的 portal 挂载点；侧栏折叠或未挂载时为 null。 */
  slotEl: HTMLElement | null;
  setSlotEl: (el: HTMLElement | null) => void;
}

const SidebarSlotContext = createContext<SidebarSlotContextValue>({
  slotEl: null,
  setSlotEl: () => {},
});

export function SidebarSlotProvider({ children }: { children: ReactNode }) {
  const [slotEl, setSlotEl] = useState<HTMLElement | null>(null);
  const value = useMemo<SidebarSlotContextValue>(() => ({ slotEl, setSlotEl }), [slotEl]);

  return <SidebarSlotContext.Provider value={value}>{children}</SidebarSlotContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useSidebarSlot(): SidebarSlotContextValue {
  return useContext(SidebarSlotContext);
}
