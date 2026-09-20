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
