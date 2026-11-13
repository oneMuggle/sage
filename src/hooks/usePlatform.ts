// src/hooks/usePlatform.ts
import { platform } from '../platform';

export function usePlatform() {
  return {
    isElectron: platform.isElectron(),
    invoke: platform.invoke.bind(platform),
    on: platform.on.bind(platform),
    authHeaders: platform.getAuthHeaders(),
  };
}
