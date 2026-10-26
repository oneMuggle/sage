/**
 * Date conversion utilities shared between TodoCreateForm and TodoRowEditor.
 */

export function toLocalDatetimeValue(isoStr: string): string {
  // Convert ISO8601 to local datetime input value format "YYYY-MM-DDTHH:mm"
  try {
    const d = new Date(isoStr);
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch {
    return '';
  }
}

export function toIsoString(localDatetimeValue: string): string {
  // Convert local datetime input "YYYY-MM-DDTHH:mm" to ISO8601
  if (!localDatetimeValue) return '';
  try {
    return new Date(localDatetimeValue).toISOString();
  } catch {
    return '';
  }
}
