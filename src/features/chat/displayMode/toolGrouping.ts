import type { ToolCall } from '../../../shared/lib/store';
import type { Artifact } from '../../artifacts/artifactApi';

export function hasSpecialToolCalls(
  toolCalls: ToolCall[],
  artifactsByToolCall: Record<string, Artifact[]> | undefined,
): boolean {
  return toolCalls.some(
    (tc) =>
      Boolean(tc.metadata?.blockReason) ||
      Boolean(tc.metadata?.imageData) ||
      Boolean(tc.metadata?.mediaRefs?.length) ||
      Boolean(tc.id && artifactsByToolCall?.[tc.id]?.length),
  );
}

export function canGroupToolCalls(
  toolCalls: ToolCall[],
  isStreaming: boolean,
  threshold: number,
  artifactsByToolCall: Record<string, Artifact[]> | undefined,
): boolean {
  if (isStreaming) return false;
  if (toolCalls.length < threshold) return false;
  if (hasSpecialToolCalls(toolCalls, artifactsByToolCall)) return false;
  return true;
}

export function toolGroupSummary(
  toolCalls: ToolCall[],
  canGroup: boolean,
  _threshold: number,
): string {
  if (!canGroup) return '';
  const counts = new Map<string, number>();
  for (const tc of toolCalls) {
    counts.set(tc.name, (counts.get(tc.name) ?? 0) + 1);
  }
  return Array.from(counts.entries())
    .slice(0, 3)
    .map(([name, cnt]) => (cnt > 1 ? `${name}×${cnt}` : name))
    .join(' · ');
}
