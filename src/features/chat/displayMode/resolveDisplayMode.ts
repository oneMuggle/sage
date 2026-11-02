import { DEFAULT_DISPLAY_MODE, isValidDisplayMode, type DisplayMode } from './types';

export type { DisplayMode } from './types';

export interface DisplayModeInput {
  messageOverride?: DisplayMode | null;
  sessionOverride?: DisplayMode | null;
  globalDefault?: DisplayMode | null;
}

export interface DisplayContract {
  showThinkingPanel: boolean;
  thinkingDefaultExpanded: boolean;
  autoExpandWhileStreaming: boolean;
  toolGroupThreshold: number;
  toolGroupDefaultExpanded: boolean;
  toolCardDefaultCollapsed: boolean;
}

const CONTRACTS: Record<DisplayMode, DisplayContract> = {
  detail: {
    showThinkingPanel: true,
    thinkingDefaultExpanded: true,
    autoExpandWhileStreaming: true,
    toolGroupThreshold: 3,
    toolGroupDefaultExpanded: true,
    toolCardDefaultCollapsed: false,
  },
  trace: {
    showThinkingPanel: true,
    thinkingDefaultExpanded: false,
    autoExpandWhileStreaming: false,
    toolGroupThreshold: 3,
    toolGroupDefaultExpanded: true,
    toolCardDefaultCollapsed: true,
  },
  result: {
    showThinkingPanel: false,
    thinkingDefaultExpanded: false,
    autoExpandWhileStreaming: false,
    toolGroupThreshold: 1,
    toolGroupDefaultExpanded: false,
    toolCardDefaultCollapsed: true,
  },
};

export function resolveDisplayMode(input: DisplayModeInput): DisplayMode {
  const { messageOverride, sessionOverride, globalDefault } = input;
  if (messageOverride && isValidDisplayMode(messageOverride)) return messageOverride;
  if (sessionOverride && isValidDisplayMode(sessionOverride)) return sessionOverride;
  if (globalDefault && isValidDisplayMode(globalDefault)) return globalDefault;
  return DEFAULT_DISPLAY_MODE;
}

export function getDisplayContract(mode: DisplayMode): DisplayContract {
  return CONTRACTS[mode] ?? CONTRACTS[DEFAULT_DISPLAY_MODE];
}
