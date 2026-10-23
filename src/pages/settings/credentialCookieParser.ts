export interface CookieImportItem {
  name: string;
  value: string;
}

export function parseCookieHeader(raw: string): CookieImportItem[] {
  const items = raw
    .split(';')
    .map((segment) => segment.trim())
    .filter(Boolean)
    .map((segment) => {
      const separator = segment.indexOf('=');
      if (separator <= 0) throw new Error('invalid_cookie_format');
      return {
        name: segment.slice(0, separator).trim(),
        value: segment.slice(separator + 1).trim(),
      };
    });
  if (items.length === 0 || items.some((item) => !item.name)) {
    throw new Error('invalid_cookie_format');
  }
  return items;
}

export function formatCookieHeaderSummary(items: CookieImportItem[]): string {
  return `count=${items.length} · names=[${items.map((i) => i.name).join(',')}]`;
}

export function formatCookieHeaderJson(items: CookieImportItem[]): string {
  return JSON.stringify(
    {
      count: items.length,
      names: items.map((i) => i.name),
    },
    null,
    2,
  );
}

export function auditCredentialCookieParserGovernance(): {
  module: 'src/pages/settings/credentialCookieParser.ts';
  phase: 'P174';
  domain: 'settings';
  sampleCookieCount: number;
  compliant: boolean;
} {
  const items = parseCookieHeader('sid=abc123; theme=dark');
  return {
    module: 'src/pages/settings/credentialCookieParser.ts',
    phase: 'P174',
    domain: 'settings',
    sampleCookieCount: items.length,
    compliant: items.length === 2,
  };
}
