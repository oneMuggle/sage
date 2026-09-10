import type { UpdateProvider, ProviderType } from './base';
import type { ProviderInstanceConfig } from '../providerConfig';

export type ProviderFactory = (config: ProviderInstanceConfig) => UpdateProvider;

export class ProviderRegistry {
  private factories = new Map<ProviderType, ProviderFactory>();

  register(type: ProviderType, factory: ProviderFactory): void {
    this.factories.set(type, factory);
  }

  build(config: ProviderInstanceConfig): UpdateProvider {
    const factory = this.factories.get(config.type);
    if (!factory) {
      throw new Error(`No factory registered for type: ${config.type}`);
    }
    return factory(config);
  }

  has(type: ProviderType): boolean {
    return this.factories.has(type);
  }

  registeredTypes(): ProviderType[] {
    return Array.from(this.factories.keys());
  }
}
