// src/platform.ts
export interface PlatformAdapter {
  isElectron(): boolean;
  invoke<T>(channel: string, ...args: unknown[]): Promise<T>;
  on(channel: string, callback: (...args: unknown[]) => void): () => void;
  getAuthHeaders(): Record<string, string>;
}

interface ElectronEventBridge {
  on?: (channel: string, callback: (...args: unknown[]) => void) => void;
  off?: (channel: string, callback: (...args: unknown[]) => void) => void;
}

function getElectronApi(): NonNullable<Window['electronAPI']> | undefined {
  if (typeof window === 'undefined' || !window.electronAPI) return undefined;
  return window.electronAPI;
}

class ElectronPlatform implements PlatformAdapter {
  isElectron(): boolean {
    return getElectronApi() !== undefined;
  }

  async invoke<T>(channel: string, ...args: unknown[]): Promise<T> {
    const api = getElectronApi();
    if (!api) throw new Error('electronAPI not available');
    return api.invoke<T>(channel, args[0] as Record<string, unknown> | undefined);
  }

  on(channel: string, callback: (...args: unknown[]) => void): () => void {
    const api = getElectronApi() as (NonNullable<Window['electronAPI']> & ElectronEventBridge) | undefined;
    if (!api?.on) return () => {};
    api.on(channel, callback);
    return () => api.off?.(channel, callback);
  }

  getAuthHeaders(): Record<string, string> {
    return {};
  }
}

class WebPlatform implements PlatformAdapter {
  private token: string;

  constructor() {
    const urlToken = new URL(window.location.href).searchParams.get('token');
    if (urlToken) {
      localStorage.setItem('sage_auth_token', urlToken);
      window.history.replaceState(null, '', window.location.pathname);
    }
    this.token = localStorage.getItem('sage_auth_token') || '';
  }

  isElectron(): boolean {
    return false;
  }

  async invoke<T>(channel: string, ..._args: unknown[]): Promise<T> {
    const endpoint = this.mapChannelToEndpoint(channel);
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${this.token}`,
      },
      body: JSON.stringify({}),
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }

    return response.json();
  }

  on(_channel: string, _callback: (...args: unknown[]) => void): () => void {
    return () => {};
  }

  getAuthHeaders(): Record<string, string> {
    return { Authorization: `Bearer ${this.token}` };
  }

  private mapChannelToEndpoint(channel: string): string {
    const mapping: Record<string, string> = {
      'chat:send': '/api/v1/chat/send',
      'chat:stream': '/api/v1/chat/stream',
      'session:list': '/api/v1/sessions',
      'session:create': '/api/v1/sessions',
      'memory:list': '/api/v1/memory/list',
      'project:list': '/api/v1/projects',
      'project:create': '/api/v1/projects',
    };
    return mapping[channel] || `/api/v1/${channel}`;
  }
}

export const platform: PlatformAdapter =
  typeof window !== 'undefined' && 'electronAPI' in window
    ? new ElectronPlatform()
    : new WebPlatform();
