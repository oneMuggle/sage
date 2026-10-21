// src/features/chat/index.ts
export { AtFileMenu } from './AtFileMenu';
export { AtEntityMenu } from './AtEntityMenu';
export { getEntityKindSuggestions, parseEntityRefQuery } from './entityRefs';
export { useAtFileQuery } from './useAtFileQuery';
export { useBtwCommand } from './useBtwCommand';
export { BtwOverlay } from './BtwOverlay';
export { useBtwState } from '../../entities/chat/btwState';
export function formatChatFeatureBarrelSummary(): string {
  return 'module=features/chat · exports=8 · includes=AtFileMenu,AtEntityMenu,BtwOverlay';
}

export function formatChatFeatureBarrelJson(): string {
  return JSON.stringify({
    module: 'features/chat',
    exportCount: 8,
    components: ['AtFileMenu', 'AtEntityMenu', 'BtwOverlay'],
  });
}

