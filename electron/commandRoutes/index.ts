import type { CommandRoute } from '../commands';
import { chatRoutes } from './chat';
import { integrationRoutes } from './integrations';
import { memoryRoutes } from './memory';
import { officeRoutes } from './office';
import { orchestrationRoutes } from './orchestration';
import { projectRoutes } from './projects';
import { promptRoutes } from './prompts';
import { sessionRoutes } from './sessions';
import { settingsRoutes } from './settings';
import { skillRoutes } from './skills';

export const DOMAIN_ROUTES: Record<string, CommandRoute> = {
  ...chatRoutes,
  ...sessionRoutes,
  ...memoryRoutes,
  ...settingsRoutes,
  ...skillRoutes,
  ...orchestrationRoutes,
  ...officeRoutes,
  ...projectRoutes,
  ...promptRoutes,
  ...integrationRoutes,
};
