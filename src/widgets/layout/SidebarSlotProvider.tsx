import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { ReactNode } from 'react';

export interface SidebarSlotContextValue {
  /** 侧栏内容列中的 portal 挂载点；侧栏折叠或未挂载时为 null。 */
  slotEl: HTMLElement | null;
  setSlotEl: (el: HTMLElement | null) => void;
  /**
   * slot 内的操作需要收起侧栏覆盖层（移动端抽屉）。桌面端无覆盖层，
   * Layout 未提供回调时为空操作。
   */
  dismissOverlay: () => void;
}

const noop = () => {};

const SidebarSlotContext = createContext<SidebarSlotContextValue>({
  slotEl: null,
  setSlotEl: noop,
  dismissOverlay: noop,
});

interface SidebarSlotProviderProps {
  children: ReactNode;
  /** 移动端抽屉中操作 slot 后收起抽屉；路由不变（如文档 tab 内选中文档）时也能关闭。 */
  onSlotAction?: () => void;
}

export function SidebarSlotProvider({ children, onSlotAction }: SidebarSlotProviderProps) {
  const [slotEl, setSlotEl] = useState<HTMLElement | null>(null);
  const dismissOverlay = useCallback(() => {
    onSlotAction?.();
  }, [onSlotAction]);
  const value = useMemo<SidebarSlotContextValue>(
    () => ({ slotEl, setSlotEl, dismissOverlay }),
    [slotEl, dismissOverlay],
  );

  return <SidebarSlotContext.Provider value={value}>{children}</SidebarSlotContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useSidebarSlot(): SidebarSlotContextValue {
  return useContext(SidebarSlotContext);
}
