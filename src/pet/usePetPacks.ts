/**
 * Resolve the selected pet pack (built-in or user-imported) in renderers.
 *
 * User pack manifests are fetched from the main process and refreshed when
 * the selected pack id changes (import switches config to the new pack, and
 * deleting the selected pack switches back to the built-in one).
 */
import { useEffect, useState } from 'react';

import type { PetPackManifestBridge } from '../shared/types/electron-api';

import { DAFEIYU_PACK, packFromManifest, type PetPack } from './engine/packs';

export function usePetPacks(packId: string | null | undefined): PetPack {
  const [userPacks, setUserPacks] = useState<PetPack[]>([]);
  const pet = typeof window !== 'undefined' ? window.electronAPI?.pet : undefined;

  useEffect(() => {
    if (!pet?.listPacks) return undefined;
    let alive = true;
    pet
      .listPacks()
      .then((list: PetPackManifestBridge[]) => {
        if (!alive) return;
        setUserPacks(
          list
            .map(packFromManifest)
            .filter((pack): pack is PetPack => pack !== null),
        );
      })
      .catch(() => {
        // Keep the built-in pack; a failed list must not blank the pet.
      });
    return () => {
      alive = false;
    };
  }, [pet, packId]);

  if (!packId || packId === DAFEIYU_PACK.id) return DAFEIYU_PACK;
  return userPacks.find((pack) => pack.id === packId) ?? DAFEIYU_PACK;
}
