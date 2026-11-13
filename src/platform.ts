// src/platform.ts
export interface PlatformAdapter {
  isElectron(): boolean;
  invoke<T>(channel: string, ...args: any[]): Promise<T>;
  on(channel: string, callback: (...args: any[]) => void): () => void;
  getAuthHeaders(): Record<string, string>;
}

class ElectronPlatform implements PlatformAdapter {
  isElectron(): boolean {
    return typeof window !== 'undefined' && 'electronAPI' in window;
  }

  async invoke<T>(channel: string, ...args: any[]): Promise<T> {
    return (window as any).electronAPI.invoke(channel, ...args);
  }

  on(channel: string, callback: (...args: any[]) => void): () => void {
    (window as any).electronAPI.on(channel, callback);
    return () => (window as any).electronAPI.off(channel, callback);
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

  async invoke<T>(channel: string, ...args: any[]): Promise<T> {
    const endpoint = this.mapChannelToEndpoint(channel);
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${this.token}`,
      },
      body: JSON.stringify({ args }),
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }

    return response.json();
  }

  on(channel: string, _callback: (...args: any[]) => void): () => void {
    console.warn(`Web mode does not support IPC: ${channel}`);
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
