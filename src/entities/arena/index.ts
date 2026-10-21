export * from './api';
export function formatArenaEntityBarrelSummary(): string {
  return 'module=entities/arena · base=/api/v1/arena · reExports=api';
}

export function formatArenaEntityBarrelJson(): string {
  return JSON.stringify({
    module: 'entities/arena',
    base: '/api/v1/arena',
    reExports: ['api'],
  });
}

