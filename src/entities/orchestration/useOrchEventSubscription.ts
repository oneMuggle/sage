/**
 * Hook for subscribing to orchestration run events via Electron IPC relay.
 *
 * Manages subscription lifecycle: subscribe on mount (or when runId changes),
 * unsubscribe on unmount. Feeds events into runControlStore.
 */

import { useEffect, useRef } from 'react';

import { subscribeOrchEvents } from '../../shared/api/orchEventStream';
import type { RunSnapshot } from '../../shared/api/orchEvents';
import { orchRunControlClient } from '../../shared/api/orchRunControlClient';

import { useRunControlStore } from './runControlStore';

/**
 * Subscribe to a run's events and feed them into the store.
 *
 * @param runId - Run ID to subscribe to (null to skip subscription)
 * @param enabled - Whether to enable subscription (default: true)
 */
export function useOrchEventSubscription(runId: string | null, enabled = true) {
  const abortRef = useRef<AbortController | null>(null);
  const applyEvent = useRunControlStore((s) => s.applyEvent);
  const setRunSnapshot = useRunControlStore((s) => s.setRunSnapshot);
  const setConnectionStatus = useRunControlStore((s) => s.setConnectionStatus);
  const markGapDetected = useRunControlStore((s) => s.markGapDetected);
  const lastSeqByRunId = useRunControlStore((s) => s.lastSeqByRunId);

  useEffect(() => {
    if (!runId || !enabled) return;

    // Abort any previous subscription
    abortRef.current?.abort();
    const abort = new AbortController();
    abortRef.current = abort;

    setConnectionStatus('connecting');

    // Fetch initial snapshot
    orchRunControlClient
      .getSnapshot(runId)
      .then((snapshot: RunSnapshot) => {
        if (abort.signal.aborted) return;
        setRunSnapshot(snapshot);
        setConnectionStatus('connected');
      })
      .catch((err: unknown) => {
        if (abort.signal.aborted) return;
        console.error('Failed to fetch run snapshot:', err);
        setConnectionStatus('disconnected');
      });

    // Subscribe to event stream
    const afterSeq = lastSeqByRunId.get(runId) ?? 0;
    const stream = subscribeOrchEvents({
      runId,
      afterSeq,
      signal: abort.signal,
      onError: (err) => {
        if (abort.signal.aborted) return;
        console.error('Event stream error:', err);
        setConnectionStatus('disconnected');
        // Mark resync required for gap recovery
        markGapDetected(runId, afterSeq + 1, afterSeq);
      },
    });

    // Consume events
    (async () => {
      try {
        for await (const event of stream) {
          if (abort.signal.aborted) break;
          applyEvent(event);

          // Check for sequence gaps
          const expectedSeq = (lastSeqByRunId.get(runId) ?? 0) + 1;
          if (event.seq > expectedSeq) {
            markGapDetected(runId, expectedSeq, event.seq);
          }
        }
        if (!abort.signal.aborted) {
          setConnectionStatus('disconnected');
        }
      } catch (err: unknown) {
        if (abort.signal.aborted) return;
        console.error('Event stream iteration error:', err);
        setConnectionStatus('disconnected');
      }
    })();

    // Cleanup on unmount or runId change
    return () => {
      abort.abort();
      abortRef.current = null;
      setConnectionStatus('disconnected');
    };
  }, [
    runId,
    enabled,
    applyEvent,
    setRunSnapshot,
    setConnectionStatus,
    markGapDetected,
    lastSeqByRunId,
  ]);
}
